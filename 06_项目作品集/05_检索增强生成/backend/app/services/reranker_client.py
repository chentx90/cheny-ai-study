"""Reranker client for third-party NewAPI/OpenAI-compatible rerank APIs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

import httpx

from ..config import settings


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


class APIRerankerService:
    def __init__(self) -> None:
        self.base_url = settings.reranker_base_url.rstrip("/")
        self.api_key = settings.resolved_reranker_api_key
        self.model = settings.reranker_model

    def is_available(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/rerank"):
            return self.base_url
        return f"{self.base_url}/rerank"

    async def rerank(self, query: str, documents: Iterable[str], top_k: int | None = None) -> List[RerankResult]:
        docs = [doc or "" for doc in documents]
        if not docs:
            return []
        if not self.is_available():
            return [RerankResult(index=i, score=0.0) for i in range(len(docs))]

        payload = {
            "model": self.model,
            "query": query,
            "documents": docs,
        }
        if top_k:
            payload["top_n"] = top_k

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
        return self._parse_results(response.json(), len(docs))

    @staticmethod
    def _parse_results(data: dict, doc_count: int) -> List[RerankResult]:
        raw_results = data.get("results") or data.get("data") or data.get("documents") or []
        parsed: list[RerankResult] = []
        for fallback_index, item in enumerate(raw_results):
            if not isinstance(item, dict):
                continue
            index = item.get("index", item.get("document_index", item.get("id", fallback_index)))
            score = item.get("relevance_score", item.get("score", item.get("similarity", 0.0)))
            try:
                index_int = int(index)
                score_float = float(score)
            except (TypeError, ValueError):
                continue
            if 0 <= index_int < doc_count:
                parsed.append(RerankResult(index=index_int, score=score_float))

        if not parsed:
            return [RerankResult(index=i, score=0.0) for i in range(doc_count)]

        seen = {item.index for item in parsed}
        parsed.extend(RerankResult(index=i, score=0.0) for i in range(doc_count) if i not in seen)
        return sorted(parsed, key=lambda item: item.score, reverse=True)


reranker_service = APIRerankerService()
