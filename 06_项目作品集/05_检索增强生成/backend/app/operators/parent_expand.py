import asyncio
from typing import List, Set
from ..core.schemas import ExecutionContext, RetrievalStep, EvidenceItem


class ParentExpandOperator:
    name = "parent_expand"

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
        if not context.evidence:
            return context
        
        params = step.params or {}
        window = params.get("window", 1)
        
        seen_ids: Set[str] = {e.chunk_id for e in context.evidence}
        
        tasks = []
        for evidence in context.evidence:
            tasks.append(adapter.parent_expand(evidence, limit=window * 2 + 1))
        
        results = await asyncio.gather(*tasks)
        
        for expanded_list in results:
            for item in expanded_list:
                if item.chunk_id not in seen_ids:
                    seen_ids.add(item.chunk_id)
                    context.evidence.append(item)
        
        return context