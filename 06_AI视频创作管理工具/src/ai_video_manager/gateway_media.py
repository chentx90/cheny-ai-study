"""Upload local media for HTTP video gateways.

星链云 / vjimeng 唯一上传途径：OSS 直传 https://oss.vjimeng.vip
  1. POST /api/direct-upload/sign
  2. PUT file to signed OSS URL
  3. POST /api/direct-upload/complete
  4. Return stable https URL (strip temporary x-oss-signature query)

禁止：New API /v1/files（未实现）、base64、本机签名公网链。
"""

from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Callable

import httpx

from .openai_gateway import build_http_client, normalize_openai_base_url

Uploader = Callable[[Path, str], str]

DEFAULT_VJIMENG_OSS_BASE = "https://oss.vjimeng.vip"
MAX_DIRECT_UPLOAD_BYTES = 100 * 1024 * 1024


def stabilize_oss_public_url(url: str) -> str:
    """Prefer long-lived public object URL; strip temporary OSS signature query."""
    clean = str(url or "").strip()
    if not clean.startswith(("http://", "https://")):
        return clean
    lower = clean.lower()
    if "x-oss-signature" in lower or "x-oss-credential" in lower or "files.vjimeng.vip" in lower:
        return clean.split("?", 1)[0]
    return clean


def verify_http_refs_reachable(
    urls: list[str] | tuple[str, ...],
    *,
    timeout_seconds: float = 20.0,
    allow_insecure_ssl: bool = False,
    min_bytes: int = 64,
) -> list[dict[str, object]]:
    """Prove each https ref is publicly fetchable before video submit.

    Uses Range GET (first 2KB) so large video/audio refs stay cheap.
    asset:// refs are skipped (not HTTP-fetchable from this host).
    """
    results: list[dict[str, object]] = []
    checked = 0
    with build_http_client(timeout_seconds=timeout_seconds, allow_insecure_ssl=allow_insecure_ssl) as http:
        for raw in urls:
            url = str(raw or "").strip()
            if not url:
                continue
            if url.startswith("asset://"):
                results.append({"url": url, "ok": True, "skipped": "asset://"})
                continue
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"出站前校验失败：非 http(s) 引用 {url[:120]}")
            checked += 1
            try:
                response = http.get(url, headers={"Range": "bytes=0-2047"})
            except httpx.HTTPError as exc:
                raise ValueError(f"出站前校验失败：无法请求参考素材 {url[:160]}：{exc}") from exc
            body = response.content or b""
            ctype = str(response.headers.get("content-type") or "").split(";")[0].strip()
            ok_status = response.status_code in {200, 206}
            entry: dict[str, object] = {
                "url": url,
                "ok": ok_status and len(body) >= min_bytes,
                "status": response.status_code,
                "bytes": len(body),
                "content_type": ctype,
            }
            results.append(entry)
            if not ok_status:
                raise ValueError(
                    f"出站前校验失败：参考素材 HTTP {response.status_code}（期望 200/206）：{url[:160]}"
                )
            if len(body) < min_bytes:
                raise ValueError(
                    f"出站前校验失败：参考素材过小（{len(body)} bytes）：{url[:160]}"
                )
    if checked <= 0 and not any(str(r.get("url") or "").startswith("asset://") for r in results):
        raise ValueError("出站前校验失败：没有任何可校验的 https 参考素材")
    return results


def extract_gateway_file_url(payload: object) -> str:
    """Pull a publicly usable URL from heterogeneous gateway file responses."""
    if not isinstance(payload, dict):
        return ""
    candidates: list[object] = [payload]
    for key in ("data", "file", "result", "info"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
        elif isinstance(nested, list):
            candidates.extend(item for item in nested if isinstance(item, dict))

    url_keys = (
        "url",
        "public_url",
        "publicUrl",
        "download_url",
        "downloadUrl",
        "file_url",
        "fileUrl",
        "cdn_url",
        "cdnUrl",
        "source_url",
        "sourceUrl",
        "asset_url",
        "assetUrl",
    )
    for item in candidates:
        if not isinstance(item, dict):
            continue
        for key in url_keys:
            value = str(item.get(key) or "").strip()
            if value.startswith(("http://", "https://", "asset://")):
                return value
    return ""


def extract_gateway_file_id(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("id", "file_id", "fileId", "AssetId", "asset_id", "assetId", "key", "record_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return extract_gateway_file_id(data)
    return ""


def infer_gateway_asset_type(path: Path | str, mime_type: str = "") -> str:
    mime = (mime_type or mimetypes.guess_type(str(path))[0] or "").lower()
    name = str(path).lower()
    if mime.startswith("video/") or any(name.endswith(ext) for ext in (".mp4", ".mov", ".webm", ".m4v")):
        return "Video"
    if mime.startswith("audio/") or any(name.endswith(ext) for ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")):
        return "Audio"
    return "Image"


def oss_direct_upload_type(asset_type: str) -> str:
    mapping = {"Image": "image", "Audio": "audio", "Video": "video"}
    return mapping.get(str(asset_type or "").strip(), "image")


def resolve_upload_api_base(*, provider: str, video_base_url: str, upload_api_base: str | None = None) -> str:
    """Pick OSS upload service base. Explicit config wins; vjimeng host auto-maps."""
    explicit = str(upload_api_base or "").strip().rstrip("/")
    if explicit:
        return explicit
    host = (video_base_url or "").lower()
    provider_l = (provider or "").lower()
    if "vjimeng.vip" in host or "vjimeng" in provider_l:
        return DEFAULT_VJIMENG_OSS_BASE
    return ""


class GatewayMediaClient:
    """OSS-only uploader used before video generation (星链云 / compatible OSS)."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 120,
        allow_insecure_ssl: bool = False,
        default_model: str | None = None,
        upload_api_base: str | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.allow_insecure_ssl = allow_insecure_ssl
        self.default_model = str(default_model or "").strip()
        self.upload_api_base = resolve_upload_api_base(
            provider=provider,
            video_base_url=base_url,
            upload_api_base=upload_api_base,
        )

    @property
    def normalized_base_url(self) -> str:
        return normalize_openai_base_url(self.provider, self.base_url)

    def upload_reference(self, path: Path | str, *, asset_type: str | None = None) -> str:
        file_path = Path(path)
        if not file_path.is_file():
            raise ValueError(f"找不到待上传素材：{file_path}")

        kind = asset_type or infer_gateway_asset_type(file_path)
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        if not self.upload_api_base:
            raise ValueError(
                "未配置素材 OSS 直传地址。星链云唯一途径是 https://oss.vjimeng.vip；"
                "请使用 vjimeng 视频 Base URL，或在配置中设置 videoOssBaseUrl。"
            )
        return self._upload_via_direct_oss(file_path, mime_type=mime_type, asset_type=kind)

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key.strip()}"}

    def _upload_via_direct_oss(self, file_path: Path, *, mime_type: str, asset_type: str) -> str:
        """星链云 / vjimeng OSS 直传：sign → PUT → complete。

        PUT 目标是阿里云香港桶，与 sign/complete 不同主机；共用连接易出现
        RemoteProtocolError（Server disconnected）。控制面与数据面分开，并对断连重试。
        """
        size = file_path.stat().st_size
        if size <= 0:
            raise ValueError(f"待上传文件为空：{file_path.name}")
        if size > MAX_DIRECT_UPLOAD_BYTES:
            raise ValueError(
                f"素材超过 OSS 直传上限（{MAX_DIRECT_UPLOAD_BYTES // (1024 * 1024)}MB）：{file_path.name}"
            )

        oss_type = oss_direct_upload_type(asset_type)
        base = self.upload_api_base.rstrip("/")
        timeout = max(float(self.timeout_seconds or 20), 300.0)
        upload_bytes = file_path.read_bytes()
        upload_name = file_path.name
        upload_mime = mime_type
        upload_size = len(upload_bytes)

        if asset_type == "Image" and upload_size > 900_000:
            try:
                from io import BytesIO

                from PIL import Image

                with Image.open(BytesIO(upload_bytes)) as image:
                    image = image.convert("RGB") if image.mode in {"RGBA", "P", "LA"} else image
                    image.thumbnail((1536, 1536))
                    buffer = BytesIO()
                    image.save(buffer, format="JPEG", quality=85, optimize=True)
                    compressed = buffer.getvalue()
                if 0 < len(compressed) < upload_size:
                    upload_bytes = compressed
                    upload_size = len(compressed)
                    upload_mime = "image/jpeg"
                    if not upload_name.lower().endswith((".jpg", ".jpeg")):
                        upload_name = f"{Path(upload_name).stem}.jpg"
            except Exception:
                pass

        sign_body = {
            "filename": upload_name,
            "content_type": upload_mime,
            "size": upload_size,
            "type": oss_type,
        }

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                return self._upload_via_direct_oss_once(
                    base=base,
                    timeout=timeout,
                    sign_body=sign_body,
                    upload_bytes=upload_bytes,
                    upload_name=upload_name,
                    upload_mime=upload_mime,
                    oss_type=oss_type,
                )
            except ValueError:
                raise
            except httpx.HTTPError as exc:
                last_error = exc
                # 断连/超时可重试；其它协议错误直接抛
                retryable = isinstance(
                    exc,
                    (
                        httpx.RemoteProtocolError,
                        httpx.ReadTimeout,
                        httpx.WriteTimeout,
                        httpx.ConnectTimeout,
                        httpx.ConnectError,
                        httpx.ReadError,
                        httpx.WriteError,
                    ),
                )
                if not retryable or attempt >= 3:
                    raise ValueError(
                        f"OSS 直传请求失败（第 {attempt} 次，{type(exc).__name__}）：{exc}"
                    ) from exc
                time.sleep(0.8 * attempt)
        raise ValueError(f"OSS 直传请求失败：{last_error}")

    def _upload_via_direct_oss_once(
        self,
        *,
        base: str,
        timeout: float,
        sign_body: dict[str, object],
        upload_bytes: bytes,
        upload_name: str,
        upload_mime: str,
        oss_type: str,
    ) -> str:
        auth = {**self._auth_headers(), "Content-Type": "application/json"}
        # 控制面（oss.vjimeng.vip）与数据面（*.aliyuncs.com）分客户端，避免跨主机复用连接被对端掐断。
        with build_http_client(timeout_seconds=timeout, allow_insecure_ssl=self.allow_insecure_ssl) as api:
            sign_res = api.post(f"{base}/api/direct-upload/sign", headers=auth, json=sign_body)
            if sign_res.status_code >= 400:
                raise ValueError(self._format_oss_error("申请 OSS 直传签名", sign_res))
            try:
                sign = sign_res.json()
            except Exception as exc:
                raise ValueError("OSS 直传签名返回无法解析的 JSON") from exc
            if not isinstance(sign, dict):
                raise ValueError("OSS 直传签名返回格式异常")

            upload_url = str(sign.get("upload_url") or "").strip()
            public_url = str(sign.get("public_url") or "").strip()
            key = str(sign.get("key") or "").strip()
            method = str(sign.get("method") or "PUT").strip().upper() or "PUT"
            put_headers = sign.get("headers") if isinstance(sign.get("headers"), dict) else {}
            headers = {str(k): str(v) for k, v in put_headers.items() if str(k).strip()}
            if "Content-Type" not in headers and "content-type" not in {h.lower() for h in headers}:
                headers["Content-Type"] = upload_mime
            if not upload_url or not key:
                raise ValueError(f"OSS 直传签名缺少 upload_url/key：{str(sign)[:240]}")

        with build_http_client(timeout_seconds=timeout, allow_insecure_ssl=self.allow_insecure_ssl) as data:
            put_res = data.request(method, upload_url, headers=headers, content=upload_bytes)
            if put_res.status_code >= 400:
                text = (put_res.text or put_res.reason_phrase or "PUT failed")[:500]
                raise ValueError(f"直传 OSS PUT 失败（HTTP {put_res.status_code}）：{text}")

        with build_http_client(timeout_seconds=timeout, allow_insecure_ssl=self.allow_insecure_ssl) as api:
            complete_res = api.post(
                f"{base}/api/direct-upload/complete",
                headers=auth,
                json={"key": key, "filename": upload_name, "type": oss_type},
            )
            if complete_res.status_code >= 400:
                raise ValueError(self._format_oss_error("登记 OSS 上传完成", complete_res))
            try:
                complete = complete_res.json()
            except Exception:
                complete = {}
            complete_url = ""
            if isinstance(complete, dict):
                complete_url = str(complete.get("url") or "").strip()
            final = stabilize_oss_public_url(public_url) or stabilize_oss_public_url(complete_url)
            if not final.startswith(("http://", "https://")):
                raise ValueError(
                    f"OSS 上传完成但未返回可用 URL（key={key}）：{str(complete)[:240] or public_url[:120]}"
                )
            return final

    @staticmethod
    def _format_oss_error(action: str, response: httpx.Response) -> str:
        text = (response.text or response.reason_phrase or "request failed")[:500]
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            code = str(payload.get("error") or "").strip()
            message = str(payload.get("message") or "").strip()
            if code or message:
                detail = f"{code}: {message}".strip(": ")
                return f"{action}失败（HTTP {response.status_code}）：{detail}"
        return f"{action}失败（HTTP {response.status_code}）：{text}"


def build_gateway_media_client(config: dict[str, object]) -> GatewayMediaClient:
    return GatewayMediaClient(
        provider=str(config.get("videoProvider") or "").strip() or "newapi",
        base_url=str(config.get("videoBaseUrl") or ""),
        api_key=str(config.get("videoApiKey") or ""),
        allow_insecure_ssl=bool(config.get("videoAllowInsecureSsl")),
        upload_api_base=str(config.get("videoOssBaseUrl") or config.get("videoUploadApiBase") or "").strip()
        or None,
    )


def media_uploader_from_client(client: GatewayMediaClient) -> Uploader:
    def _upload(path: Path, asset_type: str) -> str:
        return client.upload_reference(path, asset_type=asset_type)

    return _upload
