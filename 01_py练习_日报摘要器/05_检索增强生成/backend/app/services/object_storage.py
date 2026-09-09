"""Object storage abstraction for raw source files."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from ..config import settings


class ObjectStorageService:
    def __init__(self):
        self.endpoint = settings.minio_endpoint
        self.access_key = settings.minio_access_key
        self.secret_key = settings.minio_secret_key
        self.secure = settings.minio_secure
        self.default_bucket = settings.minio_bucket
        self.local_root = settings.local_object_storage_path
        self._client = None
        self._minio_disabled = False

    @property
    def mode(self) -> str:
        return "minio" if self.endpoint and self._minio_client() else "local"

    def ensure_bucket(self, bucket: str | None = None) -> str:
        bucket = bucket or self.default_bucket
        client = self._minio_client()
        if client:
            try:
                if not client.bucket_exists(bucket):
                    client.make_bucket(bucket)
                return bucket
            except Exception as exc:
                self._disable_minio(exc)
        (self.local_root / bucket).mkdir(parents=True, exist_ok=True)
        return bucket

    def put_bytes(self, data: bytes, object_key: str, bucket: str | None = None, content_type: str = "application/octet-stream") -> dict:
        bucket = self.ensure_bucket(bucket)
        client = self._minio_client()
        if client:
            from io import BytesIO
            try:
                client.put_object(bucket, object_key, BytesIO(data), length=len(data), content_type=content_type)
                return {"bucket": bucket, "object_key": object_key, "storage_backend": "minio"}
            except Exception as exc:
                self._disable_minio(exc)
        path = self.local_root / bucket / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"bucket": bucket, "object_key": object_key, "storage_backend": self.mode}

    def put_file(self, source_path: str | Path, object_key: str, bucket: str | None = None, content_type: str = "application/octet-stream") -> dict:
        bucket = self.ensure_bucket(bucket)
        source = Path(source_path)
        client = self._minio_client()
        if client:
            try:
                client.fput_object(bucket, object_key, str(source), content_type=content_type)
                return {"bucket": bucket, "object_key": object_key, "storage_backend": "minio"}
            except Exception as exc:
                self._disable_minio(exc)
        target = self.local_root / bucket / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return {"bucket": bucket, "object_key": object_key, "storage_backend": self.mode}

    def get_to_file(self, bucket: str, object_key: str, target_path: str | Path) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        client = self._minio_client()
        if client:
            try:
                client.fget_object(bucket, object_key, str(target))
                return target
            except Exception as exc:
                self._disable_minio(exc)
        source = self.local_root / bucket / object_key
        shutil.copy2(source, target)
        return target

    def delete_object(self, bucket: str, object_key: str) -> None:
        client = self._minio_client()
        if client:
            try:
                client.remove_object(bucket, object_key)
                return
            except Exception as exc:
                self._disable_minio(exc)
        path = self.local_root / bucket / object_key
        if path.exists():
            path.unlink()

    def open(self, bucket: str, object_key: str) -> BinaryIO:
        if self._minio_client():
            raise NotImplementedError("Use get_to_file for MinIO-backed objects")
        return (self.local_root / bucket / object_key).open("rb")

    def _minio_client(self):
        if not self.endpoint or self._minio_disabled:
            return None
        if self._client is not None:
            return self._client
        try:
            from minio import Minio
            self._client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        except Exception:
            self._client = None
        return self._client

    def _disable_minio(self, exc: Exception) -> None:
        print(f"[WARN] MinIO unavailable, falling back to local object storage: {exc}")
        self._client = None
        self._minio_disabled = True
