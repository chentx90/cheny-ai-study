"""Embedding client backed only by third-party OpenAI-compatible APIs."""
from __future__ import annotations

from typing import Iterable, List

import httpx

from ..config import settings


class EmbeddingConfigError(RuntimeError):
    pass


class APIEmbeddingService:
    def __init__(self) -> None:
        self.model = settings.embedding_model
        self.base_url = settings.embedding_base_url.rstrip("/")
        self.api_key = settings.resolved_embedding_api_key
        self.dimension = settings.embedding_dimension

    def is_available(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    async def embed(self, text: str) -> List[float]:
        vectors = await self.embed_many([text])
        return vectors[0]

    async def embed_many(self, texts: Iterable[str]) -> List[List[float]]:
        inputs = [text or "" for text in texts]
        if not inputs:
            return []
        if not self.is_available():
            raise EmbeddingConfigError(
                "Embedding API is not configured. Set EMBEDDING_API_KEY or LLM_API_KEY in backend/.env."
            )

        payload = {"model": self.model, "input": inputs}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{self.base_url}/embeddings", headers=headers, json=payload)
            response.raise_for_status()
        data = response.json().get("data") or []
        vectors = [item.get("embedding") for item in sorted(data, key=lambda item: item.get("index", 0))]
        if len(vectors) != len(inputs) or any(not isinstance(vector, list) for vector in vectors):
            raise RuntimeError("Embedding API returned an invalid response.")
        for vector in vectors:
            if len(vector) != self.dimension:
                raise RuntimeError(
                    f"Embedding dimension mismatch: expected {self.dimension}, got {len(vector)}. "
                    "Update EMBEDDING_MODEL/EMBEDDING_DIMENSION or database vector dimension."
                )
        return vectors


embedding_service = APIEmbeddingService()
