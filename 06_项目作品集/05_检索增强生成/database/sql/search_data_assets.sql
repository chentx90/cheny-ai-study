SELECT
    id AS asset_id,
    asset_type,
    name,
    description,
    business_domain,
    parent_name,
    synonyms,
    formula,
    related_table,
    related_columns,
    example_values,
    1 - (embedding <=> $1::vector) AS score
FROM data_assets
WHERE status = 'active'
ORDER BY embedding <=> $1::vector
LIMIT $2;