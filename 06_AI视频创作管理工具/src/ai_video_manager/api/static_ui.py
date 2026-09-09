from __future__ import annotations

from pathlib import PurePosixPath

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not self._is_frontend_route(path, scope):
                raise
        return await super().get_response("index.html", scope)

    @staticmethod
    def _is_frontend_route(path: str, scope) -> bool:
        if scope.get("method") not in {"GET", "HEAD"}:
            return False
        normalized = str(scope.get("path") or path).lstrip("/")
        if normalized.startswith("api/"):
            return False
        return PurePosixPath(normalized).suffix == ""
