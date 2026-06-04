"""Document management API endpoints.

Provides upload, status-check, listing, deletion, and retrieval routes.
"""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Optional, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import desc
from sqlmodel import Session as DBSession, select, func

from src.config.settings import settings
from src.data.db_manager import db_manager
from src.data.models.document import Document, DocumentChunk
from src.data.schemas.document import (
    DocumentListResponse,
    DocumentSyncResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
    RetrievalRequest,
    RetrievalResponse,
)
from src.ingestion.pipeline import process_document
from src.retrieval.retriever import retriever
from src.services.storage import storage
from src.system.logs import logger
from src.utils.document_sync import (
    build_storage_object_name,
    plan_minio_document_sync,
)

router = APIRouter()

# ── Supported file types ─────────────────────────────────────────────
_ALLOWED_EXTENSIONS = {"pdf", "txt", "md", "docx"}
_MAX_FILE_SIZE = settings.MAX_UPLOAD_SIZE


def _get_file_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '.{ext}'. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )
    return ext


def _delete_documents_with_chunks(session: DBSession, docs: list[Document]) -> int:
    """Delete document rows together with their chunks from the database."""
    doc_ids = [doc.id for doc in docs if doc.id is not None]
    if not doc_ids:
        return 0

    chunks = session.exec(
        select(DocumentChunk).where(DocumentChunk.__table__.c.document_id.in_(doc_ids))
    ).all()
    for chunk in chunks:
        session.delete(chunk)

    for doc in docs:
        session.delete(doc)

    return len(doc_ids)


# ── Endpoints ────────────────────────────────────────────────────────


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
):
    """Upload a document for ingestion.

    The file is saved to a temporary location, uploaded to MinIO,
    then processed asynchronously via ``BackgroundTasks``.
    """
    # Validate
    original_filename = Path(file.filename or "document").name
    file_type = _get_file_type(original_filename)
    content = await file.read()
    file_size = len(content)

    if file_size > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({file_size} bytes). Max: {_MAX_FILE_SIZE} bytes",
        )

    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )

    # Check for duplicate by MD5 hash
    file_md5 = hashlib.md5(content).hexdigest()
    with DBSession(db_manager.engine) as session:
        existing = session.exec(
            select(Document).where(Document.__table__.c.md5_hash == file_md5)
        ).all()
        if existing:
            existing_doc = existing[0]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"文件已存在（与「{existing_doc.filename}」内容相同），请勿重复上传",
            )

    # Save to temp
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_type}")
    try:
        tmp.write(content)
        tmp.flush()
        tmp.close()

        # Upload to MinIO
        object_name = await storage.upload(tmp.name, object_name=build_storage_object_name(original_filename))

        # Create DB record
        with DBSession(db_manager.engine) as session:
            doc = Document(
                filename=original_filename,
                file_type=file_type,
                file_size=file_size,
                storage_path=object_name,
                md5_hash=file_md5,
                status="uploading",
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
            doc_id = doc.id

        # Schedule async processing
        background_tasks.add_task(process_document, doc_id)

        logger.info("document_uploaded", doc_id=doc_id, filename=original_filename, file_type=file_type, size=file_size)
        return DocumentUploadResponse(
            id=doc_id,
            filename=original_filename,
            file_type=file_type,
            file_size=file_size,
            status="uploading",
            message="Document uploaded and queued for processing",
        )
    except Exception as exc:
        logger.error("document_upload_failed", filename=original_filename, error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@router.post("/sync-minio", response_model=DocumentSyncResponse)
async def sync_minio_documents(background_tasks: BackgroundTasks):
    """Sync existing MinIO objects into the document library and queue ingestion."""
    try:
        stored_objects = await storage.list_objects(recursive=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("document_sync_storage_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    with DBSession(db_manager.engine) as session:
        existing_storage_paths = set(session.exec(select(Document.storage_path)).all())
        sync_plan = plan_minio_document_sync(stored_objects, existing_storage_paths, _ALLOWED_EXTENSIONS)

        removed_documents = 0
        if sync_plan.stale_storage_paths:
            stale_docs = session.exec(
                select(Document).where(Document.__table__.c.storage_path.in_(sync_plan.stale_storage_paths))
            ).all()
            removed_documents = _delete_documents_with_chunks(session, stale_docs)

        imported_docs: list[Document] = []
        for candidate in sync_plan.candidates:
            doc = Document(
                filename=candidate.filename,
                file_type=candidate.file_type,
                file_size=candidate.file_size,
                storage_path=candidate.object_name,
                status="uploading",
            )
            session.add(doc)
            imported_docs.append(doc)

        if imported_docs or removed_documents:
            session.commit()
            for doc in imported_docs:
                session.refresh(doc)
        else:
            session.rollback()

    queued_document_ids = [doc.id for doc in imported_docs if doc.id is not None]
    for doc_id in queued_document_ids:
        background_tasks.add_task(process_document, doc_id)

    logger.info(
        "document_sync_completed",
        scanned_objects=sync_plan.scanned_objects,
        imported_documents=len(queued_document_ids),
        removed_documents=removed_documents,
        skipped_existing=sync_plan.skipped_existing,
        skipped_unsupported=sync_plan.skipped_unsupported,
    )

    return DocumentSyncResponse(
        scanned_objects=sync_plan.scanned_objects,
        imported_documents=len(queued_document_ids),
        removed_documents=removed_documents,
        skipped_existing=sync_plan.skipped_existing,
        skipped_unsupported=sync_plan.skipped_unsupported,
        queued_document_ids=queued_document_ids,
        message=(
            "；".join(
                part
                for part in [
                    f"扫描 {sync_plan.scanned_objects} 个对象",
                    f"新增 {len(queued_document_ids)} 个文档",
                    f"移除 {removed_documents} 个失效文档" if removed_documents else "",
                ]
                if part
            )
            + "。"
        ),
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    """List all uploaded documents with pagination."""
    with DBSession(db_manager.engine) as session:
        base_query = select(Document)
        count_query = select(func.count(Document.id))

        if status_filter:
            base_query = base_query.where(Document.status == status_filter)
            count_query = count_query.where(Document.status == status_filter)

        total = cast(int, session.exec(count_query).one() or 0)
        docs = session.exec(
            base_query.order_by(desc(Document.__table__.c.created_at)).offset(skip).limit(limit)
        ).all()

    items = [
        DocumentStatusResponse(
            id=d.id,
            filename=d.filename,
            file_type=d.file_type,
            file_size=d.file_size,
            status=d.status,
            error_message=d.error_message,
            chunk_count=d.chunk_count,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in docs
    ]
    return DocumentListResponse(total=total, items=items)


@router.get("/documents/{doc_id}", response_model=DocumentStatusResponse)
async def get_document_status(doc_id: int):
    """Get the status of a specific document."""
    with DBSession(db_manager.engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return DocumentStatusResponse(
            id=doc.id,
            filename=doc.filename,
            file_type=doc.file_type,
            file_size=doc.file_size,
            status=doc.status,
            error_message=doc.error_message,
            chunk_count=doc.chunk_count,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: int):
    """Delete a document and its chunks (soft-delete the MinIO object)."""
    with DBSession(db_manager.engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        # Delete from MinIO (best-effort)
        try:
            await storage.delete(doc.storage_path)
        except Exception as exc:
            logger.warning("document_delete_storage_error", doc_id=doc_id, error=str(exc))

        # Delete chunks then document
        chunks = session.exec(select(DocumentChunk).where(DocumentChunk.document_id == doc_id)).all()
        for chunk in chunks:
            session.delete(chunk)
        session.delete(doc)
        session.commit()

        logger.info("document_deleted", doc_id=doc_id)
        return None


@router.post("/retrieve", response_model=RetrievalResponse)
async def retrieve_documents(payload: RetrievalRequest):
    """Semantic search over ingested document chunks."""
    results = await retriever.search(
        query=payload.query,
        top_k=payload.top_k,
        document_ids=payload.document_ids,
    )
    return RetrievalResponse(query=payload.query, results=results)
