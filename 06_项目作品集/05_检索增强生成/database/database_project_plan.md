# Database Project Plan

## 1. Module Goal

The database module provides storage for documents, chunks, assets, data assets, embeddings, and retrieval logs.

The first implementation uses PostgreSQL + pgvector. The schema should support retrieval, metadata filtering, parent context expansion, image asset lookup, and data asset matching.

## 2. Core Tables

```text
kb_documents
kb_chunks
kb_assets
data_assets
rag_query_logs
```

## 3. Table Responsibilities

### kb_documents

Stores document-level metadata.

```text
title
doc_type
source_uri
business_domain
version
status
```

### kb_chunks

Stores chunk text, context, preset questions, metadata, and embedding.

```text
document_id
chunk_index
section_path
title_context
content
summary
preset_questions
physical_context
embedding
embedding_model
token_count
status
```

### kb_assets

Stores image and attachment metadata.

```text
document_id
chunk_id
asset_type
asset_url
caption
ocr_text
description
physical_context
status
```

### data_assets

Stores table, column, metric, case, and tool assets.

```text
asset_type
name
description
business_domain
parent_name
synonyms
formula
related_table
related_columns
example_values
embedding
status
```

### rag_query_logs

Stores retrieval trace logs.

```text
query
agent_route
rag_method
retrieved_chunk_ids
retrieved_asset_ids
latency_ms
created_at
```

## 4. SQL Deliverables

```text
init.sql
seed_documents.sql
seed_data_assets.sql
indexes.sql
reset.sql
```

## 5. Required Extensions

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

## 6. Index Requirements

```text
HNSW index on kb_chunks.embedding
HNSW index on data_assets.embedding
btree index on status
btree index on business_domain
btree index on document_id
```

## 7. Chunk Data Format

Each chunk must be independently understandable.

```json
{
  "section_path": "设备维护 > 液压系统 > 压力不足",
  "title_context": "液压系统维护手册 - 压力不足故障排查",
  "content": "当液压泵压力不足时，应优先检查过滤器是否堵塞...",
  "summary": "说明液压泵压力不足时的优先检查项。",
  "preset_questions": [
    "液压泵压力不足怎么办？",
    "设备压力上不去应该先查哪里？"
  ],
  "physical_context": {
    "page": 18,
    "image_refs": ["asset_001"]
  }
}
```

## 8. First Vibe Coding Tasks

1. Create Docker Compose service for PostgreSQL + pgvector.
2. Write `init.sql`.
3. Create 5 core tables.
4. Add vector indexes.
5. Insert sample documents and chunks.
6. Insert sample image assets.
7. Insert sample data assets.
8. Test vector similarity query.
9. Test asset lookup by chunk_id.
10. Test data asset retrieval.

## 9. Acceptance Criteria

```text
PostgreSQL container starts successfully
pgvector extension is enabled
All 5 tables are created
Sample chunks can be inserted
Vector similarity search works
Image assets can be returned by chunk_id
Data assets can be searched
```

## 10. Demo Data

Recommended demo domain:

```text
equipment maintenance
quality management
production data
sales metric
```

Example query:

```text
液压泵压力不足怎么办？
销售额怎么算？
```