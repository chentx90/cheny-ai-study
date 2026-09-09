from fastapi import APIRouter
from ..core.registry import registry_service

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "rag-backend"}


@router.get("/capabilities")
async def get_capabilities():
    return {"backends": registry_service.get_all_registry()}


@router.get("/strategies")
async def get_strategies():
    from ..core.planner import STRATEGY_CATALOG
    return {
        "strategies": [
            {"name": k, "capability": v.capability, "backend_id": v.backend_id}
            for k, v in STRATEGY_CATALOG.items()
        ]
    }