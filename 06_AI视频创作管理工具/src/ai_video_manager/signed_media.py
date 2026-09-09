"""Short-lived signed public media URLs for gateway reference fetching."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ai_video_manager.project_bundle import resolve_project_data_root
from ai_video_manager.storage import SQLiteStore


def _signing_secret(store: SQLiteStore) -> bytes:
    env = str(os.environ.get("AVM_MEDIA_SIGNING_SECRET") or "").strip()
    if env:
        return env.encode("utf-8")
    marker = store.workspace_root / "config" / ".media_signing_key"
    marker.parent.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_bytes(os.urandom(32))
    return marker.read_bytes()


def public_media_base_url(config: dict[str, object] | None = None) -> str:
    raw = ""
    if isinstance(config, dict):
        raw = str(config.get("videoPublicBaseUrl") or config.get("publicBaseUrl") or "").strip()
    if not raw:
        raw = str(os.environ.get("AVM_PUBLIC_BASE_URL") or "").strip()
    return raw.rstrip("/")


def mint_signed_media_url(
    store: SQLiteStore,
    *,
    project_id: str,
    relative_path: str,
    public_base: str,
    ttl_seconds: int = 3600,
) -> str:
    clean = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not clean.startswith("assets/"):
        raise ValueError(f"仅支持 assets/ 下素材签发公开链接：{relative_path}")
    # Ensure file exists under data_root
    root = resolve_project_data_root(store, project_id).resolve()
    candidate = (root / clean).resolve()
    if not str(candidate).startswith(str(root)) or not candidate.is_file():
        raise ValueError(f"找不到参考素材：{relative_path}")

    expires = int(time.time()) + max(int(ttl_seconds), 60)
    payload = {
        "p": project_id,
        "f": clean,
        "e": expires,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(_signing_secret(store), body.encode("ascii"), hashlib.sha256).hexdigest()
    token = f"{body}.{sig}"
    return f"{public_base.rstrip('/')}/api/public/media/{quote(token, safe='.=_-')}"


def verify_signed_media_token(store: SQLiteStore, token: str) -> tuple[str, Path]:
    from urllib.parse import unquote

    raw = unquote(str(token or "").strip())
    if "." not in raw:
        raise ValueError("无效的媒体令牌")
    body, sig = raw.rsplit(".", 1)
    expected = hmac.new(_signing_secret(store), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ValueError("媒体令牌签名无效")
    try:
        payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except Exception as exc:
        raise ValueError("媒体令牌无法解析") from exc
    expires = int(payload.get("e") or 0)
    if expires < int(time.time()):
        raise ValueError("媒体令牌已过期")
    project_id = str(payload.get("p") or "").strip()
    relative = str(payload.get("f") or "").strip().replace("\\", "/").lstrip("/")
    if not project_id or not relative.startswith("assets/"):
        raise ValueError("媒体令牌内容无效")
    root = resolve_project_data_root(store, project_id).resolve()
    candidate = (root / relative).resolve()
    if not str(candidate).startswith(str(root)) or not candidate.is_file():
        raise ValueError("媒体文件不存在")
    return project_id, candidate
