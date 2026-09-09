from .base import BaseStrategy


class ImageContextStrategy(BaseStrategy):
    name = "image_context"
    capability = "asset_fetch"

    async def run(self, request, context):
        adapter = context.get("adapter")
        if adapter is None:
            return {"evidence": context.get("evidence", []), "assets": []}
        evidence = context.get("evidence", [])
        assets = []
        for item in evidence:
            item_assets = await adapter.asset_fetch(item.chunk_id)
            item.assets.extend(item_assets)
            assets.extend(item_assets)
        return {"evidence": evidence, "assets": assets}
