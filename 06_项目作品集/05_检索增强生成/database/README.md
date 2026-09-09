# 数据库模块

## 表结构与关联

```
kb_documents (文档元数据)
  id, title, doc_type, business_domain, content_hash, status
  │
  ├─ 1:N ──▶ kb_chunks (文本块)
  │           id, doc_id, content, summary, preset_questions,
  │           embedding vector(1536), position, parent_id
  │
  ├─ 1:N ──▶ kb_assets (图片/附件)
  │           id, doc_id, asset_url, ocr_text, caption
  │
  └─ 1:N ──▶ data_assets (结构化数据)
              id, doc_id, metric/table/column, embedding vector(1536)

ingestion_uploads (上传文件)
  id, filename, file_path, created_at
  │
  └─ 1:N ──▶ ingestion_jobs (接入任务, ON DELETE CASCADE)
              id, upload_id, status, stage, progress,
              preview_uri, result (JSONB)
              │
              └─ 1:N ──▶ ingestion_job_errors (错误明细)

rag_query_logs  (检索日志，独立)
```

`content_hash`（TEXT）= SHA256(归一化正文 + business_domain)，用于入库去重；`status` 区分 `active`/`archived`，检索层只读 `active`。

## 种子文件执行顺序

```
seeds/
  00_extensions.sql      CREATE EXTENSION vector; pgcrypto
  01_tables.sql          建表（含 content_hash 列）
  02_seed_documents.sql
  03_seed_chunks.sql
  04_seed_assets.sql
  05_seed_data_assets.sql
  06_indexes.sql         HNSW 向量索引 + content_hash 联合索引
  10_ingestion_tables.sql  接入相关表（ON DELETE CASCADE）
```

## 关键索引

```sql
-- 向量检索（HNSW，余弦距离）
CREATE INDEX idx_kb_chunks_embedding ON kb_chunks
  USING hnsw (embedding vector_cosine_ops);

-- 去重查询
CREATE INDEX idx_kb_documents_content_hash
  ON kb_documents(content_hash, business_domain);
```

## 启动

```bash
docker compose up -d   # 自动执行 seeds/ 下所有 .sql
```

## 现有库迁移（添加 content_hash）

```sql
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS content_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_kb_documents_content_hash
  ON kb_documents(content_hash, business_domain);
```
