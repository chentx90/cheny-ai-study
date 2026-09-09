from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.config import (
    _build_precheck,
    _fetch_video_models,
    _load_api_config,
    _mask_api_config,
    _save_api_config,
    _test_llm_connection,
    _test_video_connection,
)
from ai_video_manager.api.schemas import SaveApiConfigRequest, TestLLMConnectionRequest
from ai_video_manager.auth.permissions import require_user
from ai_video_manager.llm import normalize_llm_use_cases
from ai_video_manager.api.job_runner import video_job_runner


def _user_id(request: Request) -> str:
    return require_user(request).id


def register_config_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store
    prompt_engine = services.prompt_engine
    video_engine = services.video_engine
    refresh_video_engine = services.refresh_video_engine
    video_runtime_mode = services.video_runtime_mode

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "video_jobs_active": video_job_runner.active_count,
            "video_recovery": getattr(app.state, "video_recovery_report", {}),
        }

    @app.get("/api/config/apis")
    def get_api_config(request: Request) -> dict:
        user_id = _user_id(request)
        config = _load_api_config(store, user_id=user_id)
        refresh_video_engine(config)
        masked = _mask_api_config(config)
        masked["videoRuntimeProvider"] = video_engine.provider
        masked["videoRuntimeMode"] = video_runtime_mode()
        masked["scope"] = "user"
        return {"data": masked}

    @app.put("/api/config/apis")
    def save_api_config(request_body: SaveApiConfigRequest, request: Request) -> dict:
        user_id = _user_id(request)
        current = _load_api_config(store, user_id=user_id)
        incoming = dict(request_body.data)
        for key in ("llmApiKey", "videoApiKey", "imageApiKey"):
            if key not in incoming or incoming[key] == "":
                incoming[key] = current.get(key, "")
        merged = {**current, **incoming}
        merged["llmUseCases"] = normalize_llm_use_cases(merged)
        saved = _save_api_config(store, merged, user_id=user_id)
        refresh_video_engine(saved)
        masked = _mask_api_config(saved)
        masked["videoRuntimeProvider"] = video_engine.provider
        masked["videoRuntimeMode"] = video_runtime_mode()
        masked["scope"] = "user"
        return {"data": masked}

    @app.post("/api/config/precheck")
    def precheck_config(request: Request) -> dict:
        user_id = _user_id(request)
        config = _load_api_config(store, user_id=user_id)
        refresh_video_engine(config)
        checks = _build_precheck(config, store, prompt_engine, user_id=user_id)
        return {
            "ok": all(item["status"] != "fail" for item in checks),
            "checks": checks,
            "videoRuntimeProvider": video_engine.provider,
            "videoRuntimeMode": video_runtime_mode(),
        }

    @app.post("/api/config/llm/test")
    def test_llm_connection(request_body: TestLLMConnectionRequest, request: Request) -> dict:
        user_id = _user_id(request)
        result = _test_llm_connection(store, request_body.use_case, request_body.data, user_id=user_id)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.post("/api/config/video/test")
    def test_video_connection(request_body: SaveApiConfigRequest, request: Request) -> dict:
        user_id = _user_id(request)
        result = _test_video_connection(store, request_body.data, user_id=user_id)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.post("/api/config/video/models")
    def list_video_models(request_body: SaveApiConfigRequest, request: Request) -> dict:
        user_id = _user_id(request)
        result = _fetch_video_models(store, request_body.data, user_id=user_id)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.get("/api/config/video/models")
    def list_saved_video_models(request: Request) -> dict:
        user_id = _user_id(request)
        result = _fetch_video_models(store, user_id=user_id)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result)
        return result
