from .base import BaseStrategy


class HybridStrategy(BaseStrategy):
    name = "hybrid"
    capability = "vector_search"

    async def run(self, request, context):
        adapter = context.get("adapter")
        if adapter is None:
            return {"evidence": [], "assets": []}
        evidence = await adapter.vector_search(request.query)
        return {"evidence": evidence, "assets": []}
