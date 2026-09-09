from .base import BaseStrategy


class DataAssetStrategy(BaseStrategy):
    name = "data_asset"
    capability = "data_asset_search"

    async def run(self, request, context):
        adapter = context.get("adapter")
        if adapter is None:
            return {"evidence": context.get("evidence", []), "assets": []}
        data_assets = await adapter.data_asset_search(request.query)
        return {"evidence": context.get("evidence", []), "assets": data_assets}
