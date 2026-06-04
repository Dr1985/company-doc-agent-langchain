"""Helpers for storage object naming and MinIO-to-document-library sync planning."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath, PurePosixPath
from typing import Iterable, Optional
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class StoredObjectRecord:
    """Minimal metadata for an object stored in MinIO/S3."""

    object_name: str
    size: int = 0
    last_modified: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class DocumentSyncCandidate:
    """A MinIO object that should be imported into the document library."""

    object_name: str
    filename: str
    file_type: str
    file_size: int


@dataclass(frozen=True, slots=True)
class DocumentSyncPlan:
    """Computed import plan for a MinIO sync run."""

    scanned_objects: int
    skipped_existing: int
    skipped_unsupported: int
    stale_storage_paths: tuple[str, ...]
    candidates: tuple[DocumentSyncCandidate, ...]


def build_storage_object_name(filename: str, prefix: str | None = None) -> str:
    """Build a stable object key that preserves the original filename."""
    safe_filename = PurePath(filename).name.strip() or "document"
    safe_prefix = (prefix or uuid4().hex).strip("/\\") or uuid4().hex
    return f"{safe_prefix}/{safe_filename}"


def plan_minio_document_sync(
    stored_objects: Iterable[StoredObjectRecord],
    existing_storage_paths: set[str],
    allowed_extensions: set[str],
) -> DocumentSyncPlan:
    """Classify MinIO objects into sync candidates and skips."""
    candidates: list[DocumentSyncCandidate] = []
    current_object_names: set[str] = set()
    skipped_existing = 0
    skipped_unsupported = 0
    scanned_objects = 0

    for stored_object in stored_objects:
        scanned_objects += 1
        object_name = stored_object.object_name
        current_object_names.add(object_name)

        if object_name in existing_storage_paths:
            skipped_existing += 1
            continue

        filename = PurePosixPath(object_name).name.strip()
        if not filename or "." not in filename:
            skipped_unsupported += 1
            continue

        file_type = filename.rsplit(".", 1)[-1].lower()
        if file_type not in allowed_extensions:
            skipped_unsupported += 1
            continue

        candidates.append(
            DocumentSyncCandidate(
                object_name=object_name,
                filename=filename,
                file_type=file_type,
                file_size=max(int(stored_object.size or 0), 0),
            )
        )

    return DocumentSyncPlan(
        scanned_objects=scanned_objects,
        skipped_existing=skipped_existing,
        skipped_unsupported=skipped_unsupported,
        stale_storage_paths=tuple(sorted(existing_storage_paths - current_object_names)),
        candidates=tuple(candidates),
    )

