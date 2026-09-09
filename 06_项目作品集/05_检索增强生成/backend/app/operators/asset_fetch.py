import asyncio
from typing import Set
from ..core.schemas import ExecutionContext, RetrievalStep, AssetItem


class AssetFetchOperator:
    name = "asset_fetch"

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
        
        seen_asset_ids: Set[str] = {a.asset_id for a in context.assets}
        
        tasks = [adapter.asset_fetch(e.chunk_id) for e in context.evidence]
        results = await asyncio.gather(*tasks)
        
        for evidence, asset_list in zip(context.evidence, results):
            for asset in asset_list:
                if asset.asset_id not in seen_asset_ids:
                    seen_asset_ids.add(asset.asset_id)
                    context.assets.append(asset)
                    evidence.assets.append(asset)
        
        return context