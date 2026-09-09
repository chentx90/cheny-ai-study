"""Evaluation endpoints for retrieval quality checks."""

from fastapi import APIRouter

from ..evaluation.eval_runner import run_evaluation_sync

router = APIRouter()


@router.post("/evaluation/run")
async def run_evaluation():
    results, _metrics = await run_evaluation_sync()
    return results


@router.get("/evaluation/metrics")
async def get_metrics():
    _results, metrics = await run_evaluation_sync()
    return {
        "total": metrics["total"],
        "hit1": metrics["hit@1"],
        "hit3": metrics["hit@3"],
        "hit5": metrics["hit@5"],
        "mrr": metrics["mrr"],
        "avg_latency": metrics["avg_latency"],
        "report_path": metrics.get("report_path"),
    }
