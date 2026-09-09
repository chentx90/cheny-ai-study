from typing import List, Optional
import time
from .base import BaseAdapter
from ..core.schemas import EvidenceItem, AssetItem


class MockAdapter(BaseAdapter):
    def __init__(self):
        self._mock_chunks = [
            EvidenceItem(
                chunk_id="chunk_001",
                document_id="doc_001",
                section_path="设备维护 > 液压系统 > 压力不足",
                title_context="液压系统维护手册 - 压力不足故障排查",
                content="当液压泵压力不足时，应优先检查过滤器是否堵塞。过滤器堵塞会导致油液无法正常循环，造成压力上不去的问题。其次检查油液液位是否正常，如果油液太少也会影响压力输出。最后检查泄压阀和液压阀是否工作正常。",
                score=0.95,
                physical_context={"page": 18, "image_refs": ["hydraulic_filter_001"]}
            ),
            EvidenceItem(
                chunk_id="chunk_002",
                document_id="doc_001",
                section_path="设备维护 > 液压系统 > 维护周期",
                title_context="液压系统维护手册 - 维护周期",
                content="液压系统的维护周期一般为3个月进行一次常规检查，每6个月进行一次深度维护。常规检查包括更换过滤器、检查油液液位、观察系统运行状态。",
                score=0.82,
                physical_context={"page": 5, "image_refs": []}
            ),
        ]
        self._mock_assets = [
            AssetItem(
                asset_id="asset_001",
                asset_type="image",
                asset_url="/assets/images/hydraulic_filter_001.png",
                caption="液压滤器结构图",
                ocr_text="滤器过滤网孔尺寸为200目",
                description="液压滤器的详细结构，用于故障诊断"
            )
        ]

    async def vector_search(self, query: str, k: int = 5, query_embedding: Optional[List[float]] = None) -> List[EvidenceItem]:
        time.sleep(0.05)
        return self._mock_chunks[:k]

    async def metadata_filter(self, **filters) -> List[EvidenceItem]:
        return self._mock_chunks

    async def chunk_fetch(self, chunk_id: str) -> Optional[EvidenceItem]:
        for chunk in self._mock_chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        return None

    async def parent_expand(self, chunk: EvidenceItem, limit: int = 3) -> List[EvidenceItem]:
        return []

    async def asset_fetch(self, chunk_id: str) -> List[AssetItem]:
        if chunk_id == "chunk_001":
            return self._mock_assets
        return []

    async def data_asset_search(self, query: str, k: int = 5) -> List[dict]:
        return [
            {"asset_type": "metric", "name": "销售额", "description": "计算销售总额的指标", "score": 0.9}
        ][:k]
