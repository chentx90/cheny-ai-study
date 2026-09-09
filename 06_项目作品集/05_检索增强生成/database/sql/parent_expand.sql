SELECT
    id AS chunk_id,
    document_id,
    chunk_index,
    section_path,
    title_context,
    content,
    summary,
    physical_context
FROM kb_chunks
WHERE document_id = $1
  AND chunk_index BETWEEN $2 AND $3
  AND status = 'active'
ORDER BY chunk_index;