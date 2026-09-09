import time

from fastapi import APIRouter, HTTPException

from ..core.execution_engine import ExecutionEngine
from ..core.method_loader import MethodLoadError, load_method
from ..core.method_resolver import detect_intent, resolve_method
from ..core.planner import create_retrieval_plan
from ..core.registry import registry_service
from ..core.schemas import ExecutionContext, KnowledgePackage, RetrievalTrace, RetrieveRequest
from ..operators import operator_registry

router = APIRouter()


@router.post("/retrieve")
async def retrieve(request: RetrieveRequest):
    start_time = time.time()
    method_id = resolve_method(request.method, request.mode.value if request.mode else None, request.query)
    intent, confidence = detect_intent(request.query)

    try:
        method = load_method(method_id)
    except MethodLoadError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    context = ExecutionContext(
        query=request.query,
        intent=intent,
        constraints=request.constraints,
    )
    engine = ExecutionEngine(operator_registry, registry_service)
    context = await engine.execute(method, context)

    trace_steps = [step.model_dump() for step in context.trace_steps]
    backends = sorted({step.backend for step in context.trace_steps if step.backend and step.backend != "local"})
    strategies = [step.operator for step in context.trace_steps if step.operator != "execution_engine"]
    latency_ms = int((time.time() - start_time) * 1000)

    return {
        **KnowledgePackage(
            query=request.query,
            intent=intent,
            confidence=confidence,
            evidence=context.evidence,
            missing_info=[],
            retrieval_trace=RetrievalTrace(
                strategies=strategies,
                backends=backends,
                latency_ms=latency_ms,
            ),
        ).model_dump(),
        "method": method_id,
        "assets": context.assets,
        "data_assets": context.data_assets,
        "retrieval_trace": {
            "latency_ms": latency_ms,
            "strategies": strategies,
            "backends": backends,
            "steps": trace_steps,
        },
    }


@router.post("/retrieve/plan")
async def get_retrieval_plan(request: RetrieveRequest):
    return create_retrieval_plan(request.query, request.mode)
