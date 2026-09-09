SELECT 'kb_documents' AS table_name, COUNT(*) FROM kb_documents
UNION ALL
SELECT 'kb_chunks', COUNT(*) FROM kb_chunks
UNION ALL
SELECT 'kb_assets', COUNT(*) FROM kb_assets
UNION ALL
SELECT 'data_assets', COUNT(*) FROM data_assets
UNION ALL
SELECT 'rag_query_logs', COUNT(*) FROM rag_query_logs;