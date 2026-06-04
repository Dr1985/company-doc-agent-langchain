"""This file contains the graph schema for the application."""

from typing import Annotated, Any, Dict, List, Optional

from langgraph.graph.message import add_messages
from pydantic import (
    BaseModel,
    Field,
)


class GraphState(BaseModel):
    """State definition for the LangGraph Agent/Workflow."""

    messages: Annotated[list, add_messages] = Field(
        default_factory=list, description="The messages in the conversation"
    )
    long_term_memory: str = Field(default="", description="The long term memory of the conversation")
    retrieved_context: str = Field(default="", description="Formatted RAG context for the LLM")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Citation sources for RAG responses")
    document_ids: Optional[List[int]] = Field(default=None, description="Optional document IDs to restrict retrieval scope")
