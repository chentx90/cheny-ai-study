INSERT INTO rag_query_logs (
    query,
    agent_route,
    rag_method,
    retrieved_chunk_ids,
    retrieved_asset_ids,
    latency_ms
)
VALUES ($1, $2, $3, $4, $5, $6);