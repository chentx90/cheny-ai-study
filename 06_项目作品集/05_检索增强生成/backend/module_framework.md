# Backend Module Framework

## 1. Module Boundary

The backend is the RAG gateway and orchestration layer.

It receives requests from frontend or Agent, creates retrieval plans, calls strategies and adapters, and returns a Knowledge Package.

It should not hard-code a specific database to a specific retrieval method.

## 2. Recommended Stack

```text
Python
FastAPI
Pydantic
SQLAlchemy / asyncpg
httpx
pytest
structlog
```

Optional:

```text
LangChain
LangGraph
Redis
Reranker model service
```

## 3. Directory Framework

```text
backend/
  app/
    main.py
    config.py

    api/
      retrieve.py
      debug.py
      knowledge.py

    core/
      schemas.py
      registry.py
      planner.py
      trace.py
      errors.py

    strategies/
      base.py
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
      fusion.py
      logging.py

  tests/
    test_planner.py
    test_retrieve_api.py
    test_postgres_adapter.py

  Dockerfile
  README.md
```

## 4. Core Runtime Flow

```text
POST /retrieve
  ↓
parse request
  ↓
analyze mode and constraints
  ↓
planner builds retrieval plan
  ↓
runtime executes strategies
  ↓
adapters query backends
  ↓
fusion and context expansion
  ↓
return Knowledge Package
```

## 5. Capability Registry

```python
BACKENDS = {
    "postgres_pgvector": {
        "capabilities": [
            "vector_search",
            "metadata_filter",
            "chunk_fetch",
            "parent_expand",
            "asset_fetch",
            "data_asset_search",
            "log_write",
        ]
    },
    "mock": {
        "capabilities": [
            "vector_search",
            "asset_fetch",
        ]
    },
}
```

## 6. Strategy Contract

```python
class RetrievalStrategy:
    name: str
    required_capabilities: list[str]

    async def run(self, request, context):
        ...
```

## 7. Adapter Contract

```python
class StorageAdapter:
    backend_id: str
    capabilities: list[str]

    async def execute(self, capability: str, payload: dict) -> dict:
        ...
```

## 8. Main API Schema

```python
class RetrieveRequest(BaseModel):
    query: str
    mode: str = "balanced"
    constraints: dict = {}

class RetrieveResponse(BaseModel):
    query: str
    intent: str | None = None
    confidence: float | None = None
    evidence: list[dict]
    missing_info: list[str] = []
    retrieval_trace: dict = {}
```

## 9. First Files To Create

```text
app/main.py
app/api/retrieve.py
app/core/schemas.py
app/core/registry.py
app/core/planner.py
app/adapters/mock.py
app/strategies/simple_vector.py
tests/test_retrieve_api.py
```

## 10. First Acceptance Test

```text
GET /health returns ok
GET /capabilities returns backend capabilities
POST /retrieve returns mock Knowledge Package
retrieval_trace contains selected strategy and backend
```
