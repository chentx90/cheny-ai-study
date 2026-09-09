"""Runtime paths for local dev and container deployment (fnOS / Docker)."""

from __future__ import annotations

import os
from pathlib import Path

ENV_WORKSPACE_ROOT = "AVM_WORKSPACE_ROOT"
ENV_DB_PATH = "AVM_DB_PATH"
ENV_STATIC_DIR = "AVM_STATIC_DIR"
ENV_SERVE_UI = "AVM_SERVE_UI"
ENV_CORS_ORIGINS = "AVM_CORS_ORIGINS"


def resolve_workspace_root(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env = str(os.environ.get(ENV_WORKSPACE_ROOT) or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path(".").resolve()


def resolve_db_path(explicit: str | Path | None = None, *, workspace_root: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env = str(os.environ.get(ENV_DB_PATH) or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    root = workspace_root or resolve_workspace_root()
    return (root / "database" / "app.db").resolve()


def infer_workspace_root_from_db(db_path: Path) -> Path:
    if db_path.parent.name == "database":
        return db_path.parent.parent.resolve()
    return db_path.parent.resolve()


def resolve_runtime_paths(db_path: str | Path | None = None) -> tuple[Path, Path]:
    """Return (workspace_root, db_path) honoring env vars and explicit test paths."""
    env_root = str(os.environ.get(ENV_WORKSPACE_ROOT) or "").strip()
    env_db = str(os.environ.get(ENV_DB_PATH) or "").strip()
    if env_root:
        workspace_root = Path(env_root).expanduser().resolve()
        resolved_db = Path(env_db).expanduser().resolve() if env_db else resolve_db_path(workspace_root=workspace_root)
        return workspace_root, resolved_db
    if db_path is not None:
        resolved_db = Path(db_path).expanduser().resolve()
        return infer_workspace_root_from_db(resolved_db), resolved_db
    if env_db:
        resolved_db = Path(env_db).expanduser().resolve()
        return infer_workspace_root_from_db(resolved_db), resolved_db
    workspace_root = resolve_workspace_root()
    return workspace_root, resolve_db_path(workspace_root=workspace_root)


def resolve_static_ui_dir(explicit: str | Path | None = None, *, workspace_root: Path | None = None) -> Path | None:
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
        return candidate if candidate.is_dir() else None
    env = str(os.environ.get(ENV_STATIC_DIR) or "").strip()
    if env:
        candidate = Path(env).expanduser().resolve()
        return candidate if candidate.is_dir() else None
    root = workspace_root or resolve_workspace_root()
    default = (root / "frontend" / "dist").resolve()
    return default if default.is_dir() else None


def should_serve_ui() -> bool:
    return str(os.environ.get(ENV_SERVE_UI) or "").strip().lower() in {"1", "true", "yes", "on"}


def cors_origins() -> list[str]:
    raw = str(os.environ.get(ENV_CORS_ORIGINS) or "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
