from pydantic import BaseModel, Field
from typing import List, Optional, Any
from enum import Enum


class RetrievalMode(str, Enum):
    fast = "fast"
    balanced = "balanced"
    reliable = "reliable"
    deep = "deep"


class RetrieveRequest(BaseModel):
    query: str
    method: Optional[str] = None
    mode: RetrievalMode = RetrievalMode.balanced
    constraints: Optional[dict] = None


class EvidenceItem(BaseModel):
    chunk_id: str
    document_id: str
    section_path: str
    title_context: str
    content: str
    score: float
    physical_context: Optional[dict] = None
    assets: List[Any] = Field(default_factory=list)


class AssetItem(BaseModel):
    asset_id: str
    asset_type: str
    asset_url: str
    caption: Optional[str]
    ocr_text: Optional[str]
    description: Optional[str]


class DataAssetItem(BaseModel):
    asset_id: str
    asset_type: str = "data_asset"
    name: str = ""
    description: Optional[str] = None
    business_domain: Optional[str] = None
    parent_name: Optional[str] = None
    synonyms: Optional[Any] = None
    formula: Optional[str] = None
    related_table: Optional[str] = None
    related_columns: Optional[Any] = None
    example_values: Optional[Any] = None
    score: Optional[float] = None


class RetrievalStep(BaseModel):
    name: str
    operator: str
    backend: str = "postgres_pgvector"
    params: dict = Field(default_factory=dict)


class RetrievalMethod(BaseModel):
    method_id: str
    description: Optional[str] = None
    steps: List[RetrievalStep] = Field(default_factory=list)


class TraceStep(BaseModel):
    name: str
    operator: str
    backend: str
    status: str
    latency_ms: int
    input_count: int = 0
    output_count: int = 0
    error: Optional[str] = None


class ExecutionContext(BaseModel):
    query: str
    intent: str = ""
    query_embedding: Optional[List[float]] = None
    evidence: List[EvidenceItem] = Field(default_factory=list)
    assets: List[AssetItem] = Field(default_factory=list)
    data_assets: List[DataAssetItem] = Field(default_factory=list)
    trace_steps: List[TraceStep] = Field(default_factory=list)
    constraints: Optional[dict] = None


class RetrievalTrace(BaseModel):
    strategies: List[str]
    backends: List[str]
    latency_ms: int


class KnowledgePackage(BaseModel):
    query: str
    intent: str
    confidence: float
    evidence: List[EvidenceItem]
    missing_info: List[str]
    retrieval_trace: RetrievalTrace


class CapabilityRegistry(BaseModel):
    backend_id: str
    capabilities: List[str]


class RetrievalPlan(BaseModel):
    query: str
    plan: List[dict]
