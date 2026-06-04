"""This file contains the LangGraph Agent/workflow and interactions with the LLM."""

import asyncio
from typing import (
    AsyncGenerator,
    Optional,
)
from urllib.parse import quote_plus

from asgiref.sync import sync_to_async
from langchain_core.messages import (
    BaseMessage,
    ToolMessage,
    convert_to_openai_messages,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import (
    END,
    StateGraph,
)
from langgraph.graph.state import (
    Command,
    CompiledStateGraph,
)
from langgraph.types import (
    RunnableConfig,
    StateSnapshot,
)
from mem0 import AsyncMemory
from psycopg_pool import AsyncConnectionPool

from src.config.settings import (
    Environment,
    settings,
)
from src.agent.tools import tools
from src.system.logs import logger
from src.system.telemetry import llm_inference_duration_seconds
from src.system.tracing import (
    capture_current_trace_context,
    get_langchain_callbacks,
    record_llm_call,
    record_tool_execution,
    start_trace_span,
    update_current_span,
)
from src.agent.prompts import load_system_prompt, load_rag_system_prompt
from src.data.schemas import (
    GraphState,
    Message,
)
from src.services.llm_provider import llm_service
from src.utils import (
    dump_messages,
    prepare_messages,
    process_llm_response,
)
from src.retrieval.hybrid import rag_retrieve


class LangGraphAgent:
    """Manages the LangGraph Agent/workflow and interactions with the LLM.

    This class handles the creation and management of the LangGraph workflow,
    including LLM interactions, database connections, and response processing.
    """

    def __init__(self):
        """Initialize the LangGraph Agent with necessary components."""
        # Use the LLM service with tools bound
        self.llm_service = llm_service
        self.llm_service.bind_tools(tools)
        self.tools_by_name = {tool.name: tool for tool in tools}
        self._connection_pool: Optional[AsyncConnectionPool] = None
        self._graph: Optional[CompiledStateGraph] = None
        self.memory: Optional[AsyncMemory] = None
        self._memory_unavailable: bool = False
        logger.info(
            "langgraph_agent_initialized",
            model=settings.DEFAULT_LLM_MODEL,
            provider=settings.ACTIVE_LLM_PROVIDER.value,
            long_term_memory_enabled=settings.LONG_TERM_MEMORY_AVAILABLE,
            environment=settings.ENVIRONMENT.value,
        )

    def _build_long_term_memory_config(self) -> dict:
        """Build the mem0 configuration for long-term memory."""
        return {
            "vector_store": {
                "provider": "pgvector",
                "config": settings.get_long_term_memory_vector_store_config(),
            },
            "llm": {
                "provider": settings.get_long_term_memory_llm_provider_name(),
                "config": settings.get_long_term_memory_llm_config(),
            },
            "embedder": {
                "provider": settings.LONG_TERM_MEMORY_EMBEDDER_PROVIDER,
                "config": settings.get_long_term_memory_embedder_config(),
            },
            # "custom_fact_extraction_prompt": load_custom_fact_extraction_prompt(),
        }

    async def _long_term_memory(self) -> Optional[AsyncMemory]:
        """Initialize the long term memory when the required providers are configured."""
        if self._memory_unavailable:
            return None

        if not settings.LONG_TERM_MEMORY_AVAILABLE:
            logger.warning(
                "long_term_memory_disabled",
                reason=settings.LONG_TERM_MEMORY_DISABLED_REASON,
                llm_provider=settings.LONG_TERM_MEMORY_PROVIDER.value,
                embedder_provider=settings.LONG_TERM_MEMORY_EMBEDDER_PROVIDER or "none",
            )
            self._memory_unavailable = True
            return None

        if self.memory is None:
            try:
                self.memory = await AsyncMemory.from_config(config_dict=self._build_long_term_memory_config())
                logger.info(
                    "long_term_memory_initialized",
                    llm_provider=settings.LONG_TERM_MEMORY_PROVIDER.value,
                    embedder_provider=settings.LONG_TERM_MEMORY_EMBEDDER_PROVIDER,
                    collection_name=settings.LONG_TERM_MEMORY_COLLECTION_NAME,
                )
            except Exception as e:
                self._memory_unavailable = True
                logger.error(
                    "long_term_memory_initialization_failed",
                    error=str(e),
                    llm_provider=settings.LONG_TERM_MEMORY_PROVIDER.value,
                    embedder_provider=settings.LONG_TERM_MEMORY_EMBEDDER_PROVIDER or "none",
                )
                return None
        return self.memory

    async def _get_connection_pool(self) -> AsyncConnectionPool:
        """Get a PostgreSQL connection pool using environment-specific settings.

        Returns:
            AsyncConnectionPool: A connection pool for PostgreSQL database.
        """
        if self._connection_pool is None:
            try:
                # Configure pool size based on environment
                max_size = settings.POSTGRES_POOL_SIZE

                connection_url = (
                    "postgresql://"
                    f"{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
                    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
                )

                self._connection_pool = AsyncConnectionPool(
                    connection_url,
                    open=False,
                    max_size=max_size,
                    kwargs={
                        "autocommit": True,
                        "connect_timeout": 5,
                        "prepare_threshold": None,
                    },
                )
                await self._connection_pool.open()
                logger.info("connection_pool_created", max_size=max_size, environment=settings.ENVIRONMENT.value)
            except Exception as e:
                logger.error("connection_pool_creation_failed", error=str(e), environment=settings.ENVIRONMENT.value)
                # In production, we might want to degrade gracefully
                if settings.ENVIRONMENT == Environment.PRODUCTION:
                    logger.warning("continuing_without_connection_pool", environment=settings.ENVIRONMENT.value)
                    return None
                raise e
        return self._connection_pool

    async def _get_relevant_memory(self, user_id: str, query: str) -> str:
        """Get the relevant memory for the user and query.

        Args:
            user_id (str): The user ID.
            query (str): The query to search for.

        Returns:
            str: The relevant memory.
        """
        with start_trace_span(
            "memory.search",
            input={"user_id": str(user_id), "query_preview": query[:200]},
            metadata={"query_length": len(query)},
        ):
            try:
                memory = await self._long_term_memory()
                if not memory:
                    update_current_span(output={"result_count": 0, "enabled": False})
                    return ""

                results = await memory.search(user_id=str(user_id), query=query)
                memories = results.get("results", [])
                update_current_span(output={"result_count": len(memories), "enabled": True})
                return "\n".join([f"* {result['memory']}" for result in memories])
            except Exception as e:
                update_current_span(level="ERROR", status_message=str(e))
                logger.error("failed_to_get_relevant_memory", error=str(e), user_id=user_id, query=query)
                return ""

    async def _update_long_term_memory(
        self,
        user_id: str,
        messages: list[dict],
        metadata: dict = None,
        trace_context: Optional[dict[str, str]] = None,
    ) -> None:
        """Update the long term memory.

        Args:
            user_id (str): The user ID.
            messages (list[dict]): The messages to update the long term memory with.
            metadata (dict): Optional metadata to include.
        """
        with start_trace_span(
            "memory.update",
            trace_context=trace_context,
            input={"message_count": len(messages), "user_id": str(user_id)},
            metadata=metadata,
        ):
            try:
                memory = await self._long_term_memory()
                if not memory:
                    update_current_span(output={"enabled": False, "message_count": len(messages)})
                    return

                await memory.add(messages, user_id=str(user_id), metadata=metadata)
                update_current_span(output={"enabled": True, "message_count": len(messages)})
                logger.info("long_term_memory_updated_successfully", user_id=user_id)
            except Exception as e:
                update_current_span(level="ERROR", status_message=str(e))
                logger.exception(
                    "failed_to_update_long_term_memory",
                    user_id=user_id,
                    error=str(e),
                )

    async def _retrieve(self, state: GraphState, config: RunnableConfig) -> Command:
        """Retrieve relevant document chunks for the user query.

        Runs hybrid search (vector + BM25) and parent document recall,
        then updates the state with formatted context and citation sources.
        """
        # Extract the last user message as the search query
        last_user_msg = ""
        for msg in reversed(state.messages):
            if hasattr(msg, "type") and msg.type == "human":
                last_user_msg = msg.content
                break
            elif isinstance(msg, dict) and msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        if not last_user_msg:
            logger.warning("retrieve_no_user_message")
            return Command(update={"retrieved_context": "", "sources": []}, goto="chat")

        with start_trace_span(
            "retrieve",
            input={"query": last_user_msg[:200]},
            metadata={"query_length": len(last_user_msg)},
        ):
            try:
                result = await rag_retrieve(
                    query=last_user_msg,
                    top_k=5,
                    include_parent_docs=True,
                )
                update_current_span(output={
                    "chunk_count": len(result["chunks"]),
                    "parent_count": len(result["parent_chunks"]),
                    "has_context": bool(result["context"]),
                })

                logger.info(
                    "retrieve_completed",
                    query_length=len(last_user_msg),
                    chunks=len(result["chunks"]),
                    sources=len(result["sources"]),
                )

                return Command(
                    update={
                        "retrieved_context": result["context"],
                        "sources": result["sources"],
                    },
                    goto="chat",
                )
            except Exception as e:
                logger.error("retrieve_failed", error=str(e))
                update_current_span(level="ERROR", status_message=str(e))
                # Degrade gracefully: continue without context
                return Command(
                    update={"retrieved_context": "", "sources": []},
                    goto="chat",
                )

    async def _chat(self, state: GraphState, config: RunnableConfig) -> Command:
        """Process the chat state and generate a response.

        Args:
            state (GraphState): The current state of the conversation.

        Returns:
            Command: Command object with updated state and next node to execute.
        """
        # Get the current LLM instance for metrics
        current_llm = self.llm_service.get_llm()
        model_name = (
            current_llm.model_name
            if current_llm and hasattr(current_llm, "model_name")
            else settings.DEFAULT_LLM_MODEL
        )

        # Use RAG prompt when retrieved context is available, otherwise default
        if state.retrieved_context:
            SYSTEM_PROMPT = load_rag_system_prompt(
                long_term_memory=state.long_term_memory,
                retrieved_context=state.retrieved_context,
            )
        else:
            SYSTEM_PROMPT = load_system_prompt(long_term_memory=state.long_term_memory)

        # Prepare messages with system prompt
        messages = prepare_messages(state.messages, current_llm, SYSTEM_PROMPT)

        trace_context = capture_current_trace_context()
        
        try:
            # Use LLM service with automatic retries and circular fallback
            with llm_inference_duration_seconds.labels(model=model_name).time():
                response_message = await self.llm_service.call(dump_messages(messages), config=config)

            # Process response to handle structured content blocks
            response_message = process_llm_response(response_message)

            logger.info(
                "llm_response_generated",
                session_id=config["configurable"]["thread_id"],
                model=model_name,
                environment=settings.ENVIRONMENT.value,
            )

            # Determine next node based on whether there are tool calls
            if response_message.tool_calls:
                goto = "tool_call"
            else:
                goto = END

            return Command(update={"messages": [response_message]}, goto=goto)
        except Exception as e:
            logger.error(
                "llm_call_failed_all_models",
                session_id=config["configurable"]["thread_id"],
                error=str(e),
                environment=settings.ENVIRONMENT.value,
            )
            raise Exception(f"failed to get llm response after trying all models: {str(e)}")

    # Define our tool node
    async def _tool_call(self, state: GraphState, config: RunnableConfig) -> Command:
        """Process tool calls from the last message.

        Args:
            state: The current agent state containing messages and tool calls.

        Returns:
            Command: Command object with updated messages and routing back to chat.
        """
        outputs = []
        for tool_call in state.messages[-1].tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            
            with record_tool_execution(
                tool_name,
                tool_args=tool_args,
                trace_context=capture_current_trace_context(),
            ):
                try:
                    import time
                    start_time = time.time()
                    tool_result = await self.tools_by_name[tool_name].ainvoke(tool_args, config=config)
                    duration_ms = (time.time() - start_time) * 1000
                    
                    # Update span with result and duration
                    update_current_span(
                        output=tool_result,
                        metadata={"duration_ms": round(duration_ms, 2)},
                    )
                except Exception as e:
                    update_current_span(
                        level="ERROR",
                        status_message=str(e),
                    )
                    raise
            
            outputs.append(
                ToolMessage(
                    content=tool_result,
                    name=tool_name,
                    tool_call_id=tool_call["id"],
                )
            )
        return Command(update={"messages": outputs}, goto="chat")

    async def create_graph(self) -> Optional[CompiledStateGraph]:
        """Create and configure the LangGraph workflow.

        #为了构建一个具备持久化对话记忆且在生产环境中高可用的 AI 代理执行引擎，
        该函数创建并编译了一个 LangGraph 状态图（CompiledStateGraph），
        它是通过编排“聊天”与“工具调用”节点的流转路线、动态挂载 PostgreSQL 数据库作为记忆检查点，
        并配合环境感知的异常降级机制将其 `compile`（打包）成可执行对象来实现的。

        Returns:
            Optional[CompiledStateGraph]: The configured LangGraph instance or None if init fails
        """
        if self._graph is None:
            try:
                graph_builder = StateGraph(GraphState)
                graph_builder.add_node("retrieve", self._retrieve, ends=["chat"])
                graph_builder.add_node("chat", self._chat, ends=["tool_call", END])
                graph_builder.add_node("tool_call", self._tool_call, ends=["chat"])
                graph_builder.set_entry_point("retrieve")
                graph_builder.set_finish_point("chat")

                # Get connection pool (may be None in production if DB unavailable)
                connection_pool = await self._get_connection_pool()
                if connection_pool:
                    checkpointer = AsyncPostgresSaver(connection_pool)
                    await checkpointer.setup()
                else:
                    # In production, proceed without checkpointer if needed
                    checkpointer = None
                    if settings.ENVIRONMENT != Environment.PRODUCTION:
                        raise Exception("Connection pool initialization failed")

                self._graph = graph_builder.compile(
                    checkpointer=checkpointer, name=f"{settings.PROJECT_NAME} Agent ({settings.ENVIRONMENT.value})"
                )

                logger.info(
                    "graph_created",
                    graph_name=f"{settings.PROJECT_NAME} Agent",
                    environment=settings.ENVIRONMENT.value,
                    has_checkpointer=checkpointer is not None,
                )
            except Exception as e:
                logger.error("graph_creation_failed", error=str(e), environment=settings.ENVIRONMENT.value)
                # In production, we don't want to crash the app
                if settings.ENVIRONMENT == Environment.PRODUCTION:
                    logger.warning("continuing_without_graph")
                    return None
                raise e

        return self._graph

    async def get_response(
        self,
        messages: list[Message],
        session_id: str,
        user_id: Optional[str] = None,
    ) -> dict:
        """Get a response from the LLM.

        Args:
            messages (list[Message]): The messages to send to the LLM.
            session_id (str): The session ID for Langfuse tracking.
            user_id (Optional[str]): The user ID for Langfuse tracking.

        Returns:
            dict: {"messages": [...], "sources": [...]}
        """
        if self._graph is None:
            self._graph = await self.create_graph()

        callbacks = get_langchain_callbacks()
        trace_context = capture_current_trace_context()
        config = {
            "configurable": {"thread_id": session_id},
            "metadata": {
                "user_id": user_id,
                "session_id": session_id,
                "environment": settings.ENVIRONMENT.value,
                "debug": settings.DEBUG,
                "trace_id": trace_context["trace_id"] if trace_context else None,
            },
            "tags": ["chatbot", "sync", settings.ACTIVE_LLM_PROVIDER.value],
        }
        if callbacks:
            config["callbacks"] = callbacks

        with start_trace_span(
            "agent.get_response",
            input={
                "session_id": session_id,
                "user_id": str(user_id) if user_id is not None else None,
                "message_count": len(messages),
            },
            metadata={
                "stream": False,
                "provider": settings.ACTIVE_LLM_PROVIDER.value,
                "model": settings.DEFAULT_LLM_MODEL,
            },
        ):
            relevant_memory = (
                await self._get_relevant_memory(user_id, messages[-1].content)
            ) or "No relevant memory found."
            try:
                response = await self._graph.ainvoke(
                    input={"messages": dump_messages(messages), "long_term_memory": relevant_memory},
                    config=config,
                )
                memory_update_trace_context = capture_current_trace_context()
                # Run memory update in background without blocking the response
                asyncio.create_task(
                    self._update_long_term_memory(
                        user_id,
                        convert_to_openai_messages(response["messages"]),
                        config["metadata"],
                        trace_context=memory_update_trace_context,
                    )
                )
                processed_messages = self.__process_messages(response["messages"])
                sources = response.get("sources", [])
                update_current_span(output={"response_message_count": len(processed_messages), "source_count": len(sources)})
                return {"messages": processed_messages, "sources": sources}
            except Exception as e:
                update_current_span(level="ERROR", status_message=str(e))
                logger.exception("Error getting response", session_id=session_id, error=str(e))
                raise

    async def get_stream_response(
        self, messages: list[Message], session_id: str, user_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Get a stream response from the LLM.

        Args:
            messages (list[Message]): The messages to send to the LLM.
            session_id (str): The session ID for the conversation.
            user_id (Optional[str]): The user ID for the conversation.

        Yields:
            str: Tokens of the LLM response.
        """
        callbacks = get_langchain_callbacks()
        trace_context = capture_current_trace_context()
        config = {
            "configurable": {"thread_id": session_id},
            "metadata": {
                "user_id": user_id,
                "session_id": session_id,
                "environment": settings.ENVIRONMENT.value,
                "debug": settings.DEBUG,
                "trace_id": trace_context["trace_id"] if trace_context else None,
            },
            "tags": ["chatbot", "stream", settings.ACTIVE_LLM_PROVIDER.value],
        }
        if callbacks:
            config["callbacks"] = callbacks
        if self._graph is None:
            self._graph = await self.create_graph()

        with start_trace_span(
            "agent.get_stream_response",
            input={
                "session_id": session_id,
                "user_id": str(user_id) if user_id is not None else None,
                "message_count": len(messages),
            },
            metadata={
                "stream": True,
                "provider": settings.ACTIVE_LLM_PROVIDER.value,
                "model": settings.DEFAULT_LLM_MODEL,
            },
        ):
            relevant_memory = (
                await self._get_relevant_memory(user_id, messages[-1].content)
            ) or "No relevant memory found."
            full_response = ""

            try:
                async for token, _ in self._graph.astream(
                    {"messages": dump_messages(messages), "long_term_memory": relevant_memory},
                    config,
                    stream_mode="messages",
                ):
                    try:
                        token_content = token.content
                        full_response += token_content
                        yield token_content
                    except Exception as token_error:
                        logger.error("Error processing token", error=str(token_error), session_id=session_id)
                        # Continue with next token even if current one fails
                        continue

                # After streaming completes, get final state
                state: StateSnapshot = await sync_to_async(self._graph.get_state)(config=config)
                sources = []
                if state.values and "messages" in state.values:
                    memory_update_trace_context = capture_current_trace_context()
                    asyncio.create_task(
                        self._update_long_term_memory(
                            user_id,
                            convert_to_openai_messages(state.values["messages"]),
                            config["metadata"],
                            trace_context=memory_update_trace_context,
                        )
                    )
                    sources = state.values.get("sources", [])

                # Yield sources as a special event
                import json as _json
                yield f"data: {_json.dumps({'type': 'sources', 'sources': sources})}\n\n"

                update_current_span(output={"response_length": len(full_response), "source_count": len(sources)})
            except Exception as stream_error:
                update_current_span(level="ERROR", status_message=str(stream_error))
                logger.error("Error in stream processing", error=str(stream_error), session_id=session_id)
                raise stream_error

    async def get_chat_history(self, session_id: str) -> list[Message]:
        """Get the chat history for a given thread ID.

        Args:
            session_id (str): The session ID for the conversation.

        Returns:
            list[Message]: The chat history.
        """
        if self._graph is None:
            self._graph = await self.create_graph()

        state: StateSnapshot = await sync_to_async(self._graph.get_state)(
            config={"configurable": {"thread_id": session_id}}
        )
        return self.__process_messages(state.values["messages"]) if state.values else []

    def __process_messages(self, messages: list[BaseMessage]) -> list[Message]:
        openai_style_messages = convert_to_openai_messages(messages)
        # keep just assistant and user messages
        return [
            Message(role=message["role"], content=str(message["content"]))
            for message in openai_style_messages
            if message["role"] in ["assistant", "user"] and message["content"]
        ]

    async def clear_chat_history(self, session_id: str) -> None:
        """Clear all chat history for a given thread ID.

        Args:
            session_id: The ID of the session to clear history for.

        Raises:
            Exception: If there's an error clearing the chat history.
        """
        try:
            # Make sure the pool is initialized in the current event loop
            conn_pool = await self._get_connection_pool()

            # Use a new connection for this specific operation
            async with conn_pool.connection() as conn:
                for table in settings.CHECKPOINT_TABLES:
                    try:
                        await conn.execute(f"DELETE FROM {table} WHERE thread_id = %s", (session_id,))
                        logger.info(f"Cleared {table} for session {session_id}")
                    except Exception as e:
                        logger.error(f"Error clearing {table}", error=str(e))
                        raise

        except Exception as e:
            logger.error("Failed to clear chat history", error=str(e))
            raise
