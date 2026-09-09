from __future__ import annotations

from typing import Any

PERMISSION_KEYS = (
    "can_create_project",
    "can_make_public",
)


def normalize_user_permissions(raw: Any) -> dict[str, bool | None]:
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, bool | None] = {}
    for key in PERMISSION_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if value is None:
            clean[key] = None
        else:
            clean[key] = bool(value)
    return clean
