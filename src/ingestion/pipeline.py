"""Document ingestion pipeline.

Orchestrates the full flow:
  1. Download file from MinIO to temp path
  2. Load text with the appropriate loader
  3. Split text into chunks
  4. Generate embeddings for each chunk
  5. Persist chunks + embeddings to PostgreSQL / pgvector
"""

import os
from datetime import UTC, datetime
from typing import cast

from sqlmodel import Session as DBSession, select

from src.data.db_manager import db_manager
from src.data.models.document import Document, DocumentChunk
from src.embedding.qwen_embedding import qwen_embedding
from src.ingestion.loaders import DocxLoader, PdfLoader, TxtLoader
from src.ingestion.loaders.base import BaseLoader
from src.ingestion.splitters import DocumentSplitter
from src.services.storage import storage
from src.system.logs import logger


# ── Loader registry ──────────────────────────────────────────────────
_LOADER_MAP: dict[str, type[BaseLoader]] = {
    "pdf": PdfLoader,
    "txt": TxtLoader,
    "md": TxtLoader,
    "docx": DocxLoader,
}


def _get_loader(file_type: str) -> BaseLoader:
    loader_cls = _LOADER_MAP.get(file_type)
    if not loader_cls:
        raise ValueError(f"Unsupported file type: {file_type!r}")
    return loader_cls()


# ── Public API ───────────────────────────────────────────────────────


async def process_document(doc_id: int) -> None:
    """Full ingestion pipeline for a single document.

    Called as a FastAPI ``BackgroundTask`` after upload.
    Updates the document status through ``uploading → processing → ready | failed``.

    Args:
        doc_id: Primary key of the ``Document`` row to process.
    """
    logger.info("pipeline_started", doc_id=doc_id)

    local_path = None
    with DBSession(db_manager.engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            logger.error("pipeline_document_not_found", doc_id=doc_id)
            return

        try:
            # ── Mark as processing ──
            doc.status = "processing"
            doc.updated_at = datetime.now(UTC)
            session.add(doc)
            session.commit()

            # ── 1. Download from MinIO ──
            local_path = await storage.download(doc.storage_path)
            logger.info("pipeline_downloaded", doc_id=doc_id, local_path=local_path)

            # ── Remove previous chunks so reprocessing stays idempotent ──
            existing_chunks = session.exec(
                select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
            ).all()
            for existing_chunk in existing_chunks:
                session.delete(existing_chunk)

            # ── 2. Load text ──
            loader = _get_loader(doc.file_type)
            text = await loader.load(local_path)

            # ── 3. Split ──
            splitter = DocumentSplitter()
            chunks = splitter.split(text)
            logger.info("pipeline_chunked", doc_id=doc_id, chunk_count=len(chunks))

            # ── 4. Embed ──
            if qwen_embedding.available:
                embeddings = await qwen_embedding.embed_documents(chunks)
            else:
                embeddings = [None] * len(chunks)
                logger.warning("pipeline_embedding_skipped", doc_id=doc_id)

            # ── 5. Persist ──
            for idx, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
                chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    content=chunk_text,
                    embedding=emb,
                )
                session.add(chunk)

            doc.status = "ready"
            doc.error_message = None
            doc.chunk_count = len(chunks)
            doc.updated_at = datetime.now(UTC)
            session.add(doc)
            session.commit()
            logger.info("pipeline_completed", doc_id=doc_id, chunks=len(chunks))

        except Exception as exc:
            doc.status = "failed"
            doc.error_message = str(exc)[:2048]
            doc.updated_at = datetime.now(UTC)
            session.add(doc)
            session.commit()
            logger.error("pipeline_failed", doc_id=doc_id, error=str(exc))
        finally:
            # Clean up temp file
            if local_path is not None:
                try:
                    os.unlink(cast(str, local_path))
                except OSError:
                    pass
