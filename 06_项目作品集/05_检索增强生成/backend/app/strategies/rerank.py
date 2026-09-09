from .base import BaseStrategy


class RerankStrategy(BaseStrategy):
    name = "rerank"
    capability = "rerank"

    async def run(self, request, context):
        evidence = context.get("evidence", [])
        return {"evidence": evidence, "assets": []}
