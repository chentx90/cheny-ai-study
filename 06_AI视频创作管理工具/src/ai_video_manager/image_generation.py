"""Direct OpenAI-compatible image generation."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urljoin

import httpx


class ImageGenerationError(RuntimeError):
    """Raised when the image gateway rejects or fails a request."""


def image_config_ready(config: dict[str, object]) -> bool:
    provider = str(config.get("imageProvider") or "").strip().lower()
    if provider in {"", "off", "none", "disabled"}:
        return False
    return image_gateway_ready(config)


def image_gateway_ready(config: dict[str, object]) -> bool:
    """Backend direct `/v1/images/generations` still needs Base URL + API Key."""
    resolved = resolve_image_gateway_config(config)
    base_url = str(resolved.get("imageBaseUrl") or "").strip()
    api_key = str(resolved.get("imageApiKey") or "").strip()
    return bool(base_url and api_key)


def resolve_image_gateway_config(config: dict[str, object]) -> dict[str, object]:
    """Resolve the image gateway without mixing credentials from different explicit gateways."""
    resolved = dict(config)
    image_base = str(config.get("imageBaseUrl") or "").strip()
    image_key = str(config.get("imageApiKey") or "").strip()
    use_llm = bool(config.get("imageUseLlmCredentials", True))
    if not image_base and not image_key and use_llm:
        resolved["imageBaseUrl"] = str(config.get("llmBaseUrl") or "").strip()
        resolved["imageApiKey"] = str(config.get("llmApiKey") or "").strip()
        resolved["imageCredentialSource"] = "llm"
    else:
        resolved["imageCredentialSource"] = "image"
    return resolved


def normalize_image_base_url(raw: str) -> str:
    value = str(raw or "").strip().rstrip("/")
    if not value:
        return ""
    lower = value.lower()
    if lower.endswith("/v1") or "/v1/" in lower:
        return value
    return f"{value}/v1"


class OpenAIImageClient:
    """Call `{base}/images/generations` like NewAPI / OpenAI image gateways."""

    def __init__(self, config: dict[str, object], *, timeout: float = 180.0) -> None:
        if not image_gateway_ready(config):
            raise ImageGenerationError("图片网关未配置：需要 Base URL 与 API Key")
        self.config = resolve_image_gateway_config(config)
        self.base = normalize_image_base_url(str(self.config.get("imageBaseUrl") or ""))
        self.api_key = str(self.config.get("imageApiKey") or "").strip()
        self.model = str(self.config.get("imageModel") or "").strip()
        self.size = str(self.config.get("imageOutputSize") or "1024x1024").strip() or "1024x1024"
        self.timeout = timeout

    def test_connection(self) -> dict[str, object]:
        """Probe gateway: prefer models list."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        models_url = urljoin(self.base.rstrip("/") + "/", "models")
        try:
            with httpx.Client(timeout=min(self.timeout, 30.0)) as client:
                response = client.get(models_url, headers=headers)
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": f"无法连接图片网关：{exc}", "base_url": self.base}
        if response.status_code < 400:
            data = _safe_json(response)
            if not isinstance(data, dict) or not data:
                return {
                    "ok": False,
                    "detail": "图片网关返回的不是 JSON API；请勿填写控制台或管理页面地址",
                    "base_url": self.base,
                }
            return {
                "ok": True,
                "detail": "图片网关可达",
                "base_url": self.base,
                "model": self.model or "（在生图页选择）",
            }
        if response.status_code in {404, 405}:
            return {
                "ok": True,
                "detail": "图片网关已配置（未提供 /models，将在生成时验证）",
                "base_url": self.base,
                "model": self.model or "（在生图页选择）",
            }
        return {
            "ok": False,
            "detail": _error_detail(response, "图片网关探测失败"),
            "base_url": self.base,
        }

    def fetch_models(self) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        models_url = urljoin(self.base.rstrip("/") + "/", "models")
        try:
            with httpx.Client(timeout=min(self.timeout, 30.0)) as client:
                response = client.get(models_url, headers=headers)
        except httpx.HTTPError as exc:
            return {"ok": False, "models": [], "detail": f"无法获取模型列表：{exc}", "base_url": self.base}
        if response.status_code >= 400:
            return {
                "ok": False,
                "models": [],
                "detail": _error_detail(response, "获取模型列表失败"),
                "base_url": self.base,
            }
        data = _safe_json(response)
        if not isinstance(data, dict) or not data:
            return {
                "ok": False,
                "models": [],
                "detail": "模型接口返回的不是 JSON API；请检查 Base URL",
                "base_url": self.base,
            }
        models: list[str] = []
        items = data.get("data") if isinstance(data, dict) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    models.append(str(item["id"]))
                elif isinstance(item, str) and item.strip():
                    models.append(item.strip())
        return {
            "ok": True,
            "models": models,
            "detail": f"已获取 {len(models)} 个模型" if models else "网关未返回模型列表",
            "base_url": self.base,
        }

    def generate(self, prompt: str, *, n: int = 1, model: str | None = None, size: str | None = None) -> list[bytes]:
        clean = str(prompt or "").strip()
        if not clean:
            raise ImageGenerationError("提示词不能为空")
        resolved_model = str(model or self.model or "").strip()
        if not resolved_model:
            raise ImageGenerationError("请选择或填写生图模型")
        resolved_size = str(size or self.size or "1024x1024").strip() or "1024x1024"
        count = max(1, min(4, int(n or 1)))
        url = urljoin(self.base.rstrip("/") + "/", "images/generations")
        payload: dict[str, Any] = {
            "model": resolved_model,
            "prompt": clean,
            "n": count,
            "size": resolved_size,
            "response_format": "b64_json",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload, headers=headers)
                if response.status_code >= 400 and "response_format" in (response.text or "").lower():
                    payload.pop("response_format", None)
                    response = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ImageGenerationError(f"无法连接图片网关 {self.base}：{exc}") from exc
        if response.status_code >= 400:
            raise ImageGenerationError(_error_detail(response, "生图请求失败"))
        content_type = str(response.headers.get("content-type") or "").lower()
        if content_type.startswith("image/") and response.content:
            return [response.content]
        data = _safe_json(response)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            raise ImageGenerationError(f"网关未返回图片数据{_response_summary(data, response)}")
        images: list[bytes] = []
        for item in items:
            content = _coerce_image_item(item)
            if content:
                images.append(content)
        if not images:
            raise ImageGenerationError("网关返回的图片无法解析（需要 b64_json 或 url）")
        return images


def build_image_client(config: dict[str, object]) -> OpenAIImageClient:
    return OpenAIImageClient(config)


def _coerce_image_item(item: Any) -> bytes | None:
    if not isinstance(item, dict):
        return None
    b64 = str(item.get("b64_json") or item.get("base64") or "").strip()
    if b64:
        return base64.b64decode(b64)
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    if url.startswith("data:"):
        _, _, payload = url.partition(",")
        return base64.b64decode(payload) if payload else None
    with httpx.Client(timeout=60.0) as client:
        response = client.get(url)
    if response.status_code >= 400 or not response.content:
        return None
    return response.content


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}


def _error_detail(response: httpx.Response, prefix: str) -> str:
    data = _safe_json(response)
    message = ""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            message = str(err.get("message") or err.get("code") or "").strip()
        else:
            message = str(err or data.get("message") or data.get("detail") or "").strip()
    if not message:
        message = (response.text or "").strip()[:200]
    return f"{prefix}：HTTP {response.status_code}" + (f" — {message}" if message else "")


def _response_summary(data: Any, response: httpx.Response | None = None) -> str:
    content_type = str(response.headers.get("content-type") or "未知") if response else "未知"
    raw = (response.text or "").strip()[:300] if response else ""
    if not isinstance(data, dict):
        return f"（Content-Type：{content_type}；响应类型：{type(data).__name__}" + (f"；正文：{raw}" if raw else "") + "）"
    message = ""
    for key in ("error", "message", "detail", "msg"):
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("message") or value.get("detail") or value.get("code")
        if value:
            message = str(value).strip()[:300]
            break
    keys = ", ".join(sorted(str(key) for key in data.keys())) or "无"
    return (
        f"（Content-Type：{content_type}；响应字段：{keys}"
        + (f"；消息：{message}" if message else "")
        + (f"；正文：{raw}" if raw and not message else "")
        + "）"
    )
