from typing import Any, Dict, List, Optional


def hit_at_k(rank: Optional[int], k: int) -> bool:
    return bool(rank and rank <= k)


def reciprocal_rank(rank: Optional[int]) -> float:
    return 1.0 / rank if rank else 0.0


def compute_metrics(results: List[Dict[str, Any]]) -> Dict[str, float]:
    if not results:
        return {"total": 0, "hit@1": 0, "hit@3": 0, "hit@5": 0, "mrr": 0, "avg_latency": 0}

    total = len(results)
    return {
        "total": total,
        "hit@1": sum(1 for item in results if item.get("hit1")) / total,
        "hit@3": sum(1 for item in results if item.get("hit3")) / total,
        "hit@5": sum(1 for item in results if item.get("hit5")) / total,
        "mrr": sum(float(item.get("mrr") or 0) for item in results) / total,
        "avg_latency": sum(int(item.get("latency_ms") or 0) for item in results) / total,
    }


def evaluate_rank(case_id: str, query: str, rank: Optional[int], reason: Optional[str], latency_ms: int) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "query": query,
        "hit1": hit_at_k(rank, 1),
        "hit3": hit_at_k(rank, 3),
        "hit5": hit_at_k(rank, 5),
        "mrr": reciprocal_rank(rank),
        "matched_rank": rank,
        "matched_reason": reason,
        "latency_ms": latency_ms,
    }
