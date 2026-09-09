import asyncpg
import json
from typing import Optional
from ..schemas import Document, Chunk, DataAsset
from ..embeddings.mock import MockEmbedding


class PostgresWriter:
    """PostgreSQL 异步写入器，用于 ingestion 模块的独立 CLI 运行模式。

    直接通过 ``asyncpg`` 连接 PostgreSQL 数据库，将解析结果写入：

    1. ``kb_documents`` 表（文档元信息）。
    2. ``kb_chunks`` 表（文档的每个 Chunk，首行含 pseudo-vector 字符串）。
    3. ``data_assets`` 表（结构化数据资产）。

    ⚠️ 注意：后端接入链路不使用本写入器，而是通过
    ``backend/app/services/db_writer.py``（共享连接池）完成写库操作，
    以确保连接管理和事务在各服务间保持一致。
    """

    def __init__(self, dsn: str):
        """初始化 Postgres 写入器。

        Args:
            dsn: PostgreSQL 连接字符串，
                 如 ``postgresql://user:pass@host:port/dbname``。
        """
        self.dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
        self._embedding = MockEmbedding()

    async def connect(self):
        """创建异步连接池（最小 1，最大 10 个连接）。"""
        self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)

    async def close(self):
        """关闭连接池，释放所有数据库连接。"""
        if self._pool:
            await self._pool.close()

    async def write_document(self, document: Document) -> str:
        """将文档元信息写入 ``kb_documents`` 表并返回新文档 ID。

        Args:
            document: 待写入的 ``Document``。

        Returns:
            新插入文档的 ID（字符串格式）。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO kb_documents (title, doc_type, source_uri, business_domain, version, content_hash, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                document.title,
                document.doc_type,
                document.source_uri,
                document.business_domain,
                document.version,
                document.content_hash,
                document.status,
            )
            return str(row["id"])

    async def write_chunks(self, document_id: str, chunks: list[Chunk], embedding_model: str = "mock"):
        """将 Chunk 列表批量写入 ``kb_chunks`` 表。

        使用 ``executemany`` 批量插入，以提高写入效率。

        Args:
            document_id: 所属文档的 ID。
            chunks: 待写入的 ``Chunk`` 列表。
            embedding_model: embedding 模型名称，用于记录溯源。
        """
        if not chunks:
            return
        rows = []
        for idx, chunk in enumerate(chunks):
            embedding_text = chunk.build_embedding_text()
            vector = self._embedding.embed(embedding_text)
            rows.append((
                document_id,
                idx,
                chunk.section_path,
                chunk.title_context,
                chunk.content,
                chunk.summary,
                json.dumps(chunk.preset_questions, ensure_ascii=False),
                json.dumps(chunk.physical_context, ensure_ascii=False) if chunk.physical_context else None,
                str(vector),
                embedding_model,
                len(chunk.content),
                "active",
            ))
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO kb_chunks (document_id, chunk_index, section_path, title_context, content, summary, preset_questions, physical_context, embedding, embedding_model, token_count, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector, $10, $11, $12)
                """,
                rows,
            )

    async def ingest_document(self, document: Document, embedding_model: str = "mock") -> str:
        """将完整文档（元信息 + Chunk）写入数据库。

        Args:
            document: 待入库的 ``Document``。
            embedding_model: embedding 模型名称。

        Returns:
            新文档 ID。
        """
        doc_id = await self.write_document(document)
        await self.write_chunks(doc_id, document.chunks, embedding_model=embedding_model)
        return doc_id

    async def write_data_asset(self, asset: DataAsset, embedding_model: str = "mock") -> str:
        """将 ``DataAsset`` 写入 ``data_assets`` 表。

        Args:
            asset: 待写入的 ``DataAsset``。
            embedding_model: embedding 模型名称，用于记录溯源。

        Returns:
            新插入数据资产的 ID（字符串格式）。
        """
        embedding_text = asset.build_embedding_text()
        vector = self._embedding.embed(embedding_text)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO data_assets (asset_type, name, description, business_domain, parent_name, synonyms, formula, related_table, related_columns, example_values, embedding, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::vector, $12)
                RETURNING id
                """,
                asset.asset_type,
                asset.name,
                asset.description,
                asset.business_domain,
                asset.parent_name,
                asset.synonyms,
                asset.formula,
                asset.related_table,
                asset.related_columns,
                json.dumps(asset.example_values, ensure_ascii=False) if asset.example_values else None,
                str(vector),
                "active",
            )
            return str(row["id"])
