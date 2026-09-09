import json
from typing import List, Optional

import asyncpg

from .base import BaseAdapter
from ..core.schemas import AssetItem, EvidenceItem
from ..services.embedding_client import embedding_service


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def _json_dict(value) -> dict | None:
    if value is None or isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


class PostgresAdapter(BaseAdapter):
    def __init__(self, dsn: Optional[str] = None, pool: Optional[asyncpg.Pool] = None):
        self.dsn = dsn
        self._pool = pool

    async def connect(self):
        if self._pool is None:
            if not self.dsn:
                raise RuntimeError("PostgresAdapter requires either dsn or pool")
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        return self._pool

    async def _pool_or_connect(self):
        if self._pool is None:
            await self.connect()
        return self._pool

    def _evidence_from_row(self, row, score: float = 1.0) -> EvidenceItem:
        return EvidenceItem(
            chunk_id=str(row["id"]),
            document_id=str(row["document_id"]),
            section_path=row.get("section_path") or "",
            title_context=row.get("title_context") or "",
            content=row.get("content") or "",
            score=float(row.get("score") or score),
            physical_context=_json_dict(row.get("physical_context")),
        )

    async def vector_search(self, query: str, k: int = 5, query_embedding: Optional[List[float]] = None) -> List[EvidenceItem]:
        pool = await self._pool_or_connect()
        if query_embedding:
            rows = await pool.fetch(
                """
                SELECT id, document_id, section_path, title_context, content, physical_context,
                       1 - (embedding <=> $1::vector) AS score
                FROM kb_chunks
                WHERE status = 'active'
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                _vector_literal(query_embedding),
                k,
            )
            return [self._evidence_from_row(row) for row in rows]
        rows = await pool.fetch(
            """
            SELECT id, document_id, section_path, title_context, content, physical_context,
                   CASE
                       WHEN content ILIKE $1 THEN 1.0
                       WHEN title_context ILIKE $1 THEN 0.8
                       ELSE 0.5
                   END AS score
            FROM kb_chunks
            WHERE status = 'active'
              AND ($2 = '' OR content ILIKE $1 OR title_context ILIKE $1 OR section_path ILIKE $1)
            ORDER BY score DESC, created_at DESC
            LIMIT $3
            """,
            f"%{query}%",
            query.strip(),
            k,
        )
        return [self._evidence_from_row(row) for row in rows]

    async def metadata_filter(self, **filters) -> List[EvidenceItem]:
        pool = await self._pool_or_connect()
        business_domain = filters.get("business_domain")
        rows = await pool.fetch(
            """
            SELECT c.id, c.document_id, c.section_path, c.title_context, c.content, c.physical_context
            FROM kb_chunks c
            JOIN kb_documents d ON d.id = c.document_id
            WHERE c.status = 'active'
              AND d.status = 'active'
              AND ($1::text IS NULL OR d.business_domain = $1)
            ORDER BY c.created_at DESC
            LIMIT 100
            """,
            business_domain,
        )
        return [self._evidence_from_row(row) for row in rows]

    async def chunk_fetch(self, chunk_id: str) -> Optional[EvidenceItem]:
        pool = await self._pool_or_connect()
        row = await pool.fetchrow(
            """
            SELECT id, document_id, section_path, title_context, content, physical_context
            FROM kb_chunks
            WHERE id = $1::uuid AND status = 'active'
            """,
            chunk_id,
        )
        return self._evidence_from_row(row) if row else None

    async def parent_expand(self, chunk: EvidenceItem, limit: int = 3) -> List[EvidenceItem]:
        pool = await self._pool_or_connect()
        rows = await pool.fetch(
            """
            WITH current_chunk AS (
                SELECT document_id, chunk_index
                FROM kb_chunks
                WHERE id = $1::uuid
            )
            SELECT c.id, c.document_id, c.section_path, c.title_context, c.content, c.physical_context
            FROM kb_chunks c
            JOIN current_chunk cur ON cur.document_id = c.document_id
            WHERE c.status = 'active'
              AND c.chunk_index BETWEEN cur.chunk_index - $2 AND cur.chunk_index + $2
            ORDER BY c.chunk_index
            """,
            chunk.chunk_id,
            max(limit // 2, 1),
        )
        return [self._evidence_from_row(row) for row in rows]

    async def asset_fetch(self, chunk_id: str) -> List[AssetItem]:
        pool = await self._pool_or_connect()
        rows = await pool.fetch(
            """
            SELECT id, asset_type, asset_url, caption, ocr_text, description
            FROM kb_assets
            WHERE chunk_id = $1::uuid AND status = 'active'
            ORDER BY created_at
            """,
            chunk_id,
        )
        return [
            AssetItem(
                asset_id=str(row["id"]),
                asset_type=row["asset_type"],
                asset_url=row["asset_url"] or "",
                caption=row["caption"],
                ocr_text=row["ocr_text"],
                description=row["description"],
            )
            for row in rows
        ]

    async def data_asset_search(self, query: str, k: int = 5) -> List[dict]:
        pool = await self._pool_or_connect()
        query_embedding = await embedding_service.embed(query)
        rows = await pool.fetch(
            """
            SELECT id, asset_type, name, description, business_domain, parent_name,
                   synonyms, formula, related_table, related_columns, example_values,
                   1 - (embedding <=> $1::vector) AS score
            FROM data_assets
            WHERE status = 'active'
              AND embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            _vector_literal(query_embedding),
            k,
        )
        return [dict(row) | {"asset_id": str(row["id"])} for row in rows]

    async def list_documents(
        self,
        limit: int = 100,
        business_domain: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[dict]:
        pool = await self._pool_or_connect()
        rows = await pool.fetch(
            """
            SELECT id, title, doc_type, source_uri, business_domain, version,
                   content_hash, file_asset_id, parsed_document_id, status, created_at
            FROM kb_documents
            WHERE status = 'active'
              AND ($1::text IS NULL OR business_domain = $1)
              AND ($2::text IS NULL OR title ILIKE '%' || $2 || '%' OR source_uri ILIKE '%' || $2 || '%')
            ORDER BY created_at DESC
            LIMIT $3
            """,
            business_domain,
            keyword,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_chunks(self, doc_id: str) -> List[dict]:
        pool = await self._pool_or_connect()
        rows = await pool.fetch(
            """
            SELECT id, document_id, chunk_index, section_path, title_context, content,
                   summary, preset_questions, physical_context, token_count, status, created_at
            FROM kb_chunks
            WHERE document_id = $1::uuid AND status = 'active'
            ORDER BY chunk_index
            """,
            doc_id,
        )
        return [dict(row) for row in rows]

    async def delete_document(self, doc_id: str) -> bool:
        pool = await self._pool_or_connect()
        async with pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    "UPDATE kb_documents SET status = 'archived' WHERE id = $1::uuid AND status <> 'archived'",
                    doc_id,
                )
                await conn.execute("UPDATE kb_chunks SET status = 'archived' WHERE document_id = $1::uuid", doc_id)
                await conn.execute("UPDATE kb_assets SET status = 'archived' WHERE document_id = $1::uuid", doc_id)
        return not result.endswith(" 0")

    async def list_data_assets(
        self,
        keyword: Optional[str] = None,
        business_domain: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict]:
        pool = await self._pool_or_connect()
        rows = await pool.fetch(
            """
            SELECT id, asset_type, name, description, business_domain, parent_name,
                   synonyms, formula, related_table, related_columns, example_values, status, created_at
            FROM data_assets
            WHERE status = 'active'
              AND ($1::text IS NULL OR business_domain = $1)
              AND ($2::text IS NULL OR name ILIKE '%' || $2 || '%' OR description ILIKE '%' || $2 || '%')
            ORDER BY created_at DESC
            LIMIT $3
            """,
            business_domain,
            keyword,
            limit,
        )
        return [dict(row) for row in rows]

    async def delete_data_asset(self, asset_id: str) -> bool:
        pool = await self._pool_or_connect()
        result = await pool.execute(
            "UPDATE data_assets SET status = 'archived' WHERE id = $1::uuid AND status <> 'archived'",
            asset_id,
        )
        return not result.endswith(" 0")
