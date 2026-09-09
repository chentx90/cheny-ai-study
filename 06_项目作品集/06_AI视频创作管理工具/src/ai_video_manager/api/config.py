from __future__ import annotations

import shutil

from ai_video_manager.image_generation import image_config_ready, resolve_image_gateway_config
from ai_video_manager.llm import LLM_USE_CASES, build_llm_client, normalize_llm_use_cases
from ai_video_manager.prompt_engine import PromptEngine
from ai_video_manager.security import SECRET_PREFIX, protect_secret, reveal_secret
from ai_video_manager.storage import SQLiteStore
from ai_video_manager.video_client import build_video_client
from ai_video_manager.video_generation import build_video_adapter
from ai_video_manager.xyq_cli import XYQ_VIDEO_MODELS, XiaoyunqueCliClient, is_xyq_provider

API_CONFIG_KEY = "api_config"


def _default_api_config() -> dict[str, object]:
    return {
        "llmProvider": "newapi",
        "llmBaseUrl": "",
        "llmApiKey": "",
        "llmDefaultModel": "",
        "llmUseCases": normalize_llm_use_cases({}),
        "videoProvider": "newapi",
        "videoBaseUrl": "",
        "videoApiKey": "",
        "videoDefaultModel": "",
        "videoOssBaseUrl": "",
        "videoAllowInsecureSsl": False,
        "xyqCliPath": "",
        "xyqOpenApiBase": "https://xyq.jianying.com",
        "imageProvider": "openai",
        "imageProtocol": "openai",
        "imageBaseUrl": "",
        "imageApiKey": "",
        "imageUseLlmCredentials": True,
        "imageModel": "",
        "imageOutputSize": "1024x1024",
    }


def _load_api_config(store: SQLiteStore, *, user_id: str | None = None) -> dict[str, object]:
    default = _default_api_config()
    if user_id:
        stored = store.get_user_setting(user_id, API_CONFIG_KEY, default={})
        config = {**default, **(stored or {})}
    else:
        config = {**default, **store.get_setting(API_CONFIG_KEY, default)}
    config.pop("offlineMode", None)
    config.pop("autoApprove", None)
    config.pop("autoApproveThreshold", None)
    if str(config.get("llmProvider") or "") == "mock":
        config["llmProvider"] = "newapi"
    video_provider = str(config.get("videoProvider") or "").strip()
    if not video_provider or video_provider.lower() in {"mock", "offline", "local"}:
        config["videoProvider"] = "newapi"
    elif "://" in video_provider:
        # 历史误把站点 URL 填进 provider，统一归一为 newapi
        config["videoProvider"] = "newapi"
    image_provider = str(config.get("imageProvider") or "").strip().lower()
    if image_provider in {"", "mock", "disabled", "none"}:
        config["imageProvider"] = "off"
    elif image_provider == "nova":
        config["imageProvider"] = "openai"
    config["llmUseCases"] = normalize_llm_use_cases(config)
    for key in ("llmApiKey", "videoApiKey", "imageApiKey"):
        try:
            config[key] = reveal_secret(str(config.get(key) or ""), store.workspace_root)
        except ValueError:
            config[key] = ""
    return config

def _save_api_config(store: SQLiteStore, config: dict[str, object], *, user_id: str) -> dict[str, object]:
    clear_config = dict(config)
    clear_config.pop("offlineMode", None)
    protected = dict(config)
    protected.pop("offlineMode", None)
    for key in ("llmApiKey", "videoApiKey", "imageApiKey"):
        raw = "" if clear_config.get(key) is None else str(clear_config.get(key) or "")
        protected[key] = protect_secret(raw, store.workspace_root) if raw else ""
    store.save_user_setting(user_id, API_CONFIG_KEY, protected)
    return clear_config

def _merge_api_config(
    store: SQLiteStore,
    incoming: dict[str, object] | None,
    *,
    user_id: str | None = None,
) -> dict[str, object]:
    current = _load_api_config(store, user_id=user_id)
    patch = dict(incoming or {})
    patch.pop("offlineMode", None)
    for key in ("llmApiKey", "videoApiKey", "imageApiKey"):
        if key not in patch or patch[key] == "":
            patch[key] = current.get(key, "")
    merged = {**current, **patch}
    merged["llmUseCases"] = normalize_llm_use_cases(merged)
    return merged

def _build_precheck(
    config: dict[str, object],
    store: SQLiteStore,
    prompt_engine: PromptEngine,
    *,
    user_id: str | None = None,
) -> list[dict[str, object]]:
    raw_config = (
        store.get_user_setting(user_id, API_CONFIG_KEY, default={})
        if user_id
        else store.get_setting(API_CONFIG_KEY, {})
    )
    disk = shutil.disk_usage(store.workspace_root)
    free_gb = round(disk.free / (1024**3), 2)
    video_ready = _provider_ready(config, "video")
    image_ready = image_config_ready(config) if str(config.get("imageProvider") or "") != "off" else False
    llm_use_case_count = sum(
        bool(str((config.get("llmUseCases") or {}).get(use_case, {}).get("model") or "").strip())
        for use_case in LLM_USE_CASES
    )
    llm_use_cases_ready = llm_use_case_count == len(LLM_USE_CASES)

    checks = [
        _check(
            "llm",
            "LLM 配置",
            _provider_ready(config, "llm"),
            "LLM 服务配置完整" if _provider_ready(config, "llm") else "需要 LLM Base URL 和 API Key",
        ),
        _check(
            "video",
            "视频服务配置",
            video_ready,
            _video_config_detail(config, video_ready),
        ),
        _check(
            "image",
            "图片服务",
            image_ready or str(config.get("imageProvider") or "off") == "off",
            (
                "图片网关配置完整"
                if image_ready
                else (
                    "未启用（资源管理可手动上传参考图）"
                    if str(config.get("imageProvider") or "off") == "off"
                    else "图片服务未就绪"
                )
            ),
            warn_when_false=True,
        ),
        _check(
            "llm_use_cases",
            "LLM 使用点",
            llm_use_cases_ready,
            f"{len(LLM_USE_CASES)} 个使用点已配置模型"
            if llm_use_cases_ready
            else f"已配置 {llm_use_case_count}/{len(LLM_USE_CASES)} 个使用点模型",
            warn_when_false=True,
        ),
        _check(
            "templates",
            "提示词模板",
            len(prompt_engine.list_templates()) > 0,
            f"{len(prompt_engine.list_templates())} 个模板可用",
        ),
        _check(
            "disk",
            "磁盘空间",
            disk.free >= 512 * 1024 * 1024,
            f"可用空间 {free_gb} GB",
        ),
        _check(
            "secrets",
            "密钥存储",
            _secrets_are_protected(raw_config),
            "API Key 已使用本地密钥保护" if raw_config else "尚未保存 API Key",
            warn_when_false=True,
        ),
    ]
    return checks

def _provider_ready(config: dict[str, object], prefix: str) -> bool:
    provider = str(config.get(f"{prefix}Provider") or "")
    base_url = str(config.get(f"{prefix}BaseUrl") or "").strip()
    api_key = str(config.get(f"{prefix}ApiKey") or "").strip()
    if prefix == "llm":
        return bool(provider and base_url and api_key)
    if is_xyq_provider(provider):
        return bool(api_key)
    return bool(base_url and api_key)


def _video_config_detail(config: dict[str, object], ready: bool) -> str:
    provider = str(config.get("videoProvider") or "")
    if is_xyq_provider(provider):
        return "小云雀 CLI 配置完整" if ready else "需要小云雀 Access Key（videoApiKey）"
    return "需要视频 Base URL 和 API Key" if not ready else "视频服务配置完整"

def _secrets_are_protected(raw_config: dict[str, object]) -> bool:
    values = [str(raw_config.get(key) or "") for key in ("llmApiKey", "videoApiKey", "imageApiKey")]
    return all(not value or value.startswith(SECRET_PREFIX) for value in values)

def _check(
    check_id: str,
    label: str,
    passed: bool,
    detail: str,
    *,
    warn_when_false: bool = False,
) -> dict[str, object]:
    status = "pass" if passed else "warn" if warn_when_false else "fail"
    return {"id": check_id, "label": label, "status": status, "detail": detail}

def _mask_api_config(config: dict[str, object]) -> dict[str, object]:
    resolved_image = resolve_image_gateway_config(config)
    masked = dict(config)
    for key in ("llmApiKey", "videoApiKey", "imageApiKey"):
        raw = str(masked.get(key) or "")
        masked[key] = _mask_secret(raw) if raw else ""
        masked[f"{key}Set"] = bool(raw)
    masked["imageUsingLlmCredentials"] = resolved_image.get("imageCredentialSource") == "llm"
    masked["imageRuntimeBaseUrl"] = str(resolved_image.get("imageBaseUrl") or "")
    masked["llmUseCases"] = normalize_llm_use_cases(masked)
    return masked

def _mask_secret(secret: str) -> str:
    if len(secret) <= 4:
        return "***"
    return f"***{secret[-4:]}"

def _test_video_connection(
    store: SQLiteStore,
    config_override: dict[str, object] | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, object]:
    config = (
        _merge_api_config(store, config_override, user_id=user_id)
        if config_override is not None
        else _load_api_config(store, user_id=user_id)
    )
    provider = str(config.get("videoProvider") or "newapi")
    if is_xyq_provider(provider):
        try:
            client = XiaoyunqueCliClient(
                access_key=str(config.get("videoApiKey") or ""),
                cli_path=str(config.get("xyqCliPath") or "").strip() or None,
                openapi_base=str(config.get("xyqOpenApiBase") or "").strip() or None,
            )
        except RuntimeError as exc:
            return {"ok": False, "provider": provider, "detail": str(exc)}
        result = client.test_connection()
        return {
            "ok": bool(result.get("ok")),
            "provider": provider,
            "detail": result.get("detail", ""),
            "base_url": result.get("base_url", ""),
            "cli_path": result.get("cli_path", ""),
        }

    try:
        build_video_adapter(config)
    except RuntimeError as exc:
        return {"ok": False, "provider": provider, "detail": str(exc)}

    client = build_video_client(config)
    result = client.test_connection()
    return {
        "ok": bool(result.get("ok")),
        "provider": provider,
        "detail": result.get("detail", ""),
        "base_url": result.get("base_url", client.normalized_base_url),
    }


def _fetch_video_models(
    store: SQLiteStore,
    config_override: dict[str, object] | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, object]:
    config = (
        _merge_api_config(store, config_override, user_id=user_id)
        if config_override is not None
        else _load_api_config(store, user_id=user_id)
    )
    provider = str(config.get("videoProvider") or "").strip() or "custom"
    if is_xyq_provider(provider):
        try:
            build_video_adapter(config)
        except RuntimeError as exc:
            return {"ok": False, "provider": provider, "models": [], "detail": str(exc)}
        return {
            "ok": True,
            "provider": provider,
            "models": list(XYQ_VIDEO_MODELS),
            "detail": "小云雀 CLI 内置模型列表",
            "base_url": str(config.get("xyqOpenApiBase") or "").strip(),
            "source": "xyq-cli",
        }

    try:
        build_video_adapter(config)
    except RuntimeError as exc:
        return {"ok": False, "provider": provider, "models": [], "detail": str(exc)}

    client = build_video_client(config)
    result = client.fetch_models()
    return {
        "ok": bool(result.get("ok")),
        "provider": provider,
        "models": list(result.get("models") or []),
        "detail": result.get("detail", ""),
        "base_url": result.get("base_url", ""),
        "source": result.get("source", ""),
    }


def _test_llm_connection(
    store: SQLiteStore,
    use_case: str,
    config_override: dict[str, object] | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, object]:
    if use_case not in LLM_USE_CASES:
        return {"ok": False, "use_case": use_case, "detail": f"未知 LLM 使用点：{use_case}"}
    config = (
        _merge_api_config(store, config_override, user_id=user_id)
        if config_override is not None
        else _load_api_config(store, user_id=user_id)
    )
    client = build_llm_client(config, use_case)
    result = client.test_connection()
    return {
        "ok": bool(result.get("ok")),
        "use_case": use_case,
        "label": LLM_USE_CASES[use_case],
        "provider": client.provider,
        "model": client.model,
        "detail": result.get("detail", ""),
    }
