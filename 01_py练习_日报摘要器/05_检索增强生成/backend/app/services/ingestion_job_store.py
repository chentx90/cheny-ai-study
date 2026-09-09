import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
import asyncpg


class IngestionJobStore:
    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool

    async def create_job(
        self,
        source_type: str,
        title: Optional[str] = None,
        business_domain: Optional[str] = None,
        doc_type: Optional[str] = None,
        version: Optional[str] = None,
        mode: str = "preview",
        options: Optional[dict] = None,
        upload_id: Optional[str] = None,
    ) -> dict:
        job_id = str(uuid.uuid4())
        now = datetime.utcnow()
        row = await self.db_pool.fetchrow(
            """
            INSERT INTO ingestion_jobs (id, upload_id, source_type, title, business_domain, doc_type, version, mode, status, stage, progress, options, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', NULL, 0, $9, $10)
            RETURNING *
            """,
            job_id,
            upload_id,
            source_type,
            title,
            business_domain,
            doc_type,
            version,
            mode,
            json.dumps(options) if options else None,
            now,
        )
        return dict(row)

    async def get_job(self, job_id: str) -> Optional[dict]:
        row = await self.db_pool.fetchrow("SELECT * FROM ingestion_jobs WHERE id = $1", job_id)
        return dict(row) if row else None

    async def list_jobs(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        if status:
            rows = await self.db_pool.fetch(
                "SELECT * FROM ingestion_jobs WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
                status,
                limit,
            )
        else:
            rows = await self.db_pool.fetch(
                "SELECT * FROM ingestion_jobs ORDER BY created_at DESC LIMIT $1", limit
            )
        return [dict(r) for r in rows]

    async def update_status(
        self,
        job_id: str,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        progress: Optional[int] = None,
        error_count: Optional[int] = None,
        preview_uri: Optional[str] = None,
        result: Optional[dict] = None,
    ) -> Optional[dict]:
        sets = []
        values = []
        idx = 1
        if status is not None:
            sets.append(f"status = ${idx}")
            values.append(status)
            idx += 1
        if stage is not None:
            sets.append(f"stage = ${idx}")
            values.append(stage)
            idx += 1
        if progress is not None:
            sets.append(f"progress = ${idx}")
            values.append(progress)
            idx += 1
        if error_count is not None:
            sets.append(f"error_count = ${idx}")
            values.append(error_count)
            idx += 1
        if preview_uri is not None:
            sets.append(f"preview_uri = ${idx}")
            values.append(preview_uri)
            idx += 1
        if result is not None:
            sets.append(f"result = ${idx}")
            values.append(json.dumps(result, ensure_ascii=False))
            idx += 1

        if status in ("completed", "failed", "cancelled"):
            sets.append(f"finished_at = ${idx}")
            values.append(datetime.utcnow())
            idx += 1
        if status in ("parsing", "chunking", "embedding", "writing") and not await self.get_job(job_id):
            pass
        elif status not in ("completed", "failed", "cancelled"):
            sets.append(f"started_at = COALESCE(started_at, ${idx})")
            values.append(datetime.utcnow())
            idx += 1

        if not sets:
            return await self.get_job(job_id)

        values.append(job_id)
        sql = f"UPDATE ingestion_jobs SET {', '.join(sets)} WHERE id = ${idx} RETURNING *"
        row = await self.db_pool.fetchrow(sql, *values)
        return dict(row) if row else None

    async def add_error(
        self,
        job_id: str,
        stage: str,
        message: str,
        object_ref: Optional[str] = None,
        suggestion: Optional[str] = None,
        raw_error: Optional[str] = None,
    ) -> dict:
        error_id = str(uuid.uuid4())
        row = await self.db_pool.fetchrow(
            """
            INSERT INTO ingestion_job_errors (id, job_id, stage, object_ref, message, suggestion, raw_error, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            RETURNING *
            """,
            error_id,
            job_id,
            stage,
            object_ref,
            message,
            suggestion,
            raw_error,
        )
        await self.update_status(
            job_id,
            error_count=(await self.get_job(job_id))["error_count"] + 1,
        )
        return dict(row)

    async def get_errors(self, job_id: str) -> list[dict]:
        rows = await self.db_pool.fetch(
            "SELECT * FROM ingestion_job_errors WHERE job_id = $1 ORDER BY created_at ASC",
            job_id,
        )
        return [dict(r) for r in rows]

    async def delete_job(self, job_id: str) -> bool:
        preview_uri = None
        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                job = await conn.fetchrow("SELECT preview_uri FROM ingestion_jobs WHERE id = $1", job_id)
                if not job:
                    return False
                preview_uri = job["preview_uri"]
                approved = await conn.fetchrow(
                    """
                    SELECT id, kb_document_id
                    FROM parsed_documents
                    WHERE parse_job_id = $1
                      AND (status = 'approved' OR kb_document_id IS NOT NULL)
                    LIMIT 1
                    """,
                    job_id,
                )
                if approved:
                    raise ValueError("Approved parsed document cannot be deleted from ingestion jobs. Archive the knowledge document first.")
                await conn.execute(
                    """
                    DELETE FROM embedding_jobs
                    WHERE parsed_document_id IN (SELECT id FROM parsed_documents WHERE parse_job_id = $1)
                    """,
                    job_id,
                )
                await conn.execute("DELETE FROM parsed_documents WHERE parse_job_id = $1", job_id)
                await conn.execute("DELETE FROM ingestion_job_errors WHERE job_id = $1", job_id)
                result = await conn.execute("DELETE FROM ingestion_jobs WHERE id = $1", job_id)
        if preview_uri:
            try:
                Path(preview_uri).unlink(missing_ok=True)
            except OSError:
                pass
        return result == "DELETE 1"
