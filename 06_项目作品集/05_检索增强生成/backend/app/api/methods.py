from fastapi import APIRouter
from ..core.method_loader import get_available_methods, load_method, MethodLoadError
from ..core.schemas import RetrievalMethod

router = APIRouter()


@router.get("/methods")
async def list_methods():
    methods = get_available_methods()
    return {
        "methods": [
            {"method_id": mid, "description": desc}
            for mid, desc in methods.items()
        ]
    }


@router.get("/methods/{method_id}")
async def get_method(method_id: str):
    try:
        method = load_method(method_id)
    except MethodLoadError:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Method not found: {method_id}")
    return {
        "method_id": method.method_id,
        "description": method.description,
        "steps": [step.model_dump() for step in method.steps]
    }


@router.get("/operators")
async def list_operators():
    from ..operators import operator_registry
    return {
        "operators": list(operator_registry.keys())
    }