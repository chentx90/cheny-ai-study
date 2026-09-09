# Database Module Framework

## 1. Module Boundary

The database module provides schema, seed data, indexes, and SQL examples.

The first backend is PostgreSQL + pgvector. Other vector stores or search engines can be added later through adapters.

## 2. Directory Framework

```text
database/
  sql/
    001_extensions.sql
    002_tables.sql
    003_indexes.sql
    004_seed_documents.sql
    005_seed_data_assets.sql
    999_reset.sql

  samples/
    documents.json
    chunks.json
    assets.json
    data_assets.json

  queries/
    vector_search.sql
    asset_fetch.sql
    data_asset_search.sql
    parent_expand.sql

  docker/
    Dockerfile
    docker-compose.database.yml

  README.md
```

## 3. Core Tables

```text
kb_documents
kb_chunks
kb_assets
data_assets
rag_query_logs
```

## 4. SQL Skeleton

### Extensions

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

### Documents

```sql
CREATE TABLE kb_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    doc_type TEXT,
    source_uri TEXT,
    business_domain TEXT,
    version INT DEFAULT 1,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### Chunks

```sql
CREATE TABLE kb_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES kb_documents(id),
    chunk_index INT,
    section_path TEXT,
    title_context TEXT,
    content TEXT NOT NULL,
    summary TEXT,
    preset_questions TEXT[],
    physical_context JSONB,
    embedding vector(1024),
    embedding_model TEXT,
    token_count INT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### Assets

```sql
CREATE TABLE kb_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES kb_documents(id),
    chunk_id UUID REFERENCES kb_chunks(id),
    asset_type TEXT DEFAULT 'image',
    asset_url TEXT NOT NULL,
    caption TEXT,
    ocr_text TEXT,
    description TEXT,
    physical_context JSONB,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT now()
);
```

### Data Assets

```sql
CREATE TABLE data_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    business_domain TEXT,
    parent_name TEXT,
    synonyms TEXT[],
    formula TEXT,
    related_table TEXT,
    related_columns TEXT[],
    example_values TEXT[],
    embedding vector(1024),
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT now()
);
```

### Query Logs

```sql
CREATE TABLE rag_query_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query TEXT NOT NULL,
    agent_route TEXT,
    rag_method TEXT,
    retrieved_chunk_ids UUID[],
    retrieved_asset_ids UUID[],
    latency_ms INT,
    created_at TIMESTAMP DEFAULT now()
);
```

## 5. Indexes

```sql
CREATE INDEX kb_chunks_embedding_hnsw_idx
ON kb_chunks
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX data_assets_embedding_hnsw_idx
ON data_assets
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX kb_chunks_status_idx ON kb_chunks(status);
CREATE INDEX kb_documents_domain_idx ON kb_documents(business_domain);
CREATE INDEX kb_assets_chunk_id_idx ON kb_assets(chunk_id);
```

## 6. First Acceptance Test

```text
Database starts
Extensions are enabled
All tables exist
Seed data inserts successfully
Vector search query returns rows
Asset fetch by chunk_id returns image URL
```