"""Chatbot API endpoints for handling chat interactions.

This module provides endpoints for chat interactions, including regular chat,
streaming chat, message history management, and chat history clearing.
"""

import json
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from fastapi.responses import StreamingResponse

from src.interface.auth import get_current_session
from src.config.settings import settings
from src.agent.workflow import LangGraphAgent
from src.system.rate_limit import limiter
from src.system.logs import logger
from src.system.telemetry import llm_stream_duration_seconds
from src.system.tracing import (
    add_score,
    capture_current_trace_context,
    update_current_trace,
)
from src.data.models.session import Session
from src.data.schemas.chat import (
    ChatRequest,
    ChatResponse,
    Message,
    SourceCitation,
    StreamResponse,
)

router = APIRouter()
agent = LangGraphAgent()


def _format_passthrough_stream_event(chunk: str) -> str | None:
    """Return a normalized SSE payload for known control events emitted by the agent."""
    if not chunk.startswith("data: "):
        return None

    try:
        event = json.loads(chunk[6:].strip())
    except json.JSONDecodeError:
        return None

    if event.get("type") != "sources":
        return None

    return f"data: {json.dumps(event)}\n\n"


def _build_trace_input(chat_request: ChatRequest) -> dict:
    """Build a concise trace payload for a chat request."""
    last_user_message = next(
        (message.content for message in reversed(chat_request.messages) if message.role == "user"),
        chat_request.messages[-1].content,
    )
    return {
        "message_count": len(chat_request.messages),
        "last_user_message": last_user_message,
    }


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat"][0])
async def chat(
    request: Request,
    chat_request: ChatRequest,
    session: Session = Depends(get_current_session),
):
    """Process a chat request using LangGraph.

    Args:
        request: The FastAPI request object for rate limiting.
        chat_request: The chat request containing messages.
        session: The current session from the auth token.

    Returns:
        ChatResponse: The processed chat response.

    Raises:
        HTTPException: If there's an error processing the request.
    """
    try:
        logger.info(
            "chat_request_received",
            session_id=session.id,
            message_count=len(chat_request.messages),
        )

        trace_context = capture_current_trace_context()
        update_current_trace(
            name="chatbot.chat",
            user_id=str(session.user_id),
            session_id=session.id,
            input=_build_trace_input(chat_request),
            tags=["chatbot", "sync"],
            metadata={
                "environment": settings.ENVIRONMENT.value,
                "provider": settings.ACTIVE_LLM_PROVIDER.value,
                "model": settings.DEFAULT_LLM_MODEL,
            },
        )

        result = await agent.get_response(chat_request.messages, session.id, user_id=session.user_id)

        messages = result.get("messages", [])
        sources = result.get("sources", [])
        source_citations = [
            SourceCitation(
                chunk_id=s.get("chunk_id", 0),
                document_id=s.get("document_id", 0),
                filename=s.get("filename", ""),
                chunk_index=s.get("chunk_index", 0),
                score=s.get("score", 0.0),
                preview=s.get("preview", ""),
            )
            for s in sources
        ]

        if messages:
            update_current_trace(output={"assistant_message": messages[-1].content if messages else ""})

        logger.info("chat_request_processed", session_id=session.id)

        return ChatResponse(messages=messages, sources=source_citations)
    except Exception as e:
        logger.error("chat_request_failed", session_id=session.id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat_stream"][0])
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    session: Session = Depends(get_current_session),
):
    """Process a chat request using LangGraph with streaming response.

    Args:
        request: The FastAPI request object for rate limiting.
        chat_request: The chat request containing messages.
        session: The current session from the auth token.

    Returns:
        StreamingResponse: A streaming response of the chat completion.

    Raises:
        HTTPException: If there's an error processing the request.
    """
    try:
        logger.info(
            "stream_chat_request_received",
            session_id=session.id,
            message_count=len(chat_request.messages),
        )

        trace_context = capture_current_trace_context()
        update_current_trace(
            name="chatbot.chat.stream",
            user_id=str(session.user_id),
            session_id=session.id,
            input=_build_trace_input(chat_request),
            tags=["chatbot", "stream"],
            metadata={
                "environment": settings.ENVIRONMENT.value,
                "provider": settings.ACTIVE_LLM_PROVIDER.value,
                "model": settings.DEFAULT_LLM_MODEL,
            },
        )

        async def event_generator():
            """Generate streaming events.

            Yields:
                str: Server-sent events in JSON format.

            Raises:
                Exception: If there's an error during streaming.
            """
            try:
                full_response = ""
                with llm_stream_duration_seconds.labels(model=agent.llm_service.get_llm().get_name()).time():
                    async for chunk in agent.get_stream_response(
                        chat_request.messages, session.id, user_id=session.user_id
                    ):
                        passthrough_event = _format_passthrough_stream_event(chunk)
                        if passthrough_event is not None:
                            yield passthrough_event
                            continue

                        full_response += chunk
                        response = StreamResponse(content=chunk, done=False)
                        yield f"data: {json.dumps(response.model_dump())}\n\n"

                # Send final message indicating completion
                update_current_trace(output={"assistant_message": full_response})
                final_response = StreamResponse(content="", done=True)
                yield f"data: {json.dumps(final_response.model_dump())}\n\n"

            except Exception as e:
                logger.error(
                    "stream_chat_request_failed",
                    session_id=session.id,
                    error=str(e),
                    exc_info=True,
                )
                error_response = StreamResponse(content=str(e), done=True)
                yield f"data: {json.dumps(error_response.model_dump())}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except Exception as e:
        logger.error(
            "stream_chat_request_failed",
            session_id=session.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["messages"][0])
async def get_session_messages(
    request: Request,
    session: Session = Depends(get_current_session),
):
    """Get all messages for a session.

    Args:
        request: The FastAPI request object for rate limiting.
        session: The current session from the auth token.

    Returns:
        ChatResponse: All messages in the session.

    Raises:
        HTTPException: If there's an error retrieving the messages.
    """
    try:
        messages = await agent.get_chat_history(session.id)
        return ChatResponse(messages=messages)
    except Exception as e:
        logger.error("get_messages_failed", session_id=session.id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/messages")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["messages"][0])
async def clear_chat_history(
    request: Request,
    session: Session = Depends(get_current_session),
):
    """Clear all messages for a session.

    Args:
        request: The FastAPI request object for rate limiting.
        session: The current session from the auth token.

    Returns:
        dict: A message indicating the chat history was cleared.
    """
    try:
        await agent.clear_chat_history(session.id)
        return {"message": "Chat history cleared successfully"}
    except Exception as e:
        logger.error("clear_chat_history_failed", session_id=session.id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
