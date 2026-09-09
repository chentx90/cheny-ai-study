SELECT
    'kb_chunks_missing_embedding' AS check_name,
    COUNT(*) AS count
FROM kb_chunks
WHERE status = 'active'
  AND embedding IS NULL
UNION ALL
SELECT
    'data_assets_missing_embedding',
    COUNT(*)
FROM data_assets
WHERE status = 'active'
  AND embedding IS NULL;