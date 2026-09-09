import asyncio
from typing import Set
from ..core.schemas import ExecutionContext, RetrievalStep, DataAssetItem


class DataAssetSearchOperator:
    name = "data_asset_search"

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
        
        results = await adapter.data_asset_search(context.query, k=k)
        
        seen_ids: Set[str] = {d.asset_id for d in context.data_assets}
        
        for row in results:
            asset = DataAssetItem(
                asset_id=row.get("asset_id", ""),
                asset_type=row.get("asset_type", "data_asset"),
                name=row.get("name", ""),
                description=row.get("description"),
                business_domain=row.get("business_domain"),
                parent_name=row.get("parent_name"),
                synonyms=row.get("synonyms"),
                formula=row.get("formula"),
                related_table=row.get("related_table"),
                related_columns=row.get("related_columns"),
                example_values=row.get("example_values"),
                score=row.get("score"),
            )
            if asset.asset_id not in seen_ids:
                seen_ids.add(asset.asset_id)
                context.data_assets.append(asset)
        
        return context