from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.utils import _dump
from ai_video_manager.auth.acl import resolve_project_role
from ai_video_manager.auth.permissions import resolve_user_capabilities, require_user
from ai_video_manager.auth.runtime import is_auth_disabled
from ai_video_manager.models import SystemRole


def register_auth_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store

    @app.get("/api/auth/setup-status")
    def setup_status() -> dict:
        return {"needs_setup": False, "auth_disabled": True}

    @app.get("/api/auth/me")
    def me(request: Request) -> dict:
        user = require_user(request)
        payload = _dump_user(user)
        project_id = request.query_params.get("project_id")
        if project_id:
            role = resolve_project_role(store, user, project_id)
            payload["project_role"] = role.value if role else None
        capabilities = resolve_user_capabilities(user, store.get_auth_defaults())
        return {"user": payload, "capabilities": capabilities, "auth_disabled": is_auth_disabled()}


def _dump_user(user) -> dict:
    data = _dump(user)
    if data:
        data.pop("password_hash", None)
        if "permissions" not in data:
            data["permissions"] = getattr(user, "permissions", {}) or {}
    return data


def require_admin(request: Request) -> None:
    user = request.state.user
    if user is None or user.role != SystemRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin permission required")
