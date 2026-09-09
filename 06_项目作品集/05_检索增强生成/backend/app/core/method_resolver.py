from typing import Optional


MODE_METHOD_MAP = {
    "fast": "document_vector_v1",
    "balanced": "document_context_v1",
    "reliable": "equipment_troubleshooting_v1",
    "deep": "data_asset_lookup_v1",
}


def detect_intent(query: str) -> tuple[str, float]:
    if any(kw in query for kw in ["怎么算", "公式", "计算"]):
        return "calculation", 0.85
    if any(kw in query for kw in ["怎么", "如何", "怎样"]):
        return "troubleshooting", 0.9
    if any(kw in query for kw in ["什么", "是什么", "定义"]):
        return "definition", 0.7
    return "general", 0.5


def resolve_method(method_id: Optional[str], mode: Optional[str], query: str) -> str:
    if method_id:
        return method_id
    
    if mode and mode in MODE_METHOD_MAP:
        return MODE_METHOD_MAP[mode]
    
    intent, _ = detect_intent(query)
    
    if intent == "troubleshooting":
        return "equipment_troubleshooting_v1"
    
    if intent == "calculation":
        return "data_asset_lookup_v1"
    
    if intent == "definition":
        return "document_vector_v1"
    
    return "document_vector_v1"