from abc import ABC, abstractmethod
from typing import List
from ..core.schemas import EvidenceItem, AssetItem, RetrieveRequest


class BaseStrategy(ABC):
    name: str
    capability: str

    @abstractmethod
    async def run(self, request: RetrieveRequest, context: dict) -> dict:
        pass


class SimpleVectorStrategy(BaseStrategy):
    name = "simple_vector"
    capability = "vector_search"

    async def run(self, request: RetrieveRequest, context: dict) -> dict:
        adapter = context.get("adapter")
        if adapter is None:
            return {"evidence": [], "assets": []}
        evidence = await adapter.vector_search(request.query)
        return {"evidence": evidence, "assets": []}
