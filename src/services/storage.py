"""MinIO / S3-compatible storage service.

Handles upload, download, and deletion of document files.
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

from minio import Minio
from minio.error import S3Error

from src.config.settings import settings
from src.system.logs import logger
from src.utils.document_sync import (
    StoredObjectRecord,
    build_storage_object_name,
)


class StorageService:
    """S3-compatible file storage backed by MinIO."""

    def __init__(self):
        self._client: Optional[Minio] = None
        self._bucket = settings.MINIO_BUCKET
        self._ready = False
        self._init_client()

    def _init_client(self):
        """Initialise the MinIO client and ensure the bucket exists."""
        endpoint = settings.MINIO_ENDPOINT
        access_key = settings.MINIO_ACCESS_KEY
        secret_key = settings.MINIO_SECRET_KEY
        secure = settings.MINIO_SECURE

        if not access_key or not secret_key:
            logger.warning("minio_not_configured", endpoint=endpoint)
            return

        try:
            self._client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
            )
            # Ensure bucket exists
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info("minio_bucket_created", bucket=self._bucket)
            else:
                logger.info("minio_bucket_exists", bucket=self._bucket)

            self._ready = True
            logger.info("minio_initialised", endpoint=endpoint, bucket=self._bucket)
        except S3Error as exc:
            logger.error("minio_init_failed", endpoint=endpoint, error=str(exc))
            self._client = None
        except Exception as exc:
            logger.error("minio_init_error", endpoint=endpoint, error=str(exc))
            self._client = None

    @property
    def ready(self) -> bool:
        """Whether the storage service is connected and ready."""
        return self._ready

    async def upload(self, file_path: str, object_name: Optional[str] = None) -> str:
        """Upload a local file to MinIO.

        Args:
            file_path: Local path to the file.
            object_name: MinIO object key (auto-generated if not given).

        Returns:
            The object key (storage path).
        """
        if not self._client:
            raise RuntimeError("MinIO client is not initialised")

        object_key = object_name or build_storage_object_name(Path(file_path).name)

        try:
            self._client.fput_object(
                self._bucket,
                object_key,
                file_path,
            )
            logger.info("file_uploaded", bucket=self._bucket, object_name=object_key)
            return object_key
        except S3Error as exc:
            logger.error("file_upload_failed", bucket=self._bucket, object_name=object_key, error=str(exc))
            raise

    async def list_objects(self, prefix: Optional[str] = None, recursive: bool = True) -> list[StoredObjectRecord]:
        """List objects in the configured bucket."""
        if not self._client:
            raise RuntimeError("MinIO client is not initialised")

        try:
            objects = [
                StoredObjectRecord(
                    object_name=obj.object_name,
                    size=max(int(getattr(obj, "size", 0) or 0), 0),
                    last_modified=getattr(obj, "last_modified", None),
                )
                for obj in self._client.list_objects(self._bucket, prefix=prefix, recursive=recursive)
            ]
            logger.info(
                "objects_listed",
                bucket=self._bucket,
                object_count=len(objects),
                prefix=prefix,
                recursive=recursive,
            )
            return objects
        except S3Error as exc:
            logger.error(
                "object_listing_failed",
                bucket=self._bucket,
                prefix=prefix,
                recursive=recursive,
                error=str(exc),
            )
            raise

    async def download(self, object_name: str) -> str:
        """Download a file from MinIO to a temporary local path.

        Args:
            object_name: MinIO object key.

        Returns:
            Local temporary file path.
        """
        if not self._client:
            raise RuntimeError("MinIO client is not initialised")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(object_name).suffix)
        tmp.close()  # Release handle so fget_object can write to it
        try:
            self._client.fget_object(self._bucket, object_name, tmp.name)
            logger.info("file_downloaded", bucket=self._bucket, object_name=object_name)
            return tmp.name
        except S3Error as exc:
            os.unlink(tmp.name)
            logger.error("file_download_failed", bucket=self._bucket, object_name=object_name, error=str(exc))
            raise

    async def delete(self, object_name: str) -> bool:
        """Delete an object from MinIO.

        Args:
            object_name: MinIO object key.

        Returns:
            True if successful.
        """
        if not self._client:
            raise RuntimeError("MinIO client is not initialised")

        try:
            self._client.remove_object(self._bucket, object_name)
            logger.info("file_deleted", bucket=self._bucket, object_name=object_name)
            return True
        except S3Error as exc:
            logger.error("file_delete_failed", bucket=self._bucket, object_name=object_name, error=str(exc))
            raise


# Singleton
storage = StorageService()
