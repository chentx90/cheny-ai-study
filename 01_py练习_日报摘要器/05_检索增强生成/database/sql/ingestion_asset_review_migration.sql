CREATE TABLE IF NOT EXISTS import_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    root_path TEXT,
    business_domain TEXT,
    total_files INTEGER DEFAULT 0,
    imported_files INTEGER DEFAULT 0,
    failed_files INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_filename TEXT NOT NULL,
    relative_path TEXT,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    storage_backend TEXT DEFAULT 'minio',
    file_ext TEXT,
    mime_type TEXT,
    file_size BIGINT,
    content_hash TEXT,
    business_domain TEXT,
    source_batch_id UUID REFERENCES import_batches(id),
    status TEXT DEFAULT 'uploaded',
    created_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE ingestion_uploads
    ADD COLUMN IF NOT EXISTS file_asset_id UUID REFERENCES file_assets(id);

ALTER TABLE kb_documents
    ADD COLUMN IF NOT EXISTS content_hash TEXT,
    ADD COLUMN IF NOT EXISTS file_asset_id UUID REFERENCES file_assets(id),
    ADD COLUMN IF NOT EXISTS parsed_document_id UUID;

CREATE TABLE IF NOT EXISTS parsed_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_asset_id UUID REFERENCES file_assets(id),
    parse_job_id UUID REFERENCES ingestion_jobs(id),
    title TEXT NOT NULL,
    doc_type TEXT,
    business_domain TEXT,
    content_hash TEXT,
    markdown_text TEXT,
    stats JSONB,
    status TEXT DEFAULT 'draft',
    review_notes TEXT,
    kb_document_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    approved_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunk_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parsed_document_id UUID REFERENCES parsed_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER,
    section_path TEXT,
    title_context TEXT,
    content TEXT,
    summary TEXT,
    preset_questions JSONB,
    physical_context JSONB,
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS embedding_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parsed_document_id UUID REFERENCES parsed_documents(id),
    status TEXT DEFAULT 'pending',
    stage TEXT,
    progress INTEGER DEFAULT 0,
    embedding_provider TEXT DEFAULT 'api',
    embedding_model TEXT DEFAULT 'text-embedding-3-small',
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_file_assets_hash_domain ON file_assets(content_hash, business_domain);
CREATE INDEX IF NOT EXISTS idx_file_assets_batch ON file_assets(source_batch_id);
CREATE INDEX IF NOT EXISTS idx_parsed_documents_file_asset ON parsed_documents(file_asset_id);
CREATE INDEX IF NOT EXISTS idx_chunk_drafts_parsed_document ON chunk_drafts(parsed_document_id);
CREATE INDEX IF NOT EXISTS idx_embedding_jobs_parsed_document ON embedding_jobs(parsed_document_id);
