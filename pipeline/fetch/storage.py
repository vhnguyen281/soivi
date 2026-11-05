"""Where raw snapshot bytes live.

Key layout: {institution}/{source_kind}/{YYYY-MM-DD}/{sha256}.{ext}
(date in UTC). The bucket has object versioning on, so nothing is ever lost.
"""

import datetime as dt
import io
from typing import Protocol

from core.config import Settings, get_settings

EXTENSIONS = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/pdf": "pdf",
    "application/json": "json",
    "text/plain": "txt",
    "text/csv": "csv",
    "image/png": "png",
    "image/jpeg": "jpg",
}


def extension_for(content_type: str | None) -> str:
    return EXTENSIONS.get((content_type or "").lower(), "bin")


def snapshot_key(
    institution: str,
    source_kind: str,
    fetched_at: dt.datetime,
    sha256: str,
    content_type: str | None,
) -> str:
    day = fetched_at.astimezone(dt.UTC).date().isoformat()
    return f"{institution}/{source_kind}/{day}/{sha256}.{extension_for(content_type)}"


class SnapshotStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str | None) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class MemoryStore:
    """In-memory store for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}
        self.puts = 0

    def put(self, key: str, data: bytes, content_type: str | None) -> None:
        self.objects[key] = (data, content_type)
        self.puts += 1

    def get(self, key: str) -> bytes:
        return self.objects[key][0]

    def exists(self, key: str) -> bool:
        return key in self.objects


class MinioStore:
    def __init__(self, settings: Settings | None = None) -> None:
        from minio import Minio

        s = settings or get_settings()
        self.bucket = s.s3_bucket
        self.client = Minio(
            s.s3_endpoint,
            access_key=s.s3_access_key,
            secret_key=s.s3_secret_key,
            secure=s.s3_secure,
        )

    def put(self, key: str, data: bytes, content_type: str | None) -> None:
        self.client.put_object(
            self.bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )

    def get(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self.client.stat_object(self.bucket, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return False
            raise
        return True
