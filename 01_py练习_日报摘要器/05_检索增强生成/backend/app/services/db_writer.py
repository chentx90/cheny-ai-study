"""Write approved knowledge objects to PostgreSQL."""
from __future__ import annotations

import json
from typing import List, Optional

import asyncpg

from .embedding_client import embedding_service


def _build_embedding_text(chunk: dict) -> str:
    parts = [
        f"[Title Context] {chunk.get('title_context', '')}",
        f"[Section Path] {chunk.get('section_path', '')}",
        f"[Summary] {chunk.get('summary', '')}",
        f"[Content] {chunk.get('content', '')}",
        f"[Preset Questions] {' '.join(chunk.get('preset_questions') or [])}",
    ]
    return "\n".join(parts)


async def write_document_with_chunks(
    pool: asyncpg.Pool,
    doc: dict,
    chunks: List[dict],
    embedding_model: Optional[str] = None,
) -> str:
    embedding_model = embedding_model or embedding_service.model
    embedding_texts = [_build_embedding_text(chunk) for chunk in chunks]
    embeddings = await embedding_service.embed_many(embedding_texts) if embedding_texts else []

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO kb_documents
                  (title, doc_type, source_uri, business_domain, version, content_hash, status,
                   file_asset_id, parsed_document_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                doc.get("title", ""),
                doc.get("doc_type", "manual"),
                doc.get("source_uri"),
                doc.get("business_domain", "general"),
                doc.get("version", "1.0"),
                doc.get("content_hash"),
                doc.get("status", "active"),
                doc.get("file_asset_id"),
                doc.get("parsed_document_id"),
            )
            doc_id = str(row["id"])

            if chunks:
                rows = [
                    (
                        doc_id,
                        idx,
                        chunk.get("section_path", ""),
                        chunk.get("title_context", ""),
                        chunk.get("content", ""),
                        chunk.get("summary", ""),
                        json.dumps(chunk.get("preset_questions") or [], ensure_ascii=False),
                        json.dumps(chunk.get("physical_context"), ensure_ascii=False) if chunk.get("physical_context") else None,
                        _vector_literal(embeddings[idx]),
                        embedding_model,
                        len(chunk.get("content", "")),
                        "active",
                    )
                    for idx, chunk in enumerate(chunks)
                ]
                await conn.executemany(
                    """
                    INSERT INTO kb_chunks
                      (document_id, chunk_index, section_path, title_context, content, summary,
                       preset_questions, physical_context, embedding, embedding_model, token_count, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector, $10, $11, $12)
                    """,
                    rows,
                )
    return doc_id


async def write_data_asset(pool: asyncpg.Pool, asset: dict, embedding_model: Optional[str] = None) -> str:
    embedding_model = embedding_model or embedding_service.model
    embed_text = " ".join(
        filter(
            None,
            [
                asset.get("name", ""),
                asset.get("description", ""),
                asset.get("business_domain", ""),
                asset.get("formula", ""),
            ],
        )
    )
    embedding = await embedding_service.embed(embed_text)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO data_assets
              (asset_type, name, description, business_domain, parent_name, synonyms,
               formula, related_table, related_columns, example_values, embedding, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::vector, $12)
            RETURNING id
            """,
            asset.get("asset_type", ""),
            asset.get("name", ""),
            asset.get("description", ""),
            asset.get("business_domain", "general"),
            asset.get("parent_name"),
            asset.get("synonyms") or [],
            asset.get("formula"),
            asset.get("related_table"),
            asset.get("related_columns") or [],
            json.dumps(asset.get("example_values"), ensure_ascii=False) if asset.get("example_values") else None,
            _vector_literal(embedding),
            "active",
        )
    return str(row["id"])


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"
