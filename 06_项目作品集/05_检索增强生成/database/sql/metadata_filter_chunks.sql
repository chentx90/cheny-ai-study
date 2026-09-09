SELECT
    c.id AS chunk_id,
    c.document_id,
    c.chunk_index,
    c.section_path,
    c.title_context,
    c.content,
    c.summary,
    c.physical_context
FROM kb_chunks c
JOIN kb_documents d ON d.id = c.document_id
WHERE c.status = 'active'
  AND d.status = 'active'
  AND ($1::text IS NULL OR d.business_domain = $1)
  AND ($2::text IS NULL OR d.doc_type = $2)
ORDER BY c.created_at DESC
LIMIT $3;