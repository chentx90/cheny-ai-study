CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding ON kb_chunks USING hnsw (embedding vector_l2_ops);
CREATE INDEX IF NOT EXISTS idx_data_assets_embedding ON data_assets USING hnsw (embedding vector_l2_ops);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_status ON kb_chunks(status);
CREATE INDEX IF NOT EXISTS idx_kb_documents_business_domain ON kb_documents(business_domain);
CREATE INDEX IF NOT EXISTS idx_kb_documents_content_hash ON kb_documents(content_hash, business_domain);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_document_id ON kb_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_assets_chunk_id ON kb_assets(chunk_id);
CREATE INDEX IF NOT EXISTS idx_rag_query_logs_created_at ON rag_query_logs(created_at);