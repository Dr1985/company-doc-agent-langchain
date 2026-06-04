"""Document and chunk models for RAG ingestion pipeline.

This module defines the SQLModel ORM models for storing uploaded documents
and their vectorized chunks, with pgvector support for similarity search.
"""

from datetime import datetime, UTC
from typing import (
    TYPE_CHECKING,
    Any,
    List,
    Optional,
)

from sqlalchemy import Column
from sqlmodel import (
    Field,
    Relationship,
    SQLModel,
)

from pgvector.sqlalchemy import Vector

if TYPE_CHECKING:
    pass


class Document(SQLModel, table=True):
    """Uploaded document metadata.

    Stores original file info and processing status. The actual file
    content lives in MinIO at ``storage_path``.
    """

    __tablename__ = "documents"

    id: int = Field(default=None, primary_key=True)
    filename: str = Field(max_length=512, index=True)
    file_type: str = Field(max_length=32)  # pdf / txt / docx / md
    file_size: int = Field(default=0)  # bytes
    storage_path: str = Field(max_length=1024)  # MinIO object key
    md5_hash: Optional[str] = Field(default=None, max_length=64, index=True)  # MD5 for dedup
    status: str = Field(
        default="uploading", max_length=32, index=True
    )  # uploading → processing → ready | failed
    error_message: Optional[str] = Field(default=None, max_length=2048)
    chunk_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    chunks: List["DocumentChunk"] = Relationship(back_populates="document")


class DocumentChunk(SQLModel, table=True):
    """A single chunk of a document with its vector embedding.

    The ``embedding`` column uses pgvector's ``vector(1024)`` type
    (matching Qwen text-embedding-v4 output dimensionality).
    """

    __tablename__ = "document_chunks"

    id: int = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="documents.id", index=True)
    chunk_index: int = Field(default=0)
    content: str = Field(default="")
    embedding: Any = Field(
        default=None,
        sa_column=Column(Vector(1024), nullable=True),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    document: Document = Relationship(back_populates="chunks")
