"""Pydantic schemas for document ingestion API."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    """Response returned after a document is uploaded."""

    id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    message: str = ""


class DocumentStatusResponse(BaseModel):
    """Status of a single document."""

    id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    error_message: Optional[str] = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    total: int
    items: List[DocumentStatusResponse]


class DocumentSyncResponse(BaseModel):
    """Summary of a MinIO sync run."""

    scanned_objects: int
    imported_documents: int
    removed_documents: int = 0
    skipped_existing: int
    skipped_unsupported: int
    queued_document_ids: List[int] = Field(default_factory=list)
    message: str = ""


class ChunkResult(BaseModel):
    """A single retrieved chunk for RAG."""

    chunk_id: int
    document_id: int
    filename: str
    chunk_index: int
    content: str
    score: float = Field(ge=0.0, le=1.0)


class RetrievalRequest(BaseModel):
    """Query payload for document retrieval."""

    query: str = Field(..., min_length=1, max_length=2048)
    top_k: int = Field(default=5, ge=1, le=50)
    document_ids: Optional[List[int]] = Field(
        default=None, description="Filter by document IDs"
    )


class RetrievalResponse(BaseModel):
    """Search results from the vector store."""

    query: str
    results: List[ChunkResult]
