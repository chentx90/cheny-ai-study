from abc import ABC, abstractmethod
from typing import List, Optional
from ..core.schemas import EvidenceItem, AssetItem


class BaseAdapter(ABC):
    @abstractmethod
    async def vector_search(self, query: str, k: int = 5, query_embedding: Optional[List[float]] = None) -> List[EvidenceItem]:
        pass

    @abstractmethod
    async def metadata_filter(self, **filters) -> List[EvidenceItem]:
        pass

    @abstractmethod
    async def chunk_fetch(self, chunk_id: str) -> Optional[EvidenceItem]:
        pass

    @abstractmethod
    async def parent_expand(self, chunk: EvidenceItem, limit: int = 3) -> List[EvidenceItem]:
        pass

    @abstractmethod
    async def asset_fetch(self, chunk_id: str) -> List[AssetItem]:
        pass

    @abstractmethod
    async def data_asset_search(self, query: str, k: int = 5) -> List[dict]:
        pass
