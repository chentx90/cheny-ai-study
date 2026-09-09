from typing import List
from ..core.schemas import ExecutionContext, RetrievalStep, EvidenceItem
from ..services.embedding_client import embedding_service


class VectorSearchOperator:
    name = "vector_search"

    async def run(
        self,
        step: RetrievalStep,
        context: ExecutionContext,
        adapter_registry,
    ) -> ExecutionContext:
        backend_id = step.backend or "postgres_pgvector"
        adapter = adapter_registry.get(backend_id)
        if adapter is None:
            raise RuntimeError(f"Adapter not registered: {backend_id}")
        
        params = step.params or {}
        k = params.get("top_k", 5)
        
        if context.query_embedding is None:
            context.query_embedding = await embedding_service.embed(context.query)
        
        items = await adapter.vector_search(context.query, k=k, query_embedding=context.query_embedding)
        context.evidence.extend(items)
        
        return context
