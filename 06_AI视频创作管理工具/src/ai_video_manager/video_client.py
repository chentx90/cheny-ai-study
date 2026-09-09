from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, OpenAI

from .openai_gateway import (
    _DEGRADED_HTTP_STATUSES,
    _KEY_ACCEPTED_HTTP_STATUSES,
    _REACHABLE_HTTP_STATUSES,
    alternate_insecure_base_url,
    build_http_client,
    build_sync_openai_client,
    gateway_site_root,
    is_vjimeng_gateway,
    normalize_openai_base_url,
)


@dataclass
class LangChainVideoClient:
    """星链云视频客户端：仅官方 demo /v1/video/*（无 /videos 降级）。"""

    provider: str
    base_url: str
    api_key: str
    timeout_seconds: float = 20
    poll_interval: float = 2.0
    max_retries: int = 1
    allow_insecure_ssl: bool = False
    _results: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    @property
    def normalized_base_url(self) -> str:
        return normalize_openai_base_url(self.provider, self.base_url)

    @property
    def site_root(self) -> str:
        return gateway_site_root(self.provider, self.base_url).rstrip("/")

    @property
    def uses_vjimeng_native_api(self) -> bool:
        return is_vjimeng_gateway(provider=self.provider, base_url=self.base_url)

    def test_connection(self) -> dict[str, object]:
        if not self.base_url.strip() or not self.api_key.strip():
            return {"ok": False, "detail": "需要 Base URL 和 API Key"}
        return self._probe_gateway(mode="test")

    def fetch_models(self) -> dict[str, object]:
        if not self.base_url.strip() or not self.api_key.strip():
            return {"ok": False, "models": [], "detail": "需要 Base URL 和 API Key"}

        probe = self._probe_gateway(mode="models")
        models = list(probe.get("models") or []) if probe.get("ok") else []
        source = "models.list"

        if not models:
            pricing_models, pricing_detail = self._fetch_models_from_pricing()
            if pricing_models:
                models = pricing_models
                source = "pricing"
            elif not probe.get("ok"):
                return {
                    "ok": False,
                    "models": [],
                    "detail": probe.get("detail") or pricing_detail or "无法获取模型列表",
                    "base_url": probe.get("base_url") or self.normalized_base_url,
                }

        if models:
            label = "定价页 /api/pricing" if source == "pricing" else "模型接口 /models"
            return {
                "ok": True,
                "models": models,
                "detail": f"共 {len(models)} 个视频模型（来自 {label}）",
                "base_url": probe.get("base_url") or self.normalized_base_url,
                "source": source,
            }

        if probe.get("ok"):
            return {
                "ok": True,
                "models": [],
                "detail": str(probe.get("detail") or "网关可达，但未返回可用模型 ID（可手动输入模型名）"),
                "base_url": probe.get("base_url") or self.normalized_base_url,
            }

        return {
            "ok": False,
            "models": [],
            "detail": probe.get("detail", "无法获取模型列表"),
            "base_url": probe.get("base_url") or self.normalized_base_url,
        }

    def _fetch_models_from_pricing(self) -> tuple[list[str], str]:
        root = gateway_site_root(self.provider, self.base_url).strip().rstrip("/")
        if not root:
            return [], "无法解析网关站点地址"
        url = f"{root}/api/pricing"
        headers = {"Authorization": f"Bearer {self.api_key.strip()}"}
        try:
            with build_http_client(timeout_seconds=self.timeout_seconds, allow_insecure_ssl=self.allow_insecure_ssl) as http:
                response = http.get(url, headers=headers)
                if response.status_code >= 400:
                    return [], f"定价页请求失败（HTTP {response.status_code}）"
                payload = response.json()
        except httpx.HTTPError as exc:
            return [], f"定价页请求失败：{exc}"
        except Exception as exc:  # pragma: no cover - network dependent
            return [], str(exc)

        return _parse_pricing_video_models(payload), ""

    async def create_generation(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        self._require_vjimeng_native()
        data = await self._post_vjimeng_generate(payload)
        task_id = str(
            data.get("id")
            or data.get("task_id")
            or data.get("taskId")
            or ""
        ).strip()
        if not task_id and isinstance(data.get("data"), dict):
            nested = data["data"]
            task_id = str(nested.get("id") or nested.get("task_id") or nested.get("taskId") or "").strip()
        if not task_id:
            raise RuntimeError(f"视频服务未返回任务 ID：{data}")
        self._results[task_id] = data
        return task_id, data

    async def get_generation(self, task_id: str) -> dict[str, Any]:
        self._require_vjimeng_native()
        data = await self._get_vjimeng_task(task_id)
        self._results[task_id] = data
        return data

    def _require_vjimeng_native(self) -> None:
        if self.uses_vjimeng_native_api:
            return
        raise RuntimeError(
            "HTTP 视频通道已移除 OpenAI /videos 旧协议（参考从未生效）。"
            "请将视频 Base URL 设为星链云地址（如 https://www.vjimeng.vip），"
            "仅走官方 demo：/v1/video/submit/generate 与 /v1/video/fetch。"
        )

    async def _post_vjimeng_generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """官方 demo：POST /v1/video/submit/generate。无其它回退。"""
        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json",
        }
        url = f"{self.site_root}/v1/video/submit/generate"
        timeout = max(float(self.timeout_seconds or 20), 180.0)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                verify=not self.allow_insecure_ssl,
            ) as http:
                response = await http.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"无法连接星链云视频提交接口：{exc}") from exc
        if response.status_code >= 400:
            text = (response.text or response.reason_phrase or "request failed")[:800]
            raise RuntimeError(f"HTTP {response.status_code}: {text}")
        return _unwrap_payload(response.json())

    async def _get_vjimeng_task(self, task_id: str) -> dict[str, Any]:
        """官方 demo：GET /v1/video/fetch/{taskId}。无其它回退。"""
        headers = {"Authorization": f"Bearer {self.api_key.strip()}"}
        url = f"{self.site_root}/v1/video/fetch/{task_id}"
        timeout = max(float(self.timeout_seconds or 20), 60.0)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                verify=not self.allow_insecure_ssl,
            ) as http:
                response = await http.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"无法连接星链云视频查询接口：{exc}") from exc
        if response.status_code >= 400:
            text = (response.text or response.reason_phrase or "request failed")[:800]
            raise RuntimeError(f"HTTP {response.status_code}: {text}")
        return _unwrap_payload(response.json())

    async def download_result(self, task_id: str, save_path: str) -> bool:
        from pathlib import Path

        data = self._results.get(task_id) or await self.get_generation(task_id)
        url = extract_video_url(data)
        if not url:
            raise RuntimeError(f"视频任务完成但未返回下载地址：{task_id}")

        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("data:"):
            path.write_bytes(decode_data_url(url))
            return True

        headers = {"Authorization": f"Bearer {self.api_key.strip()}"}
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            verify=not self.allow_insecure_ssl,
        ) as http:
            response = await http.get(url, headers=headers)
            response.raise_for_status()
            path.write_bytes(response.content)
        return True

    def _probe_gateway(self, *, mode: str) -> dict[str, object]:
        candidates = self._base_url_candidates()
        errors: list[str] = []
        for candidate in candidates:
            result = self._probe_single_base(candidate, mode=mode)
            if result.get("ok"):
                return result
            errors.append(str(result.get("detail") or "探测失败"))
        detail = "；".join(errors[:3])
        hint = _connection_hint(self.base_url, errors)
        if hint:
            detail = f"{detail}。{hint}" if detail else hint
        return {
            "ok": False,
            "detail": detail or "视频服务连接失败",
            "base_url": candidates[0] if candidates else self.normalized_base_url,
        }

    def _base_url_candidates(self) -> list[str]:
        primary = self.normalized_base_url
        candidates = [primary]
        alternate = alternate_insecure_base_url(primary)
        if alternate and alternate not in candidates:
            candidates.append(alternate)
        return candidates

    def _probe_single_base(self, base_url: str, *, mode: str) -> dict[str, object]:
        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json",
        }
        try:
            client = build_sync_openai_client(
                provider=self.provider,
                base_url=base_url,
                api_key=self.api_key,
                timeout_seconds=self.timeout_seconds,
                max_retries=self.max_retries,
                allow_insecure_ssl=self.allow_insecure_ssl,
            )
            response = client.models.list()
            models = _parse_models_payload({"data": [item.model_dump() for item in response.data or []]})
            if mode == "test":
                if models:
                    return {
                        "ok": True,
                        "detail": f"网关可达，模型列表可用（{len(models)} 个）",
                        "base_url": base_url,
                        "probe": "models.list",
                    }
                return {
                    "ok": True,
                    "detail": "网关可达（模型列表为空）",
                    "base_url": base_url,
                    "probe": "models.list",
                }
            return {"ok": True, "models": models, "base_url": base_url, "probe": "models.list"}
        except APIStatusError as exc:
            status = exc.status_code or 0
            if status == 401:
                return {"ok": False, "detail": "API Key 无效或未授权，请检查星链云控制台令牌"}
            if status == 403:
                confirmed = self._confirm_video_key(base_url, headers=headers, mode=mode)
                if confirmed is not None:
                    return confirmed
            if status in _REACHABLE_HTTP_STATUSES | _DEGRADED_HTTP_STATUSES:
                return _reachable_result(base_url, status, exc, mode=mode)
            return {"ok": False, "detail": f"{base_url} -> {_format_openai_error(exc)}"}
        except APIConnectionError:
            pass
        except Exception as exc:  # pragma: no cover - network dependent
            if _looks_like_ssl_error(exc):
                pass
            else:
                return {"ok": False, "detail": f"{base_url} -> {exc}"}

        return self._probe_with_http(base_url, headers=headers, mode=mode)

    def _probe_with_http(self, base_url: str, *, headers: dict[str, str], mode: str) -> dict[str, object]:
        site = gateway_site_root(self.provider, base_url).rstrip("/")
        submit_url = f"{site}/v1/video/submit/generate"
        attempts: list[tuple[str, str, dict[str, Any] | None]] = [
            (
                "POST",
                submit_url,
                {
                    "model": "__ping__",
                    "prompt": "__ping__",
                    "duration": 5,
                    "metadata": {"modeType": "text2video", "ratio": "16:9", "enableSound": "on"},
                },
            ),
            ("GET", f"{base_url}/models", None),
            ("GET", base_url, None),
        ]
        errors: list[str] = []
        with build_http_client(timeout_seconds=self.timeout_seconds, allow_insecure_ssl=self.allow_insecure_ssl) as http:
            for method, url, body in attempts:
                try:
                    response = http.request(method, url, headers=headers, json=body)
                except httpx.ConnectError as exc:
                    errors.append(f"{url} -> 连接失败：{exc}")
                    continue
                except httpx.HTTPError as exc:
                    errors.append(f"{url} -> {exc}")
                    continue

                status = response.status_code
                if status == 401:
                    return {"ok": False, "detail": "API Key 无效或未授权，请检查星链云控制台令牌"}
                if "/v1/video/submit/generate" in url and status in _KEY_ACCEPTED_HTTP_STATUSES:
                    return _video_key_ok_result(base_url, mode, probe=url, status=status)
                if status == 403 and url.endswith("/models"):
                    errors.append(f"{url} -> HTTP 403：模型列表无权限")
                    continue
                if status in _REACHABLE_HTTP_STATUSES:
                    if mode == "models" and method == "GET" and url.endswith("/models"):
                        models = _parse_models_payload(response.json() if response.content else {})
                        if models:
                            return {"ok": True, "models": models, "base_url": base_url, "probe": url}
                    if mode == "test":
                        return {
                            "ok": True,
                            "detail": f"网关可达（{method} {url} -> HTTP {status}）",
                            "base_url": base_url,
                            "probe": url,
                        }
                    if mode == "models":
                        models = _parse_models_payload(response.json() if response.content else {})
                        if models:
                            return {"ok": True, "models": models, "base_url": base_url, "probe": url}
                if status in _DEGRADED_HTTP_STATUSES:
                    return {
                        "ok": True,
                        "detail": f"网关可达但上游异常（HTTP {status}），请确认服务在线",
                        "base_url": base_url,
                        "probe": url,
                        "models": [],
                    }
                errors.append(f"{url} -> HTTP {status}: {response.text[:160]}")

        return {"ok": False, "detail": "；".join(errors[:3]) or "视频服务连接失败"}

    def _confirm_video_key(self, base_url: str, *, headers: dict[str, str], mode: str) -> dict[str, object] | None:
        site = gateway_site_root(self.provider, base_url).rstrip("/")
        url = f"{site}/v1/video/submit/generate"
        with build_http_client(timeout_seconds=self.timeout_seconds, allow_insecure_ssl=self.allow_insecure_ssl) as http:
            try:
                response = http.post(
                    url,
                    headers=headers,
                    json={
                        "model": "__ping__",
                        "prompt": "__ping__",
                        "duration": 5,
                        "metadata": {"modeType": "text2video", "ratio": "16:9", "enableSound": "on"},
                    },
                )
            except httpx.HTTPError:
                return None
            if response.status_code == 401:
                return {"ok": False, "detail": "API Key 无效或未授权，请检查星链云控制台令牌"}
            if response.status_code in _KEY_ACCEPTED_HTTP_STATUSES:
                return _video_key_ok_result(base_url, mode, probe=url, status=response.status_code)
        return None

    def _sync_client(self) -> OpenAI:
        return build_sync_openai_client(
            provider=self.provider,
            base_url=self.base_url,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            allow_insecure_ssl=self.allow_insecure_ssl,
        )


def build_video_client(config: dict[str, object]) -> LangChainVideoClient:
    return LangChainVideoClient(
        provider=str(config.get("videoProvider") or "").strip() or "custom",
        base_url=str(config.get("videoBaseUrl") or ""),
        api_key=str(config.get("videoApiKey") or ""),
        allow_insecure_ssl=bool(config.get("videoAllowInsecureSsl")),
    )


_VIDEO_MODEL_KEYWORDS = (
    "video",
    "sora",
    "kling",
    "veo",
    "seedance",
    "jimeng",
    "wan",
    "runway",
    "luma",
    "minimax",
    "sd2",
)


def _parse_pricing_video_models(payload: object) -> list[str]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    candidates: list[str] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        model_name = str(item.get("model_name") or item.get("model") or "").strip()
        if not model_name:
            continue
        if _is_video_pricing_model(item):
            candidates.append(model_name)

    if not candidates and rows and all(isinstance(item, dict) for item in rows):
        if all(_billing_mode(item) == "per-second" for item in rows):
            candidates = [
                str(item.get("model_name") or item.get("model") or "").strip()
                for item in rows
                if isinstance(item, dict)
            ]
            candidates = [name for name in candidates if name]

    deduped: list[str] = []
    seen: set[str] = set()
    for model_id in candidates:
        if model_id in seen:
            continue
        seen.add(model_id)
        deduped.append(model_id)
    return deduped


def _billing_mode(item: dict[str, Any]) -> str:
    return str(item.get("billing_mode") or "").replace("_", "-").lower()


def _is_video_pricing_model(item: dict[str, Any]) -> bool:
    if _billing_mode(item) in {"per-second", "percall", "per-call"}:
        return True
    name = str(item.get("model_name") or item.get("model") or "").lower()
    return any(keyword in name for keyword in _VIDEO_MODEL_KEYWORDS)


def _reachable_result(base_url: str, status: int, exc: APIStatusError, *, mode: str) -> dict[str, object]:
    if status in _DEGRADED_HTTP_STATUSES:
        detail = f"网关可达但上游异常（HTTP {status}），请确认服务在线"
    else:
        detail = f"网关可达（HTTP {status}）"
    if mode == "models":
        return {"ok": True, "models": [], "base_url": base_url, "detail": detail, "probe": "models.list"}
    return {"ok": True, "detail": detail, "base_url": base_url, "probe": "models.list"}


def _video_key_ok_result(base_url: str, mode: str, *, probe: str, status: int) -> dict[str, object]:
    detail = (
        "视频服务可用：Key 有效"
        + (f"（HTTP {status}）" if status != 200 else "")
        + "。若 /models 无权限，将自动从定价页拉取模型"
    )
    if mode == "models":
        return {"ok": True, "models": [], "base_url": base_url, "detail": detail, "probe": probe}
    return {"ok": True, "detail": detail, "base_url": base_url, "probe": probe}


def _connection_hint(base_url: str, errors: list[str]) -> str:
    joined = " ".join(errors).lower()
    hints: list[str] = []
    if "ssl" in joined or "certificate" in joined or "eof" in joined:
        hints.append("若网关使用自签证书，可勾选「跳过 SSL 验证」")
        if base_url.strip().startswith("https://"):
            hints.append("或尝试改用 http:// 地址")
    if "127.0.0.1" in base_url or "localhost" in base_url:
        hints.append("本地 Jimeng/NewAPI 网关通常填 http://127.0.0.1:5100 或 http://127.0.0.1:8000")
    if not hints:
        hints.append(f"实际请求地址：{normalize_openai_base_url('custom', base_url)}")
    return " ".join(hints)


def _looks_like_ssl_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "ssl" in text or "certificate" in text or "eof occurred in violation of protocol" in text


def _unwrap_payload(data: object) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    if isinstance(data, dict):
        return data
    raise RuntimeError(f"视频服务返回格式无效：{data}")


def _parse_models_payload(data: object) -> list[str]:
    models: list[str] = []
    if isinstance(data, dict):
        rows = data.get("data")
        if isinstance(rows, list):
            for item in rows:
                if isinstance(item, str) and item.strip():
                    models.append(item.strip())
                elif isinstance(item, dict):
                    model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
                    if model_id:
                        models.append(model_id)
        alt = data.get("models")
        if isinstance(alt, list):
            for item in alt:
                if isinstance(item, str) and item.strip():
                    models.append(item.strip())
                elif isinstance(item, dict):
                    model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
                    if model_id:
                        models.append(model_id)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str) and item.strip():
                models.append(item.strip())
            elif isinstance(item, dict):
                model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
                if model_id:
                    models.append(model_id)
    deduped: list[str] = []
    seen: set[str] = set()
    for model_id in models:
        if model_id in seen:
            continue
        seen.add(model_id)
        deduped.append(model_id)
    return deduped


def extract_video_url(data: dict[str, Any]) -> str:
    for key in ("url", "video_url", "videoUrl", "download_url", "downloadUrl", "result_url", "resultUrl"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        for key in ("url", "video_url", "videoUrl", "download_url", "downloadUrl", "result_url", "resultUrl"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    output = data.get("output")
    if isinstance(output, str) and output.strip():
        return output.strip()
    if isinstance(output, dict):
        nested = extract_video_url(output)
        if nested:
            return nested
    if isinstance(output, list):
        for item in output:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                nested = extract_video_url(item)
                if nested:
                    return nested
    raw = data.get("data")
    if isinstance(raw, dict):
        return extract_video_url(raw)
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return extract_video_url(raw[0])
    return ""


def decode_data_url(url: str) -> bytes:
    if not url.startswith("data:"):
        raise ValueError("Invalid data URL")
    header, encoded = url.split(",", 1)
    if ";base64" not in header:
        raise ValueError("Only base64 data URLs are supported for video results")
    return base64.b64decode(encoded)


def map_generation_status(data: dict[str, Any]) -> str:
    status = str(data.get("status") or data.get("state") or "").strip().lower()
    if status in {"completed", "succeeded", "success", "done"}:
        return "completed"
    if status in {"failed", "error", "cancelled", "canceled", "failure"}:
        return "failed"
    if status in {"pending", "queued", "processing", "running", "in_progress"}:
        return "processing"
    if extract_video_url(data):
        return "completed"
    return "processing"


def _format_openai_error(exc: APIStatusError) -> str:
    body = exc.message or str(exc)
    status = exc.status_code or 0
    text = body[:500]
    lower = text.lower()
    if status == 403 and ("blocked" in lower or "cloudflare" in lower or "just a moment" in lower):
        return (
            f"HTTP 403: 请求被网关拦截（{text}）。"
            "常见原因：参考素材未先上传云空间、Base URL 或 API Key 无效。"
            "可先无参考重试确认连通；有远端 task id 时用「追回」拉结果，勿盲目重复重试。"
        )
    if status:
        return f"HTTP {status}: {text}"
    return text
