CREATE TABLE IF NOT EXISTS kb_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    source_uri TEXT,
    business_domain TEXT,
    version TEXT,
    file_asset_id UUID,
    parsed_document_id UUID,
    content_hash TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES kb_documents(id),
    chunk_index INTEGER,
    section_path TEXT,
    title_context TEXT,
    content TEXT,
    summary TEXT,
    preset_questions JSONB,
    physical_context JSONB,
    embedding VECTOR(1024),
    embedding_model TEXT,
    token_count INTEGER,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kb_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES kb_documents(id),
    chunk_id UUID REFERENCES kb_chunks(id),
    asset_type TEXT NOT NULL,
    asset_url TEXT,
    caption TEXT,
    ocr_text TEXT,
    description TEXT,
    physical_context JSONB,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS data_assets (
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
    example_values JSONB,
    embedding VECTOR(1024),
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_query_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query TEXT NOT NULL,
    agent_route TEXT,
    rag_method TEXT,
    retrieved_chunk_ids UUID[],
    retrieved_asset_ids UUID[],
    latency_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
