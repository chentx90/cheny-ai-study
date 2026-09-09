from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ai_video_manager.auth.acl import enforce_project_acl_middleware
from ai_video_manager.auth.runtime import resolve_auth_disabled_user
from ai_video_manager.storage import SQLiteStore


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, store: SQLiteStore) -> None:
        super().__init__(app)
        self.store = store

    async def dispatch(self, request: Request, call_next):
        request.state.user = None
        request.state.project_access = None
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            request.state.user = resolve_auth_disabled_user(self.store)
            enforce_project_acl_middleware(self.store, request)
        return await call_next(request)
