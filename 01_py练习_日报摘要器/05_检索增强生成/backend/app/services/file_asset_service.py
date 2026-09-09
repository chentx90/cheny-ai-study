"""Raw file asset management backed by object storage."""
from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import asyncpg

from .object_storage import ObjectStorageService


class FileAssetService:
    def __init__(self, db_pool: asyncpg.Pool, storage: ObjectStorageService):
        self.db_pool = db_pool
        self.storage = storage

    async def create_from_bytes(
        self,
        file_name: str,
        file_bytes: bytes,
        content_type: str = "application/octet-stream",
        business_domain: str = "general",
        relative_path: str | None = None,
        source_batch_id: str | None = None,
    ) -> dict:
        file_asset_id = str(uuid.uuid4())
        ext = Path(file_name).suffix.lstrip(".").lower()
        content_hash = hashlib.sha256(file_bytes).hexdigest()
        now = datetime.utcnow()
        rel_path = _normalize_relative_path(relative_path or file_name)
        object_key = _object_key(business_domain, now, file_asset_id, rel_path)
        stored = self.storage.put_bytes(file_bytes, object_key, content_type=content_type)
        return await self._insert_asset(
            file_asset_id=file_asset_id,
            original_filename=file_name,
            relative_path=rel_path,
            file_ext=ext,
            mime_type=content_type,
            file_size=len(file_bytes),
            content_hash=content_hash,
            business_domain=business_domain,
            bucket=stored["bucket"],
            object_key=stored["object_key"],
            storage_backend=stored["storage_backend"],
            source_batch_id=source_batch_id,
        )

    async def import_folder(
        self,
        root_path: str,
        business_domain: str = "general",
        batch_name: str | None = None,
    ) -> dict:
        root = Path(root_path)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Import folder not found: {root}")
        batch_id = str(uuid.uuid4())
        files = [p for p in root.rglob("*") if p.is_file()]
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO import_batches (id, name, root_path, business_domain, total_files, status, created_at)
                VALUES ($1, $2, $3, $4, $5, 'importing', NOW())
                """,
                batch_id,
                batch_name or root.name,
                str(root),
                business_domain,
                len(files),
            )

        imported, failed = [], []
        for path in files:
            try:
                rel = path.relative_to(root).as_posix()
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                asset = await self.create_from_bytes(
                    file_name=path.name,
                    file_bytes=path.read_bytes(),
                    content_type=content_type,
                    business_domain=business_domain,
                    relative_path=rel,
                    source_batch_id=batch_id,
                )
                imported.append(asset)
            except Exception as exc:
                failed.append({"path": str(path), "error": str(exc)})

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE import_batches SET status=$2, imported_files=$3, failed_files=$4, finished_at=NOW() WHERE id=$1",
                batch_id,
                "completed" if not failed else "completed_with_errors",
                len(imported),
                len(failed),
            )
        return {"batch_id": batch_id, "imported": imported, "failed": failed}

    async def get_asset(self, file_asset_id: str) -> Optional[dict]:
        row = await self.db_pool.fetchrow("SELECT * FROM file_assets WHERE id=$1", file_asset_id)
        return dict(row) if row else None

    async def list_assets(self, limit: int = 50, business_domain: str | None = None) -> list[dict]:
        if business_domain:
            rows = await self.db_pool.fetch(
                "SELECT * FROM file_assets WHERE business_domain=$1 ORDER BY created_at DESC LIMIT $2",
                business_domain,
                limit,
            )
        else:
            rows = await self.db_pool.fetch("SELECT * FROM file_assets ORDER BY created_at DESC LIMIT $1", limit)
        return [dict(row) for row in rows]

    async def materialize_to_temp(self, file_asset: dict, target_dir: str | Path) -> Path:
        suffix = Path(file_asset.get("original_filename") or "").suffix
        target = Path(target_dir) / f"{file_asset['id']}{suffix}"
        return self.storage.get_to_file(file_asset["bucket"], file_asset["object_key"], target)

    async def delete_asset(self, file_asset_id: str) -> bool:
        file_asset = await self.get_asset(file_asset_id)
        if not file_asset:
            return False
        active_doc = await self.db_pool.fetchrow(
            "SELECT id, title FROM kb_documents WHERE file_asset_id=$1 AND status='active' LIMIT 1",
            file_asset_id,
        )
        if active_doc:
            raise ValueError(f"File asset is already used by active document: {active_doc['title']} ({active_doc['id']})")

        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                job_rows = await conn.fetch(
                    """
                    SELECT j.id, j.preview_uri
                    FROM ingestion_jobs j
                    JOIN ingestion_uploads u ON u.id = j.upload_id
                    WHERE u.file_asset_id = $1
                    """,
                    file_asset_id,
                )
                await conn.execute(
                    "DELETE FROM embedding_jobs WHERE parsed_document_id IN (SELECT id FROM parsed_documents WHERE file_asset_id=$1)",
                    file_asset_id,
                )
                await conn.execute("DELETE FROM parsed_documents WHERE file_asset_id=$1", file_asset_id)
                await conn.execute(
                    """
                    DELETE FROM ingestion_job_errors
                    WHERE job_id IN (
                        SELECT j.id FROM ingestion_jobs j
                        JOIN ingestion_uploads u ON u.id = j.upload_id
                        WHERE u.file_asset_id = $1
                    )
                    """,
                    file_asset_id,
                )
                await conn.execute(
                    """
                    DELETE FROM ingestion_jobs
                    WHERE upload_id IN (SELECT id FROM ingestion_uploads WHERE file_asset_id=$1)
                    """,
                    file_asset_id,
                )
                await conn.execute("DELETE FROM ingestion_uploads WHERE file_asset_id=$1", file_asset_id)
                result = await conn.execute("DELETE FROM file_assets WHERE id=$1", file_asset_id)

        for row in job_rows:
            preview_uri = row["preview_uri"]
            if preview_uri:
                try:
                    Path(preview_uri).unlink(missing_ok=True)
                except OSError:
                    pass
        self.storage.delete_object(file_asset["bucket"], file_asset["object_key"])
        return result == "DELETE 1"

    async def _insert_asset(self, **asset) -> dict:
        row = await self.db_pool.fetchrow(
            """
            INSERT INTO file_assets
              (id, original_filename, relative_path, bucket, object_key, storage_backend,
               file_ext, mime_type, file_size, content_hash, business_domain, source_batch_id, status, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'uploaded',NOW())
            RETURNING *
            """,
            asset["file_asset_id"],
            asset["original_filename"],
            asset["relative_path"],
            asset["bucket"],
            asset["object_key"],
            asset["storage_backend"],
            asset["file_ext"],
            asset["mime_type"],
            asset["file_size"],
            asset["content_hash"],
            asset["business_domain"],
            asset["source_batch_id"],
        )
        return dict(row)


def _normalize_relative_path(path: str) -> str:
    return Path(path).as_posix().lstrip("/")


def _object_key(business_domain: str, now: datetime, file_asset_id: str, relative_path: str) -> str:
    safe_domain = business_domain or "general"
    return f"raw/{safe_domain}/{now:%Y/%m}/{file_asset_id}/{relative_path}"
