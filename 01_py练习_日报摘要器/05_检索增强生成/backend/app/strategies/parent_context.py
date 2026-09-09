from .base import BaseStrategy


class ParentContextStrategy(BaseStrategy):
    name = "parent_context"
    capability = "parent_expand"

    async def run(self, request, context):
        adapter = context.get("adapter")
        if adapter is None:
            return {"evidence": [], "assets": []}
        evidence = context.get("evidence", [])
        expanded = []
        for item in evidence:
            expanded.extend(await adapter.parent_expand(item))
        return {"evidence": expanded, "assets": []}
