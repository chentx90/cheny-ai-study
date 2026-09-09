# Backend Project Plan

## 1. Module Goal

The backend is the orchestration center of the RAG system. It exposes a unified retrieval API, receives requests from the frontend or Agent layer, creates retrieval plans, calls retriever strategies and storage adapters, and returns a structured knowledge package.

The backend should not hard-code one database to one retrieval method. It should use capability registration and retrieval plans.

## 2. Main Responsibilities

```text
Expose /retrieve
Analyze query intent
Build retrieval plan
Select retrieval strategies
Select backend capabilities
Call adapters
Merge and rank results
Return Knowledge Package
Write retrieval logs
```

## 3. Suggested Tech Stack

```text
Python
FastAPI
Pydantic
SQLAlchemy / asyncpg
httpx
LangChain optional
LangGraph optional for Agent route demo
Redis optional
```

## 4. Core Concepts

### Capability Registry

Each backend declares what it can do.

```json
{
  "backend_id": "postgres_pgvector",
  "capabilities": [
    "vector_search",
    "metadata_filter",
    "chunk_fetch",
    "parent_expand",
    "asset_fetch",
    "data_asset_search"
  ]
}
```

### Retrieval Strategy

Each strategy declares what it needs.

```json
{
  "strategy": "hybrid",
  "required_capabilities": [
    "vector_search",
    "bm25_search"
  ]
}
```

### Retrieval Plan

The backend creates runtime plans.

```json
{
  "query": "液压泵压力不足怎么办？",
  "plan": [
    {"strategy": "simple_vector", "capability": "vector_search"},
    {"strategy": "parent_context", "capability": "parent_expand"},
    {"strategy": "image_context", "capability": "asset_fetch"}
  ]
}
```

## 5. API Design

### Unified Retrieval

```text
POST /retrieve
```

Request:

```json
{
  "query": "液压泵压力不足怎么办？",
  "mode": "balanced",
  "constraints": {
    "business_domain": "equipment",
    "need_image": true,
    "need_citation": true
  }
}
```

Response:

```json
{
  "query": "...",
  "intent": "troubleshooting",
  "confidence": 0.82,
  "evidence": [],
  "missing_info": [],
  "retrieval_trace": {
    "strategies": [],
    "backends": [],
    "latency_ms": 0
  }
}
```

### Debug APIs

```text
GET /health
GET /capabilities
GET /strategies
POST /retrieve/plan
```

## 6. Suggested Directory Structure

```text
backend/
  app/
    main.py
    config.py
    api/
      retrieve.py
      debug.py
    core/
      planner.py
      registry.py
      schemas.py
    strategies/
      simple_vector.py
      hybrid.py
      parent_context.py
      image_context.py
      data_asset.py
      rerank.py
    adapters/
      base.py
      postgres.py
      mock.py
    services/
      services/embedding_client.py
      logging.py
  tests/
  Dockerfile
  README.md
```

## 7. First Vibe Coding Tasks

1. Create FastAPI app.
2. Add `/health`.
3. Add `/capabilities`.
4. Add `/retrieve` with mock result.
5. Implement capability registry.
6. Implement planner rules for fast / balanced / reliable.
7. Implement postgres adapter skeleton.
8. Connect simple pgvector query.
9. Return evidence and trace.
10. Add tests for planner and response schema.

## 8. Acceptance Criteria

```text
One unified /retrieve endpoint exists
Backend can create retrieval plan
Backend can route strategy to backend capability
Backend can return Knowledge Package
Backend can run even with mock adapters
Database details are hidden from frontend and Agent
```
