from __future__ import annotations

from ai_video_manager.models import SystemRole, User
from ai_video_manager.storage import SQLiteStore

AUTH_DISABLED_ENV = "AVM_AUTH_DISABLED"
AUTH_DISABLED_VALUES = {"1", "true", "yes", "on"}


def is_auth_disabled() -> bool:
    return True


def resolve_auth_disabled_user(store: SQLiteStore) -> User:
    for user in store.list_users():
        if user.is_active and user.role == SystemRole.ADMIN:
            return user
    return User(
        id="user_local_mode",
        username="local",
        password_hash="",
        display_name="本地模式",
        role=SystemRole.ADMIN,
    )
