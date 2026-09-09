from __future__ import annotations

import httpx
from openai import AsyncOpenAI, OpenAI

_OPENAI_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/models",
    "/videos/generations",
    "/video/generations",
    "/videos",
)

_REACHABLE_HTTP_STATUSES = {200, 400, 404, 405, 422}
_KEY_ACCEPTED_HTTP_STATUSES = {200, 400, 403, 404, 405, 422}
_DEGRADED_HTTP_STATUSES = {502, 503, 504}


def normalize_openai_base_url(provider: str, base_url: str) -> str:
    """Normalize OpenAI-compatible gateway base URLs for LangChain / OpenAI SDK clients."""
    base = base_url.strip().rstrip("/")
    if not base:
        return base

    changed = True
    while changed:
        changed = False
        for suffix in _OPENAI_ENDPOINT_SUFFIXES:
            if base.endswith(suffix):
                base = base[: -len(suffix)].rstrip("/")
                changed = True
                break

    if base.endswith("/v1"):
        return base

    provider_key = provider.lower()
    if provider_key in {"custom", "newapi", "openai"} or "newapi" in provider_key or "openai" in provider_key:
        return f"{base}/v1"
    return f"{base}/v1"


def gateway_site_root(provider: str, base_url: str) -> str:
    """Site origin for New API console endpoints such as /api/pricing."""
    normalized = normalize_openai_base_url(provider, base_url).rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[: -len("/v1")]
    return normalized


def is_vjimeng_gateway(*, provider: str = "", base_url: str = "") -> bool:
    """星链云 / vjimeng 使用专有 /v1/video/*，不是 OpenAI /videos。"""
    host = f"{provider} {base_url}".lower()
    return "vjimeng" in host


def alternate_insecure_base_url(base_url: str) -> str | None:
    normalized = base_url.strip().rstrip("/")
    if normalized.startswith("https://"):
        return f"http://{normalized[len('https://'):]}"
    return None


def build_http_client(*, timeout_seconds: float, allow_insecure_ssl: bool) -> httpx.Client:
    return httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        verify=not allow_insecure_ssl,
    )


def build_async_http_client(*, timeout_seconds: float, allow_insecure_ssl: bool) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
        verify=not allow_insecure_ssl,
    )


def build_sync_openai_client(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    timeout_seconds: float = 60,
    max_retries: int = 3,
    allow_insecure_ssl: bool = False,
) -> OpenAI:
    return OpenAI(
        api_key=api_key.strip(),
        base_url=normalize_openai_base_url(provider, base_url),
        timeout=timeout_seconds,
        max_retries=max_retries,
        http_client=build_http_client(timeout_seconds=timeout_seconds, allow_insecure_ssl=allow_insecure_ssl),
    )


def build_async_openai_client(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    timeout_seconds: float = 60,
    max_retries: int = 3,
    allow_insecure_ssl: bool = False,
) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key.strip(),
        base_url=normalize_openai_base_url(provider, base_url),
        timeout=timeout_seconds,
        max_retries=max_retries,
        http_client=build_async_http_client(timeout_seconds=timeout_seconds, allow_insecure_ssl=allow_insecure_ssl),
    )
