import os
import uuid
import aiofiles
from pathlib import Path
from typing import Optional
import asyncpg
from .file_asset_service import FileAssetService

UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


class UploadService:
    def __init__(self, db_pool: asyncpg.Pool, file_asset_service: FileAssetService = None):
        self.db_pool = db_pool
        self.file_asset_service = file_asset_service

    async def save_upload(self, file_name: str, file_bytes: bytes, content_type: str, business_domain: str = "general", relative_path: str = None) -> dict:
        upload_id = str(uuid.uuid4())
        ext = Path(file_name).suffix
        storage_uri = f"uploads/{upload_id}{ext}"
        disk_path = UPLOAD_DIR / f"{upload_id}{ext}"

        async with aiofiles.open(disk_path, "wb") as f:
            await f.write(file_bytes)

        file_asset = None
        if self.file_asset_service:
            file_asset = await self.file_asset_service.create_from_bytes(
                file_name=file_name,
                file_bytes=file_bytes,
                content_type=content_type,
                business_domain=business_domain,
                relative_path=relative_path or file_name,
            )

        file_type = content_type.split("/")[-1] if "/" in content_type else ext.lstrip(".")
        row = await self.db_pool.fetchrow(
            """
            INSERT INTO ingestion_uploads (id, file_asset_id, file_name, file_type, file_size, storage_uri, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'uploaded')
            RETURNING id AS upload_id, file_asset_id, file_name, file_type, file_size, storage_uri, created_at
            """,
            upload_id,
            file_asset.get("id") if file_asset else None,
            file_name,
            file_type,
            len(file_bytes),
            storage_uri,
        )
        result = dict(row)
        if file_asset:
            result["file_asset"] = file_asset
        return result

    async def ensure_upload_for_asset(self, file_asset: dict) -> dict:
        existing = await self.db_pool.fetchrow(
            "SELECT *, id AS upload_id FROM ingestion_uploads WHERE file_asset_id = $1 ORDER BY created_at DESC LIMIT 1",
            file_asset["id"],
        )
        if existing:
            return dict(existing)

        upload_id = str(uuid.uuid4())
        file_name = file_asset.get("original_filename") or file_asset["id"]
        ext = Path(file_name).suffix.lstrip(".")
        mime_type = file_asset.get("mime_type") or "application/octet-stream"
        file_type = mime_type.split("/")[-1] if "/" in mime_type else ext
        storage_uri = f"file-assets/{file_asset['id']}/{file_name}"
        row = await self.db_pool.fetchrow(
            """
            INSERT INTO ingestion_uploads (id, file_asset_id, file_name, file_type, file_size, storage_uri, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'uploaded')
            RETURNING id AS upload_id, file_asset_id, file_name, file_type, file_size, storage_uri, created_at
            """,
            upload_id,
            file_asset["id"],
            file_name,
            file_type or ext,
            file_asset.get("file_size") or 0,
            storage_uri,
        )
        result = dict(row)
        result["file_asset"] = file_asset
        return result

    async def get_upload(self, upload_id: str) -> Optional[dict]:
        row = await self.db_pool.fetchrow(
            "SELECT *, id AS upload_id FROM ingestion_uploads WHERE id = $1", upload_id
        )
        return dict(row) if row else None

    async def list_uploads(self, limit: int = 50) -> list[dict]:
        rows = await self.db_pool.fetch(
            "SELECT *, id AS upload_id FROM ingestion_uploads ORDER BY created_at DESC LIMIT $1", limit
        )
        return [dict(r) for r in rows]
