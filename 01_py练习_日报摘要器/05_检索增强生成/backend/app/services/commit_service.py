"""提交服务：文档去重、归档、同名序号计算的数据库操作。"""
import json
from pathlib import Path
from typing import Optional
import asyncpg
import aiofiles


async def find_active_doc_by_hash(pool: asyncpg.Pool, content_hash: str, business_domain: str) -> Optional[dict]:
    if not content_hash:
        return None
    row = await pool.fetchrow(
        "SELECT id, title FROM kb_documents "
        "WHERE content_hash=$1 AND COALESCE(business_domain,'')=COALESCE($2,'') AND status='active' LIMIT 1",
        content_hash, business_domain,
    )
    return {"id": str(row["id"]), "title": row["title"]} if row else None


async def archive_doc(pool: asyncpg.Pool, doc_id: str) -> None:
    await pool.execute("UPDATE kb_chunks SET status='archived' WHERE document_id=$1", doc_id)
    await pool.execute("UPDATE kb_documents SET status='archived', updated_at=NOW() WHERE id=$1", doc_id)


async def next_available_title(pool: asyncpg.Pool, title: str, business_domain: str) -> str:
    rows = await pool.fetch(
        "SELECT title FROM kb_documents "
        "WHERE status='active' AND COALESCE(business_domain,'')=COALESCE($2,'') "
        "AND (title=$1 OR title LIKE $1||' (%')",
        title, business_domain,
    )
    existing = {r["title"] for r in rows}
    if title not in existing:
        return title
    n = 2
    while f"{title} ({n})" in existing:
        n += 1
    return f"{title} ({n})"


async def read_preview_doc(preview_uri: Optional[str]) -> Optional[dict]:
    if not preview_uri or not Path(preview_uri).exists():
        return None
    async with aiofiles.open(preview_uri, "r", encoding="utf-8") as f:
        return json.loads(await f.read()).get("document")
