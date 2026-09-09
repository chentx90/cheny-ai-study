"""Evaluation runner for retrieval quality checks."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx


ROOT_DIR = Path(__file__).resolve().parents[3]
CASES_PATH = ROOT_DIR / "evaluation" / "cases" / "retrieval_cases.json"
REPORT_DIR = ROOT_DIR / "output" / "evaluation"
BACKEND_URL = os.getenv("EVALUATION_BACKEND_URL", "http://127.0.0.1:8000/api")


def load_cases(path: Path = CASES_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Evaluation cases file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _lower(value: Any) -> str:
    return str(value or "").casefold()


def _contains_any(text: str, expected: Iterable[Any]) -> Optional[str]:
    haystack = _lower(text)
    for item in expected:
        needle = _lower(item)
        if needle and needle in haystack:
            return str(item)
    return None


def _physical_match(physical_context: Dict[str, Any], case: Dict[str, Any]) -> Optional[str]:
    checks: List[Tuple[str, str]] = [
        ("expected_pages", "page"),
        ("expected_slides", "slide"),
        ("expected_rows", "row"),
        ("expected_sheets", "sheet"),
    ]
    for case_key, context_key in checks:
        expected_values = {_lower(value) for value in _as_list(case.get(case_key))}
        if expected_values and _lower(physical_context.get(context_key)) in expected_values:
            return f"{context_key}:{physical_context.get(context_key)}"

    for expected in _as_list(case.get("expected_physical_context")):
        if not isinstance(expected, dict):
            continue
        if all(_lower(physical_context.get(key)) == _lower(value) for key, value in expected.items()):
            return f"physical_context:{expected}"
    return None


def _evidence_match(case: Dict[str, Any], evidence: Dict[str, Any]) -> Optional[str]:
    chunk_id = str(evidence.get("chunk_id") or "")
    document_id = str(evidence.get("document_id") or "")
    section_path = str(evidence.get("section_path") or "")
    title_context = str(evidence.get("title_context") or "")
    content = str(evidence.get("content") or "")
    physical_context = evidence.get("physical_context") or {}
    has_precise_location = any(
        _as_list(case.get(key))
        for key in (
            "expected_locations",
            "expected_pages",
            "expected_slides",
            "expected_rows",
            "expected_sheets",
            "expected_physical_context",
        )
    )

    expected_chunk_ids = {str(item) for item in _as_list(case.get("expected_chunk_ids"))}
    if expected_chunk_ids and chunk_id in expected_chunk_ids:
        return f"chunk_id:{chunk_id}"

    expected_document_ids = {str(item) for item in _as_list(case.get("expected_document_ids"))}
    if expected_document_ids and document_id in expected_document_ids:
        return f"document_id:{document_id}"

    location_match = _contains_any(section_path, _as_list(case.get("expected_locations")))
    if location_match:
        return f"location:{location_match}"

    physical_reason = _physical_match(physical_context, case)
    if physical_reason:
        return physical_reason

    keyword_match = _contains_any(content, _as_list(case.get("expected_keywords")))
    if keyword_match:
        return f"keyword:{keyword_match}"

    if not has_precise_location:
        source_match = _contains_any(f"{title_context}\n{section_path}", _as_list(case.get("expected_sources")))
        if source_match:
            return f"source:{source_match}"

    return None


def _asset_match(case: Dict[str, Any], asset: Dict[str, Any]) -> Optional[str]:
    asset_id = str(asset.get("asset_id") or "")
    expected_asset_ids = {str(item) for item in _as_list(case.get("expected_asset_ids"))}
    if expected_asset_ids and asset_id in expected_asset_ids:
        return f"asset_id:{asset_id}"

    text = "\n".join(
        str(asset.get(key) or "")
        for key in ("caption", "ocr_text", "description", "asset_url", "asset_type")
    )
    keyword_match = _contains_any(text, _as_list(case.get("expected_asset_keywords")))
    if keyword_match:
        return f"asset_keyword:{keyword_match}"
    return None


def _data_asset_match(case: Dict[str, Any], data_asset: Dict[str, Any]) -> Optional[str]:
    names = {str(item) for item in _as_list(case.get("expected_data_asset_names"))}
    name = str(data_asset.get("name") or "")
    if names and name in names:
        return f"data_asset:{name}"

    text = "\n".join(
        str(data_asset.get(key) or "")
        for key in ("name", "description", "parent_name", "formula", "related_table")
    )
    keyword_match = _contains_any(text, _as_list(case.get("expected_data_asset_keywords")))
    if keyword_match:
        return f"data_asset_keyword:{keyword_match}"
    return None


def _first_match(case: Dict[str, Any], response: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
    evidence = response.get("evidence") or []
    for index, item in enumerate(evidence, start=1):
        reason = _evidence_match(case, item)
        if reason:
            return index, reason

    data_assets = response.get("data_assets") or []
    for index, item in enumerate(data_assets, start=1):
        reason = _data_asset_match(case, item)
        if reason:
            return index, reason

    assets = response.get("assets") or []
    for index, item in enumerate(assets, start=1):
        reason = _asset_match(case, item)
        if reason:
            return index, reason

    if not _case_has_expectation(case) and evidence:
        return 1, "non_empty_evidence"
    return None, None


def _case_has_expectation(case: Dict[str, Any]) -> bool:
    keys = [
        "expected_chunk_ids",
        "expected_document_ids",
        "expected_sources",
        "expected_locations",
        "expected_pages",
        "expected_slides",
        "expected_rows",
        "expected_sheets",
        "expected_physical_context",
        "expected_keywords",
        "expected_asset_ids",
        "expected_asset_keywords",
        "expected_data_asset_names",
        "expected_data_asset_keywords",
    ]
    return any(_as_list(case.get(key)) for key in keys)


def _constraints_for(case: Dict[str, Any]) -> Dict[str, Any]:
    constraints = dict(case.get("constraints") or {})
    if case.get("business_domain") and "business_domain" not in constraints:
        constraints["business_domain"] = case["business_domain"]
    return constraints


def _preview_response(response: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
    preview = []
    for item in (response.get("evidence") or [])[:limit]:
        preview.append(
            {
                "chunk_id": item.get("chunk_id"),
                "title_context": item.get("title_context"),
                "section_path": item.get("section_path"),
                "score": item.get("score"),
                "physical_context": item.get("physical_context"),
            }
        )
    return preview


async def evaluate_case(client: httpx.AsyncClient, case: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "query": case["query"],
        "method": case.get("method"),
        "mode": case.get("mode", "balanced"),
        "constraints": _constraints_for(case),
    }
    response = await client.post(f"{BACKEND_URL}/retrieve", json=payload)
    response.raise_for_status()
    data = response.json()

    rank, reason = _first_match(case, data)
    latency_ms = data.get("retrieval_trace", {}).get("latency_ms", 0)

    return {
        "case_id": case.get("case_id"),
        "query": case["query"],
        "hit1": bool(rank and rank <= 1),
        "hit3": bool(rank and rank <= 3),
        "hit5": bool(rank and rank <= 5),
        "mrr": (1.0 / rank) if rank else 0.0,
        "matched_rank": rank,
        "matched_reason": reason,
        "latency_ms": latency_ms,
        "top_evidence": _preview_response(data),
    }


def compute_metrics(results: List[Dict[str, Any]]) -> Dict[str, float]:
    total = len(results)
    if not total:
        return {
            "total": 0,
            "hit@1": 0,
            "hit@3": 0,
            "hit@5": 0,
            "mrr": 0,
            "avg_latency": 0,
        }

    return {
        "total": total,
        "hit@1": sum(1 for result in results if result["hit1"]) / total,
        "hit@3": sum(1 for result in results if result["hit3"]) / total,
        "hit@5": sum(1 for result in results if result["hit5"]) / total,
        "mrr": sum(float(result["mrr"]) for result in results) / total,
        "avg_latency": sum(int(result["latency_ms"]) for result in results) / total,
    }


def save_report(results: List[Dict[str, Any]], metrics: Dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "backend_url": BACKEND_URL,
        "cases_path": str(CASES_PATH),
        "metrics": metrics,
        "results": results,
    }
    latest_path = REPORT_DIR / "latest_retrieval_eval.json"
    dated_path = REPORT_DIR / f"retrieval_eval_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    latest_path.write_text(payload, encoding="utf-8")
    dated_path.write_text(payload, encoding="utf-8")
    return latest_path


async def run_evaluation_sync() -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cases = load_cases()
    results = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for case in cases:
            results.append(await evaluate_case(client, case))

    metrics = compute_metrics(results)
    report_path = save_report(results, metrics)
    metrics["report_path"] = str(report_path)
    return results, metrics
