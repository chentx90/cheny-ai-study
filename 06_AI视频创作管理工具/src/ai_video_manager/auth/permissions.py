from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from ai_video_manager.models import SystemRole, User
from ai_video_manager.permissions_util import PERMISSION_KEYS, normalize_user_permissions

__all__ = [
    "PERMISSION_KEYS",
    "normalize_user_permissions",
    "require_user",
    "resolve_user_capabilities",
]


def require_user(request: Request) -> User:
    user = request.state.user
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def resolve_user_capabilities(user: User, defaults: dict[str, Any]) -> dict[str, bool]:
    overrides = normalize_user_permissions(getattr(user, "permissions", None))
    is_admin = user.role == SystemRole.ADMIN

    def resolve_flag(key: str, system_default: bool) -> bool:
        if is_admin:
            return True
        override = overrides.get(key)
        if override is None:
            return system_default
        return bool(override)

    return {
        "is_admin": is_admin,
        "can_create_project": resolve_flag(
            "can_create_project",
            bool(defaults.get("allow_user_create_project", True)),
        ),
        "can_make_public": resolve_flag(
            "can_make_public",
            bool(defaults.get("allow_user_make_public", False)),
        ),
    }
