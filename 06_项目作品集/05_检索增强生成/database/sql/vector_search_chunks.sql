SELECT
    c.id AS chunk_id,
    c.document_id,
    c.section_path,
    c.title_context,
    c.content,
    c.summary,
    c.preset_questions,
    c.physical_context,
    1 - (c.embedding <=> $1::vector) AS score
FROM kb_chunks c
JOIN kb_documents d ON d.id = c.document_id
WHERE c.status = 'active'
  AND d.status = 'active'
  AND ($3::text IS NULL OR d.business_domain = $3)
ORDER BY c.embedding <=> $1::vector
LIMIT $2;