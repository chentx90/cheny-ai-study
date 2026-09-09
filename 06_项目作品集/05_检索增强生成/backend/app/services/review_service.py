"""Review and approval workflow for parsed documents and chunk drafts."""
from __future__ import annotations

import json
import uuid
from typing import Optional

import asyncpg

from .commit_service import archive_doc, find_active_doc_by_hash, next_available_title
from .db_writer import write_data_asset, write_document_with_chunks


class ReviewService:
    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool

    async def save_parsed_draft(self, parsed: dict, job: dict, upload: dict | None = None) -> dict:
        document = parsed.get("document") or {}
        parsed_document_id = str(uuid.uuid4())
        file_asset_id = (upload or {}).get("file_asset_id")
        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO parsed_documents
                      (id, file_asset_id, parse_job_id, title, doc_type, business_domain,
                       content_hash, markdown_text, stats, status, created_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'draft',NOW())
                    """,
                    parsed_document_id,
                    file_asset_id,
                    job.get("id"),
                    document.get("title") or job.get("title") or "Untitled",
                    document.get("doc_type") or job.get("doc_type") or "document",
                    document.get("business_domain") or job.get("business_domain") or "general",
                    document.get("content_hash"),
                    "\n\n".join(page.get("text", "") for page in parsed.get("pages", [])),
                    json.dumps(parsed.get("stats") or {}, ensure_ascii=False),
                )
                for idx, chunk in enumerate(parsed.get("chunks", [])):
                    await conn.execute(
                        """
                        INSERT INTO chunk_drafts
                          (id, parsed_document_id, chunk_index, section_path, title_context,
                           content, summary, preset_questions, physical_context, status, created_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'draft',NOW())
                        """,
                        str(uuid.uuid4()),
                        parsed_document_id,
                        idx,
                        chunk.get("section_path", ""),
                        chunk.get("title_context", ""),
                        chunk.get("content", ""),
                        chunk.get("summary", ""),
                        json.dumps(chunk.get("preset_questions") or [], ensure_ascii=False),
                        json.dumps(chunk.get("physical_context"), ensure_ascii=False) if chunk.get("physical_context") else None,
                    )
        return await self.get_review(parsed_document_id)

    async def get_review(self, parsed_document_id: str) -> Optional[dict]:
        doc = await self.db_pool.fetchrow("SELECT * FROM parsed_documents WHERE id=$1", parsed_document_id)
        if not doc:
            return None
        chunks = await self.db_pool.fetch(
            "SELECT * FROM chunk_drafts WHERE parsed_document_id=$1 ORDER BY chunk_index",
            parsed_document_id,
        )
        result = dict(doc)
        result["chunks"] = [dict(row) for row in chunks]
        return result

    async def approve(self, parsed_document_id: str, on_duplicate: str = "block") -> dict:
        review = await self.get_review(parsed_document_id)
        if not review:
            raise ValueError(f"Parsed document not found: {parsed_document_id}")
        if review["status"] not in ("draft", "rejected"):
            raise ValueError(f"Parsed document is not approvable: {review['status']}")

        domain = review.get("business_domain") or "general"
        content_hash = review.get("content_hash")
        if content_hash and on_duplicate == "block":
            existing = await find_active_doc_by_hash(self.db_pool, content_hash, domain)
            if existing:
                raise ValueError(f"Document already exists: {existing['title']} ({existing['id']})")

        embedding_job_id = str(uuid.uuid4())
        await self.db_pool.execute(
            """
            INSERT INTO embedding_jobs (id, parsed_document_id, status, stage, progress, created_at)
            VALUES ($1,$2,'embedding','embedding',0,NOW())
            """,
            embedding_job_id,
            parsed_document_id,
        )

        try:
            if content_hash and on_duplicate == "replace":
                existing = await find_active_doc_by_hash(self.db_pool, content_hash, domain)
                if existing:
                    await archive_doc(self.db_pool, existing["id"])

            title = await next_available_title(self.db_pool, review["title"], domain)
            chunks = [
                {
                    "section_path": c.get("section_path"),
                    "title_context": c.get("title_context"),
                    "content": c.get("content"),
                    "summary": c.get("summary"),
                    "preset_questions": _json_value(c.get("preset_questions"), []),
                    "physical_context": _json_value(c.get("physical_context"), None),
                }
                for c in review["chunks"]
                if c.get("status") in ("draft", "approved")
            ]
            doc = {
                "title": title,
                "doc_type": review.get("doc_type") or "document",
                "source_uri": await self._source_uri(review.get("file_asset_id")),
                "business_domain": domain,
                "version": "1.0",
                "content_hash": content_hash,
                "status": "active",
                "file_asset_id": review.get("file_asset_id"),
                "parsed_document_id": parsed_document_id,
            }
            document_id = await write_document_with_chunks(self.db_pool, doc, chunks)
            await self.db_pool.execute(
                "UPDATE parsed_documents SET status='approved', approved_at=NOW(), kb_document_id=$2 WHERE id=$1",
                parsed_document_id,
                document_id,
            )
            await self.db_pool.execute(
                "UPDATE chunk_drafts SET status='approved' WHERE parsed_document_id=$1 AND status='draft'",
                parsed_document_id,
            )
            await self.db_pool.execute(
                "UPDATE embedding_jobs SET status='completed', stage='completed', progress=100, result=$2, finished_at=NOW() WHERE id=$1",
                embedding_job_id,
                json.dumps({"document_id": document_id, "chunks": len(chunks)}, ensure_ascii=False),
            )
            return {"embedding_job_id": embedding_job_id, "document_id": document_id, "chunks": len(chunks)}
        except Exception as exc:
            await self.db_pool.execute(
                "UPDATE embedding_jobs SET status='failed', stage='error', error_message=$2, finished_at=NOW() WHERE id=$1",
                embedding_job_id,
                str(exc),
            )
            raise

    async def reject(self, parsed_document_id: str, reason: str = "") -> dict:
        row = await self.db_pool.fetchrow(
            "UPDATE parsed_documents SET status='rejected', review_notes=$2 WHERE id=$1 RETURNING *",
            parsed_document_id,
            reason,
        )
        if not row:
            raise ValueError(f"Parsed document not found: {parsed_document_id}")
        review = await self.get_review(parsed_document_id)
        return review or dict(row)

    async def delete_draft(self, parsed_document_id: str) -> bool:
        review = await self.get_review(parsed_document_id)
        if not review:
            return False
        if review.get("status") == "approved" or review.get("kb_document_id"):
            raise ValueError("Approved parsed document cannot be deleted here. Archive it from the knowledge page first.")
        parse_job_id = review.get("parse_job_id")
        preview_uri = None
        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                if parse_job_id:
                    job = await conn.fetchrow("SELECT preview_uri FROM ingestion_jobs WHERE id=$1", parse_job_id)
                    preview_uri = job["preview_uri"] if job else None
                await conn.execute("DELETE FROM embedding_jobs WHERE parsed_document_id=$1", parsed_document_id)
                result = await conn.execute("DELETE FROM parsed_documents WHERE id=$1", parsed_document_id)
                if parse_job_id:
                    await conn.execute("DELETE FROM ingestion_job_errors WHERE job_id=$1", parse_job_id)
                    await conn.execute("DELETE FROM ingestion_jobs WHERE id=$1", parse_job_id)
        if preview_uri:
            try:
                from pathlib import Path

                Path(preview_uri).unlink(missing_ok=True)
            except OSError:
                pass
        return result == "DELETE 1"

    async def _source_uri(self, file_asset_id: str | None) -> str | None:
        if not file_asset_id:
            return None
        row = await self.db_pool.fetchrow(
            "SELECT bucket, object_key, original_filename, relative_path FROM file_assets WHERE id=$1",
            file_asset_id,
        )
        if not row:
            return None
        return f"minio://{row['bucket']}/{row['object_key']}"


def _json_value(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value
