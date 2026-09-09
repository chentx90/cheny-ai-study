from __future__ import annotations

from fastapi import FastAPI, Request

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.config import _load_api_config, _merge_api_config
from ai_video_manager.api.schemas import SaveApiConfigRequest
from ai_video_manager.auth.permissions import require_user
from ai_video_manager.image_generation import ImageGenerationError, build_image_client, image_gateway_ready


def register_image_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store

    @app.post("/api/config/image/test")
    def test_image_connection(
        request: Request,
        body: SaveApiConfigRequest = SaveApiConfigRequest(data={}),
    ) -> dict:
        user_id = require_user(request).id
        config = (
            _merge_api_config(store, body.data, user_id=user_id)
            if body.data
            else _load_api_config(store, user_id=user_id)
        )
        provider = str(config.get("imageProvider") or "off").strip().lower()
        if provider in {"", "off", "none", "disabled"}:
            return {"ok": False, "provider": "off", "detail": "图片服务未启用"}
        if not image_gateway_ready(config):
            return {"ok": False, "provider": provider, "detail": "需要图片 Base URL 和 API Key"}
        try:
            return {**build_image_client(config).test_connection(), "provider": provider}
        except ImageGenerationError as exc:
            return {"ok": False, "provider": provider, "detail": str(exc)}

    @app.post("/api/config/image/models")
    def fetch_image_models(
        request: Request,
        body: SaveApiConfigRequest = SaveApiConfigRequest(data={}),
    ) -> dict:
        user_id = require_user(request).id
        config = (
            _merge_api_config(store, body.data, user_id=user_id)
            if body.data
            else _load_api_config(store, user_id=user_id)
        )
        if not image_gateway_ready(config):
            return {"ok": False, "models": [], "detail": "需要图片 Base URL 和 API Key"}
        try:
            return {**build_image_client(config).fetch_models(), "provider": str(config.get("imageProvider") or "openai")}
        except ImageGenerationError as exc:
            return {"ok": False, "models": [], "detail": str(exc)}
