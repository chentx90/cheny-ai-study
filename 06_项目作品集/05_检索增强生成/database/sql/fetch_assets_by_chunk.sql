SELECT
    id AS asset_id,
    asset_type,
    asset_url,
    caption,
    ocr_text,
    description,
    physical_context
FROM kb_assets
WHERE chunk_id = $1
  AND status = 'active';