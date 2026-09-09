"""数据写入器子包。

提供将解析结果持久化到外部存储的能力：

- **PostgresWriter**：通过 asyncpg 异步池连接 PostgreSQL，直接写入
  ``kb_documents``、``kb_chunks``、``data_assets`` 表。
  专为 ingestion 的独立 CLI 运行模式设计。

⚠️ 注意：后端接入链路不使用本写入器，而是通过
``backend/app/services/db_writer.py`` 利用共享连接池完成写库操作。

- **JsonWriter**：将 ``Document`` 或 ``DataAsset`` 序列化为 JSON 文件，
  用于开发调试时的预览和校验。
"""
from .postgres import PostgresWriter
from .json import JsonWriter

__all__ = ['PostgresWriter', 'JsonWriter']
