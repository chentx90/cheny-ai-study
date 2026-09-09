"""系统级端点：健康检查、能力声明、策略查询。
原 debug.py 改名，/documents 已迁入 /knowledge/documents，此处删除。
"""
from fastapi import APIRouter, Request
from ..core.registry import registry_service

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    db = getattr(request.app.state, "db", None)
    ingestion = getattr(request.app.state, "ingestion_service", None)
    return {
        "status": "ok",
        "service": "rag-backend",
        "postgres": "connected" if db else "disconnected",
        "ingestion_service": "initialized" if ingestion else "not_initialized",
    }


@router.get("/capabilities")
async def get_capabilities():
    return {"backends": registry_service.get_all_registry()}


@router.get("/strategies")
async def get_strategies():
    from ..core.planner import STRATEGY_CATALOG
    return {"strategies": [
        {"name": k, "capability": v.capability, "backend_id": v.backend_id}
        for k, v in STRATEGY_CATALOG.items()
    ]}
