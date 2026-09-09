"""SQLite persistence for AI Video Manager.

``SQLiteStore`` is the single repository boundary for project data. Route handlers
and services should depend on store methods rather than issuing raw SQL elsewhere.

"""
from __future__ import annotations

import json
import hashlib
import logging
import mimetypes
import sqlite3
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from .models import (
    Checkpoint,
    Document,
    EntityCard,
    EntityMaterial,
    EntityType,
    Project,
    ProjectMember,
    ProjectRole,
    ProjectVisibility,
    PromptCategory,
    PromptCard,
    PromptTemplate,
    Script,
    Segment,
    SystemRole,
    TaskStatus,
    User,
    VideoTask,
    WorkflowState,
    new_id,
)
from .permissions_util import normalize_user_permissions
from .infrastructure.db.v2_migrations import migrate_v2
from .infrastructure.db.v3_migrations import migrate_v3
from .domain.production import VideoOutput


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'active',
    current_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    flags TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    format TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS script_segments (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    is_converted INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS prompt_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    template TEXT NOT NULL,
    variables TEXT NOT NULL,
    is_default INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_cards (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    type TEXT NOT NULL,
    state TEXT,
    reference_images TEXT NOT NULL,
    audio_samples TEXT NOT NULL,
    video_clips TEXT NOT NULL,
    assets TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prompt_cards (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    anchor_text TEXT NOT NULL,
    duration REAL NOT NULL,
    source_text TEXT NOT NULL DEFAULT '',
    source_start INTEGER NOT NULL DEFAULT 0,
    source_end INTEGER NOT NULL DEFAULT 0,
    source_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    state TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS video_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    assets TEXT NOT NULL,
    duration INTEGER,
    status TEXT NOT NULL,
    result_path TEXT,
    api_task_id TEXT,
    provider TEXT NOT NULL DEFAULT 'mock',
    prompt_card_id TEXT,
    source_prompt_hash TEXT NOT NULL DEFAULT '',
    is_preview INTEGER NOT NULL,
    version INTEGER NOT NULL,
    orphaned INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    permissions TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS project_members (
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(user_id);
CREATE TABLE IF NOT EXISTS segment_locks (
    project_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    locked_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (project_id, segment_id)
);
CREATE INDEX IF NOT EXISTS idx_segment_locks_project ON segment_locks(project_id);
CREATE TABLE IF NOT EXISTS entity_materials (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    type TEXT NOT NULL,
    asset_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, entity_name, type, asset_path)
);
CREATE TABLE IF NOT EXISTS project_assets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, storage_path)
);
CREATE INDEX IF NOT EXISTS idx_project_assets_project ON project_assets(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_cards_project_segment ON prompt_cards(project_id, segment_id, order_index);
CREATE TABLE IF NOT EXISTS project_preprocess (
    project_id TEXT PRIMARY KEY,
    document_text TEXT NOT NULL DEFAULT '',
    split_strategy TEXT NOT NULL DEFAULT 'chapter',
    custom_split_pattern TEXT NOT NULL DEFAULT '',
    duration_minutes REAL NOT NULL DEFAULT 2,
    document_file TEXT NOT NULL DEFAULT '{}',
    active_segment_id TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '分集原文',
    script_convert_template_id TEXT NOT NULL DEFAULT '',
    project_style_prompt TEXT NOT NULL DEFAULT '',
    expected_total_duration_seconds REAL,
    default_aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    default_video_duration INTEGER NOT NULL DEFAULT 5,
    default_video_model TEXT NOT NULL DEFAULT '',
    default_resolution TEXT NOT NULL DEFAULT '720p',
    assets_confirmed INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0,
    migrated_from_blob INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_segments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_project_segments_project ON project_segments(project_id, order_index);
CREATE TABLE IF NOT EXISTS project_scripts (
    segment_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    validation TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prompt_card_versions (
    id TEXT PRIMARY KEY,
    prompt_card_id TEXT NOT NULL,
    version_index INTEGER NOT NULL,
    version_type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    prompt_text TEXT NOT NULL,
    anchor_text TEXT NOT NULL DEFAULT '',
    source_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prompt_card_versions_card ON prompt_card_versions(prompt_card_id, version_index);
"""


class SQLiteStore:
    def __init__(
        self,
        db_path: str | Path = "database/app.db",
        workspace_root: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.workspace_root = Path(workspace_root) if workspace_root else self._infer_workspace_root()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _infer_workspace_root(self) -> Path:
        return self.db_path.parent.parent if self.db_path.parent.name == "database" else self.db_path.parent

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
            if "category" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN category TEXT NOT NULL DEFAULT 'active'")
            if "deleted_at" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN deleted_at TEXT")
            if "owner_id" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN owner_id TEXT")
            if "visibility" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'")
            if "description" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN description TEXT NOT NULL DEFAULT ''")
            entity_card_columns = {row["name"] for row in conn.execute("PRAGMA table_info(entity_cards)").fetchall()}
            if "assets" not in entity_card_columns:
                conn.execute("ALTER TABLE entity_cards ADD COLUMN assets TEXT NOT NULL DEFAULT '[]'")
            video_task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(video_tasks)").fetchall()}
            if "prompt_card_id" not in video_task_columns:
                conn.execute("ALTER TABLE video_tasks ADD COLUMN prompt_card_id TEXT")
            if "source_prompt_hash" not in video_task_columns:
                conn.execute("ALTER TABLE video_tasks ADD COLUMN source_prompt_hash TEXT NOT NULL DEFAULT ''")
            if "provider" not in video_task_columns:
                conn.execute("ALTER TABLE video_tasks ADD COLUMN provider TEXT NOT NULL DEFAULT 'mock'")
            if "orphaned" not in video_task_columns:
                conn.execute("ALTER TABLE video_tasks ADD COLUMN orphaned INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_video_tasks_prompt_card ON video_tasks(prompt_card_id)")
            prompt_card_columns = {row["name"] for row in conn.execute("PRAGMA table_info(prompt_cards)").fetchall()}
            if "source_text" not in prompt_card_columns:
                conn.execute("ALTER TABLE prompt_cards ADD COLUMN source_text TEXT NOT NULL DEFAULT ''")
            if "source_start" not in prompt_card_columns:
                conn.execute("ALTER TABLE prompt_cards ADD COLUMN source_start INTEGER NOT NULL DEFAULT 0")
            if "source_end" not in prompt_card_columns:
                conn.execute("ALTER TABLE prompt_cards ADD COLUMN source_end INTEGER NOT NULL DEFAULT 0")
            if "locked" not in prompt_card_columns:
                conn.execute("ALTER TABLE prompt_cards ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
            if "prompt_version" not in video_task_columns:
                conn.execute("ALTER TABLE video_tasks ADD COLUMN prompt_version INTEGER NOT NULL DEFAULT 1")
            preprocess_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(project_preprocess)").fetchall()
            }
            if "output_root" not in preprocess_columns:
                conn.execute("ALTER TABLE project_preprocess ADD COLUMN output_root TEXT NOT NULL DEFAULT ''")
            if "source_assets_root" not in preprocess_columns:
                conn.execute("ALTER TABLE project_preprocess ADD COLUMN source_assets_root TEXT NOT NULL DEFAULT ''")
            if "data_root" not in preprocess_columns:
                conn.execute("ALTER TABLE project_preprocess ADD COLUMN data_root TEXT NOT NULL DEFAULT ''")
            if "content_type" not in preprocess_columns:
                conn.execute("ALTER TABLE project_preprocess ADD COLUMN content_type TEXT NOT NULL DEFAULT '分集原文'")
            if "script_convert_template_id" not in preprocess_columns:
                conn.execute("ALTER TABLE project_preprocess ADD COLUMN script_convert_template_id TEXT NOT NULL DEFAULT ''")
            if "project_style_prompt" not in preprocess_columns:
                conn.execute("ALTER TABLE project_preprocess ADD COLUMN project_style_prompt TEXT NOT NULL DEFAULT ''")
            user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "permissions" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN permissions TEXT NOT NULL DEFAULT '{}'")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                );
                CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id);

                CREATE TABLE IF NOT EXISTS command_operations (
                    operation_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    project_id TEXT,
                    user_id TEXT,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error_message TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_command_operations_project
                    ON command_operations(project_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS agent_threads (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    user_id TEXT,
                    title TEXT NOT NULL DEFAULT '项目助手',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_agent_threads_project
                    ON agent_threads(project_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS agent_messages (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_messages_thread
                    ON agent_messages(thread_id, created_at);

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    user_request TEXT NOT NULL,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    waiting_for_approval INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_thread
                    ON agent_runs(thread_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS agent_tool_calls (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    confirmation TEXT NOT NULL DEFAULT 'none',
                    result_json TEXT,
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_run
                    ON agent_tool_calls(run_id, created_at);

                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_events_run
                    ON agent_events(run_id, id);
                """
            )
            agent_thread_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(agent_threads)").fetchall()
            }
            if "summary" not in agent_thread_columns:
                conn.execute("ALTER TABLE agent_threads ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
            if "summary_message_id" not in agent_thread_columns:
                conn.execute("ALTER TABLE agent_threads ADD COLUMN summary_message_id TEXT")
            if "parent_thread_id" not in agent_thread_columns:
                conn.execute("ALTER TABLE agent_threads ADD COLUMN parent_thread_id TEXT")
            if "branch_point_message_id" not in agent_thread_columns:
                conn.execute("ALTER TABLE agent_threads ADD COLUMN branch_point_message_id TEXT")
            if "branch_depth" not in agent_thread_columns:
                conn.execute("ALTER TABLE agent_threads ADD COLUMN branch_depth INTEGER NOT NULL DEFAULT 0")
            if "context_updated_at" not in agent_thread_columns:
                conn.execute("ALTER TABLE agent_threads ADD COLUMN context_updated_at TEXT")
            self._migrate_entity_card_assets_to_materials(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS project_assets (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, storage_path)
                );
                CREATE INDEX IF NOT EXISTS idx_project_assets_project ON project_assets(project_id, updated_at DESC);
                """
            )
            migrate_v2(conn)
            migrate_v3(conn)

    def save_project(self, project: Project) -> Project:
        self.ensure_project_layout(project.id)
        flags = {
            "has_document": project.has_document,
            "has_segments": project.has_segments,
            "has_scripts": project.has_scripts,
            "has_entities": project.has_entities,
            "has_bindings": project.has_bindings,
            "has_prompts": project.has_prompts,
            "assets_confirmed": project.assets_confirmed,
            "has_completed_video": project.has_completed_video,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO projects
                (id, name, category, current_state, created_at, updated_at, deleted_at, owner_id, visibility, description, flags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.id,
                    project.name,
                    project.category,
                    project.current_state.value,
                    project.created_at.isoformat(),
                    project.updated_at.isoformat(),
                    project.deleted_at.isoformat() if project.deleted_at else None,
                    project.owner_id,
                    project.visibility.value if isinstance(project.visibility, ProjectVisibility) else str(project.visibility or "private"),
                    project.description or "",
                    json.dumps(flags, ensure_ascii=False),
                ),
            )
        return project

    def ensure_project_layout(self, project_id: str) -> Path:
        from ai_video_manager.project_bundle import ensure_bundle_layout, resolve_project_data_root

        return ensure_bundle_layout(resolve_project_data_root(self, project_id))

    def _sync_bundle_files(self, project_id: str) -> None:
        try:
            from ai_video_manager.project_bundle import sync_cards_to_files

            sync_cards_to_files(self, project_id)
        except Exception:
            logger.exception("Failed to sync project bundle files for %s", project_id)

    def save_asset(self, project_id: str, asset_type: str, filename: str, content: bytes) -> str:
        self.get_project(project_id)
        directory_by_type = {
            "image": "assets/images",
            "audio": "assets/audio",
            "video": "assets/videos",
        }
        if asset_type not in directory_by_type:
            raise ValueError(f"Unsupported asset type: {asset_type}")
        safe_name = self._safe_filename(filename)
        project_root = self.ensure_project_layout(project_id)
        target_dir = project_root / directory_by_type[asset_type]
        content_hash = hashlib.sha256(content).hexdigest()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT storage_path FROM project_assets WHERE project_id = ? AND sha256 = ?",
                (project_id, content_hash),
            ).fetchone()
        if existing:
            existing_path = self.resolve_project_file(project_id, existing["storage_path"])
            if existing_path.is_file():
                return str(existing["storage_path"])
        duplicate = self._find_duplicate_asset(target_dir, content)
        if duplicate:
            rel_path = str(duplicate.relative_to(project_root)).replace("\\", "/")
            self._ensure_project_asset_record(
                project_id,
                rel_path,
                display_filename=duplicate.name,
                asset_type=asset_type,
                size=duplicate.stat().st_size,
                sha256=content_hash,
            )
            return rel_path

        suffix = Path(safe_name).suffix or ".bin"
        asset_id = new_id("asset")
        target = target_dir / f"{asset_id}{suffix}"
        target.write_bytes(content)
        storage_path = str(target.relative_to(project_root)).replace("\\", "/")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO project_assets
                (id, project_id, storage_path, filename, asset_type, bytes, sha256,
                 mime_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    project_id,
                    storage_path,
                    safe_name,
                    asset_type,
                    len(content),
                    content_hash,
                    mimetypes.guess_type(safe_name)[0] or "",
                    now,
                    now,
                ),
            )
        return storage_path

    def _find_duplicate_asset(self, target_dir: Path, content: bytes) -> Path | None:
        for item in sorted(target_dir.iterdir()):
            if not item.is_file() or item.stat().st_size != len(content):
                continue
            if item.read_bytes() == content:
                return item
        return None

    def save_original_file(self, project_id: str, filename: str, content: bytes) -> str:
        self.get_project(project_id)
        safe_name = self._safe_filename(filename)
        target_dir = self.ensure_project_layout(project_id) / "original"
        target = self._unique_path(target_dir / safe_name)
        target.write_bytes(content)
        project_root = self.ensure_project_layout(project_id)
        return str(target.relative_to(project_root)).replace("\\", "/")

    def list_assets(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        self._sync_project_assets(project_id)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM project_assets
                WHERE project_id = ?
                ORDER BY updated_at DESC, filename ASC
                """,
                (project_id,),
            ).fetchall()
        return [self._project_asset_payload(row) for row in rows]

    def get_project_asset(self, project_id: str, storage_path: str) -> dict[str, Any] | None:
        normalized = storage_path.replace("\\", "/").lstrip("/")
        self._sync_project_assets(project_id)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_assets WHERE project_id = ? AND storage_path = ?",
                (project_id, normalized),
            ).fetchone()
        return self._project_asset_payload(row) if row else None

    def rename_asset(self, project_id: str, asset_path: str, filename: str) -> dict[str, Any]:
        normalized = asset_path.replace("\\", "/").lstrip("/")
        if not normalized.startswith("assets/"):
            raise ValueError(f"Asset path must be inside assets/: {asset_path}")
        path = self.resolve_project_file(project_id, normalized)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(asset_path)

        safe_name = self._safe_filename(filename)
        if not Path(safe_name).suffix and path.suffix:
            safe_name = f"{safe_name}{path.suffix}"

        self._ensure_project_asset_record(
            project_id,
            normalized,
            display_filename=path.name,
            asset_type=self._asset_type_for_path(normalized) or "unknown",
            size=path.stat().st_size,
        )
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE project_assets
                SET filename = ?, updated_at = ?
                WHERE project_id = ? AND storage_path = ?
                """,
                (safe_name, now, project_id, normalized),
            )
            row = conn.execute(
                "SELECT * FROM project_assets WHERE project_id = ? AND storage_path = ?",
                (project_id, normalized),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(asset_path)
        payload = self._project_asset_payload(row)
        payload["old_path"] = normalized
        return payload

    def resolve_project_file(self, project_id: str, relative_path: str) -> Path:
        self.get_project(project_id)
        project_root = self.ensure_project_layout(project_id).resolve()
        normalized = relative_path.replace("\\", "/").lstrip("/")
        candidate = (project_root / normalized).resolve()
        if candidate == project_root or not candidate.is_relative_to(project_root):
            raise ValueError(f"Path escapes project workspace: {relative_path}")
        return candidate

    def delete_project_file(self, project_id: str, relative_path: str) -> None:
        path = self.resolve_project_file(project_id, relative_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(relative_path)
        path.unlink()

    def _safe_filename(self, filename: str) -> str:
        name = filename.replace("\\", "/").split("/")[-1].strip() or "asset.bin"
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip()
        if name in {"", ".", ".."}:
            return "asset.bin"
        return name

    def _unique_path(self, target: Path) -> Path:
        if not target.exists():
            return target
        stem = target.stem
        suffix = target.suffix
        counter = 2
        while target.exists():
            target = target.with_name(f"{stem}_{counter}{suffix}")
            counter += 1
        return target

    def _asset_type_for_path(self, asset_path: str) -> str | None:
        normalized = asset_path.replace("\\", "/")
        if normalized.startswith("assets/images/"):
            return "image"
        if normalized.startswith("assets/audio/"):
            return "audio"
        if normalized.startswith("assets/videos/"):
            return "video"
        return None

    def _project_asset_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "path": row["storage_path"],
            "filename": row["filename"],
            "asset_type": row["asset_type"],
            "bytes": row["bytes"],
            "sha256": row["sha256"] if "sha256" in row.keys() else "",
            "mime_type": row["mime_type"] if "mime_type" in row.keys() else "",
            "updated_at": row["updated_at"],
        }

    def _sync_project_assets(self, project_id: str) -> None:
        project_root = self.ensure_project_layout(project_id).resolve()
        asset_dirs = {
            "image": project_root / "assets" / "images",
            "audio": project_root / "assets" / "audio",
            "video": project_root / "assets" / "videos",
        }
        for asset_type, directory in asset_dirs.items():
            if not directory.exists():
                continue
            for path in sorted(item for item in directory.iterdir() if item.is_file()):
                rel_path = str(path.relative_to(project_root)).replace("\\", "/")
                self._ensure_project_asset_record(
                    project_id,
                    rel_path,
                    display_filename=path.name,
                    asset_type=asset_type,
                    size=path.stat().st_size,
                )

    def _ensure_project_asset_record(
        self,
        project_id: str,
        storage_path: str,
        *,
        display_filename: str,
        asset_type: str,
        size: int,
        sha256: str = "",
    ) -> str:
        normalized = storage_path.replace("\\", "/").lstrip("/")
        now = datetime.now(timezone.utc).isoformat()
        if not sha256:
            source = self.resolve_project_file(project_id, normalized)
            if source.is_file():
                sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        mime_type = mimetypes.guess_type(display_filename)[0] or ""
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM project_assets WHERE project_id = ? AND storage_path = ?",
                (project_id, normalized),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE project_assets
                    SET bytes = ?, updated_at = ?, asset_type = ?, sha256 = ?, mime_type = ?
                    WHERE project_id = ? AND storage_path = ?
                    """,
                    (size, now, asset_type, sha256, mime_type, project_id, normalized),
                )
                return existing["id"]

            asset_id = new_id("asset")
            conn.execute(
                """
                INSERT INTO project_assets
                (id, project_id, storage_path, filename, asset_type, bytes, sha256,
                 mime_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    project_id,
                    normalized,
                    self._safe_filename(display_filename),
                    asset_type,
                    size,
                    sha256,
                    mime_type,
                    now,
                    now,
                ),
            )
            return asset_id

    def _dedupe_paths(self, paths: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for path in paths:
            normalized = str(path).replace("\\", "/").lstrip("/")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def get_project(self, project_id: str) -> Project:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        flags = json.loads(row["flags"])
        visibility_raw = row["visibility"] if "visibility" in row.keys() else "private"
        owner_id = row["owner_id"] if "owner_id" in row.keys() else None
        try:
            visibility = ProjectVisibility(visibility_raw or "private")
        except ValueError:
            visibility = ProjectVisibility.PRIVATE
        return Project(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            current_state=WorkflowState(row["current_state"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
            owner_id=owner_id,
            visibility=visibility,
            description=row["description"] if "description" in row.keys() else "",
            **flags,
        )

    def list_projects(self, include_deleted: bool = False, *, user_id: str | None = None, is_admin: bool = False) -> list[Project]:
        if is_admin or not user_id:
            query = "SELECT * FROM projects"
            params: tuple = ()
            if not include_deleted:
                query += " WHERE deleted_at IS NULL"
            query += " ORDER BY updated_at DESC"
            with self.connect() as conn:
                rows = conn.execute(query, params).fetchall()
        else:
            query = """
                SELECT DISTINCT p.*
                FROM projects p
                LEFT JOIN project_members pm ON pm.project_id = p.id AND pm.user_id = ?
                WHERE (pm.user_id IS NOT NULL OR p.visibility = 'public')
            """
            if not include_deleted:
                query += " AND p.deleted_at IS NULL"
            query += " ORDER BY p.updated_at DESC"
            with self.connect() as conn:
                rows = conn.execute(query, (user_id,)).fetchall()
        projects: list[Project] = []
        for row in rows:
            flags = json.loads(row["flags"])
            visibility_raw = row["visibility"] if "visibility" in row.keys() else "private"
            owner_id = row["owner_id"] if "owner_id" in row.keys() else None
            try:
                visibility = ProjectVisibility(visibility_raw or "private")
            except ValueError:
                visibility = ProjectVisibility.PRIVATE
            projects.append(
                Project(
                    id=row["id"],
                    name=row["name"],
                    category=row["category"],
                    current_state=WorkflowState(row["current_state"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
                    owner_id=owner_id,
                    visibility=visibility,
                    description=row["description"] if "description" in row.keys() else "",
                    **flags,
                )
            )
        return projects

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        category: str | None = None,
        description: str | None = None,
    ) -> Project:
        project = self.get_project(project_id)
        if name is not None:
            project.name = name
        if category is not None:
            project.category = category
        if description is not None:
            project.description = description.strip()
        project.updated_at = datetime.now(timezone.utc)
        return self.save_project(project)

    def delete_project(self, project_id: str) -> Project:
        project = self.get_project(project_id)
        project.deleted_at = datetime.now(timezone.utc)
        project.updated_at = project.deleted_at
        return self.save_project(project)

    def restore_project(self, project_id: str) -> Project:
        project = self.get_project(project_id)
        project.deleted_at = None
        project.updated_at = datetime.now(timezone.utc)
        return self.save_project(project)

    def save_document(self, document: Document) -> Document:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO documents
                (id, project_id, filename, format, content, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.id,
                    document.project_id,
                    document.filename,
                    document.format.value,
                    document.content,
                    json.dumps(document.metadata, ensure_ascii=False),
                    document.created_at.isoformat(),
                ),
            )
        return document

    def save_segments(self, segments: list[Segment]) -> list[Segment]:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO script_segments
                (id, document_id, order_index, content, is_converted)
                VALUES (?, ?, ?, ?, ?)
                """,
                [(s.id, s.document_id, s.order, s.content, int(s.is_script)) for s in segments],
            )
        return segments

    def save_scripts(self, scripts: list[Script]) -> list[Script]:
        # Scripts are currently persisted in the project workspace JSON by the API.
        # This method exists for the CLI contract and future normalized storage.
        return scripts

    def save_prompt_template(self, template: PromptTemplate) -> PromptTemplate:
        variables_json = json.dumps(template.variables, ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT template, variables, current_version FROM prompt_templates WHERE id = ?",
                (template.id,),
            ).fetchone()
            if existing is None:
                version = 1
                content_changed = True
            else:
                version = int(existing["current_version"] or 1)
                content_changed = existing["template"] != template.template or existing["variables"] != variables_json
                if content_changed:
                    row = conn.execute(
                        "SELECT COALESCE(MAX(version_index), 0) FROM prompt_template_versions WHERE template_id = ?",
                        (template.id,),
                    ).fetchone()
                    version = int(row[0]) + 1
            conn.execute(
                """
                INSERT INTO prompt_templates
                (id, name, category, template, variables, is_default, current_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    category = excluded.category,
                    template = excluded.template,
                    variables = excluded.variables,
                    is_default = excluded.is_default,
                    current_version = excluded.current_version
                """,
                (
                    template.id,
                    template.name,
                    template.category.value,
                    template.template,
                    variables_json,
                    int(template.is_default),
                    version,
                ),
            )
            if content_changed:
                conn.execute(
                    """
                    INSERT INTO prompt_template_versions
                    (id, template_id, version_index, template_text, variables, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (new_id("tplver"), template.id, version, template.template, variables_json, now),
                )
        template.version = version
        return template

    def list_prompt_templates(self) -> list[PromptTemplate]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM prompt_templates ORDER BY is_default DESC, name ASC").fetchall()
        templates: list[PromptTemplate] = []
        for row in rows:
            templates.append(
                PromptTemplate(
                    id=row["id"],
                    name=row["name"],
                    category=PromptCategory(row["category"]),
                    template=row["template"],
                    variables=json.loads(row["variables"]),
                    is_default=bool(row["is_default"]),
                    version=int(row["current_version"]) if "current_version" in row.keys() else 1,
                )
            )
        return templates

    def list_prompt_template_versions(self, template_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM prompt_templates WHERE id = ?", (template_id,)).fetchone() is None:
                raise KeyError(f"Prompt template not found: {template_id}")
            rows = conn.execute(
                """
                SELECT id, template_id, version_index, template_text, variables, created_at
                FROM prompt_template_versions
                WHERE template_id = ?
                ORDER BY version_index DESC
                """,
                (template_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "template_id": row["template_id"],
                "version": int(row["version_index"]),
                "template": row["template_text"],
                "variables": json.loads(row["variables"] or "[]"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def restore_prompt_template_version(self, template_id: str, version: int) -> PromptTemplate:
        current = next(
            (template for template in self.list_prompt_templates() if template.id == template_id),
            None,
        )
        if current is None:
            raise KeyError(f"Prompt template not found: {template_id}")
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT template_text, variables FROM prompt_template_versions
                WHERE template_id = ? AND version_index = ?
                """,
                (template_id, version),
            ).fetchone()
        if row is None:
            raise KeyError(f"Prompt template version not found: {template_id} v{version}")
        current.template = row["template_text"]
        current.variables = json.loads(row["variables"] or "[]")
        return self.save_prompt_template(current)

    def delete_prompt_template(self, template_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM prompt_template_versions WHERE template_id = ?", (template_id,))
            cursor = conn.execute("DELETE FROM prompt_templates WHERE id = ?", (template_id,))
            if cursor.rowcount == 0:
                raise KeyError(f"Prompt template not found: {template_id}")

    def save_entity_card(self, project_id: str, card: EntityCard) -> EntityCard:
        self.get_project(project_id)
        self.ensure_project_layout(project_id)
        card.project_id = project_id
        card.updated_at = datetime.now(timezone.utc)
        card.assets = self._dedupe_paths(
            [
                *card.assets,
                *card.reference_images,
                *card.audio_samples,
                *card.video_clips,
            ]
        )
        card.reference_images = self._dedupe_paths(
            [path for path in card.assets if self._asset_type_for_path(path) == "image"]
        )
        card.audio_samples = self._dedupe_paths(
            [path for path in card.assets if self._asset_type_for_path(path) == "audio"]
        )
        card.video_clips = self._dedupe_paths(
            [path for path in card.assets if self._asset_type_for_path(path) == "video"]
        )
        for asset_path in card.assets:
            normalized = asset_path.replace("\\", "/").lstrip("/")
            source = self.resolve_project_file(project_id, normalized)
            if not source.is_file():
                raise FileNotFoundError(asset_path)
            self._ensure_project_asset_record(
                project_id,
                normalized,
                display_filename=source.name,
                asset_type=self._asset_type_for_path(normalized) or "unknown",
                size=source.stat().st_size,
            )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO entity_cards
                (id, project_id, entity_name, type, state, reference_images, audio_samples,
                 video_clips, assets, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.id,
                    project_id,
                    card.entity_name,
                    card.type.value,
                    card.state,
                    json.dumps(card.reference_images, ensure_ascii=False),
                    json.dumps(card.audio_samples, ensure_ascii=False),
                    json.dumps(card.video_clips, ensure_ascii=False),
                    json.dumps(card.assets, ensure_ascii=False),
                    json.dumps(card.tags, ensure_ascii=False),
                    card.created_at.isoformat(),
                    card.updated_at.isoformat(),
                ),
            )
            self._sync_entity_card_materials(conn, project_id, card)
            self._sync_entity_card_asset_links(conn, project_id, card)
        self._sync_bundle_files(project_id)
        return card

    def list_entity_cards(self, project_id: str) -> list[EntityCard]:
        self.get_project(project_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entity_cards WHERE project_id = ? ORDER BY entity_name ASC, state ASC",
                (project_id,),
            ).fetchall()
        cards = [self._row_to_entity_card(row) for row in rows]
        self._hydrate_entity_card_assets(project_id, cards)
        return cards

    def refresh_entity_workflow_flags(self, project_id: str) -> Project:
        project = self.get_project(project_id)
        with self.connect() as conn:
            profile_row = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN linked_entity_card_id IS NOT NULL THEN 1 ELSE 0 END) AS linked "
                "FROM entity_profiles WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            card_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM entity_cards WHERE project_id = ?", (project_id,)
                ).fetchone()[0]
            )
        profile_count = int(profile_row["total"] or 0)
        linked_count = int(profile_row["linked"] or 0)
        project.has_entities = profile_count > 0 or card_count > 0
        project.has_bindings = profile_count > 0 and linked_count == profile_count
        project.current_state = self._derive_current_state(project)
        project.updated_at = datetime.now(timezone.utc)
        return self.save_project(project)

    def get_entity_card(self, project_id: str, card_id: str) -> EntityCard:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM entity_cards WHERE project_id = ? AND id = ?",
                (project_id, card_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Entity card not found: {card_id}")
        card = self._row_to_entity_card(row)
        self._hydrate_entity_card_assets(project_id, [card])
        return card

    def delete_entity_card(self, project_id: str, card_id: str) -> None:
        self.get_entity_card(project_id, card_id)
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM entity_material_links WHERE project_id = ? AND entity_card_id = ?",
                (project_id, card_id),
            )
            conn.execute("DELETE FROM entity_cards WHERE project_id = ? AND id = ?", (project_id, card_id))
        self._sync_bundle_files(project_id)

    def list_entity_materials(self, project_id: str) -> list[EntityMaterial]:
        self.get_project(project_id)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM entity_materials
                WHERE project_id = ?
                ORDER BY entity_name ASC, type ASC, created_at ASC
                """,
                (project_id,),
            ).fetchall()
        return [self._row_to_entity_material(row) for row in rows]

    def add_entity_materials(
        self,
        project_id: str,
        entity_name: str,
        entity_type: EntityType,
        asset_paths: list[str],
    ) -> list[EntityMaterial]:
        self.get_project(project_id)
        clean_name = entity_name.strip()
        if not clean_name:
            raise ValueError("Entity name is required")
        materials: list[EntityMaterial] = []
        created_at = datetime.now(timezone.utc)
        with self.connect() as conn:
            for asset_path in asset_paths:
                normalized = asset_path.replace("\\", "/").lstrip("/")
                if not normalized.startswith("assets/"):
                    raise ValueError(f"Asset path must be inside assets/: {asset_path}")
                resolved = self.resolve_project_file(project_id, normalized)
                if not resolved.exists() or not resolved.is_file():
                    raise FileNotFoundError(asset_path)
                material = EntityMaterial(
                    project_id=project_id,
                    entity_name=clean_name,
                    type=entity_type,
                    asset_path=normalized,
                    created_at=created_at,
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO entity_materials
                    (id, project_id, entity_name, type, asset_path, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        material.id,
                        project_id,
                        material.entity_name,
                        material.type.value,
                        material.asset_path,
                        material.created_at.isoformat(),
                    ),
                )
        return self.list_entity_materials(project_id)

    def delete_entity_material(self, project_id: str, material_id: str) -> None:
        self.get_project(project_id)
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM entity_materials WHERE project_id = ? AND id = ?",
                (project_id, material_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Entity material not found: {material_id}")

    def remove_entity_card_bindings(self, project_id: str, card_id: str) -> int:
        self.get_project(project_id)
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM prompt_card_entity_links WHERE project_id = ? AND entity_card_id = ?",
                (project_id, card_id),
            )
            removed_count = int(cursor.rowcount)
        if removed_count:
            self.upsert_preprocess(project_id, {"assets_confirmed": False}, bump_revision=True)
        return removed_count

    def remove_asset_references(self, project_id: str, asset_path: str) -> int:
        removed_count = 0
        for card in self.list_entity_cards(project_id):
            assets = [path for path in card.assets if path != asset_path]
            reference_images = [path for path in card.reference_images if path != asset_path]
            audio_samples = [path for path in card.audio_samples if path != asset_path]
            video_clips = [path for path in card.video_clips if path != asset_path]
            removed_from_card = int(
                asset_path
                in {
                    *card.assets,
                    *card.reference_images,
                    *card.audio_samples,
                    *card.video_clips,
                }
            )
            if removed_from_card == 0:
                continue
            card.assets = assets
            card.reference_images = reference_images
            card.audio_samples = audio_samples
            card.video_clips = video_clips
            self.save_entity_card(project_id, card)
            removed_count += removed_from_card
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM entity_materials WHERE project_id = ? AND asset_path = ?",
                (project_id, asset_path),
            )
            removed_count += cursor.rowcount
            conn.execute(
                "DELETE FROM project_assets WHERE project_id = ? AND storage_path = ?",
                (project_id, asset_path.replace("\\", "/").lstrip("/")),
            )
        return removed_count

    def replace_asset_references(self, project_id: str, old_path: str, new_path: str) -> int:
        updated_count = 0
        for card in self.list_entity_cards(project_id):
            changed = False
            for field_name in ("assets", "reference_images", "audio_samples", "video_clips"):
                values = getattr(card, field_name)
                next_values = [new_path if path == old_path else path for path in values]
                if next_values != values:
                    setattr(card, field_name, next_values)
                    changed = True
                    updated_count += 1
            if changed:
                self.save_entity_card(project_id, card)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE OR IGNORE entity_materials
                SET asset_path = ?
                WHERE project_id = ? AND asset_path = ?
                """,
                (new_path, project_id, old_path),
            )
            conn.execute(
                """
                DELETE FROM entity_materials
                WHERE project_id = ? AND asset_path = ?
                """,
                (project_id, old_path),
            )
            updated_count += cursor.rowcount
        return updated_count

    def _row_to_entity_card(self, row: sqlite3.Row) -> EntityCard:
        assets = json.loads(row["assets"]) if "assets" in row.keys() else []
        reference_images = json.loads(row["reference_images"])
        audio_samples = json.loads(row["audio_samples"])
        video_clips = json.loads(row["video_clips"])
        if not assets:
            assets = [*reference_images, *audio_samples, *video_clips]
        return EntityCard(
            id=row["id"],
            project_id=row["project_id"],
            entity_name=row["entity_name"],
            type=EntityType(row["type"]),
            state=row["state"],
            assets=assets,
            reference_images=reference_images,
            audio_samples=audio_samples,
            video_clips=video_clips,
            tags=json.loads(row["tags"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_entity_material(self, row: sqlite3.Row) -> EntityMaterial:
        return EntityMaterial(
            id=row["id"],
            project_id=row["project_id"],
            entity_name=row["entity_name"],
            type=EntityType(row["type"]),
            asset_path=row["asset_path"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _migrate_entity_card_assets_to_materials(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT * FROM entity_cards").fetchall()
        for row in rows:
            card = self._row_to_entity_card(row)
            self._sync_entity_card_materials(conn, row["project_id"], card)

    def _sync_entity_card_materials(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        card: EntityCard,
    ) -> None:
        clean_name = card.entity_name.strip()
        if not clean_name:
            return
        created_at = datetime.now(timezone.utc).isoformat()
        for asset_path in self._dedupe_paths(card.assets):
            normalized = asset_path.replace("\\", "/").lstrip("/")
            if not normalized.startswith("assets/"):
                continue
            resolved = self.resolve_project_file(project_id, normalized)
            if not resolved.exists() or not resolved.is_file():
                continue
            material = EntityMaterial(project_id=project_id, entity_name=clean_name, type=card.type, asset_path=normalized)
            conn.execute(
                """
                INSERT OR IGNORE INTO entity_materials
                (id, project_id, entity_name, type, asset_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    material.id,
                    project_id,
                    material.entity_name,
                    material.type.value,
                    material.asset_path,
                    created_at,
                ),
            )

    def _sync_entity_card_asset_links(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        card: EntityCard,
    ) -> None:
        conn.execute(
            "DELETE FROM entity_material_links WHERE project_id = ? AND entity_card_id = ?",
            (project_id, card.id),
        )
        created_at = datetime.now(timezone.utc).isoformat()
        for storage_path in self._dedupe_paths(card.assets):
            row = conn.execute(
                "SELECT id FROM project_assets WHERE project_id = ? AND storage_path = ?",
                (project_id, storage_path),
            ).fetchone()
            if row is None:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO entity_material_links
                (id, project_id, entity_card_id, project_asset_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id("eml"), project_id, card.id, row["id"], created_at),
            )

    def _hydrate_entity_card_assets(self, project_id: str, cards: list[EntityCard]) -> None:
        if not cards:
            return
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT link.entity_card_id, asset.storage_path, asset.asset_type
                FROM entity_material_links link
                JOIN project_assets asset ON asset.id = link.project_asset_id
                WHERE link.project_id = ?
                ORDER BY link.created_at, link.id
                """,
                (project_id,),
            ).fetchall()
        by_card: dict[str, list[tuple[str, str]]] = {}
        for row in rows:
            by_card.setdefault(row["entity_card_id"], []).append(
                (row["storage_path"], row["asset_type"])
            )
        for card in cards:
            linked = by_card.get(card.id)
            if linked is None:
                continue
            card.assets = [path for path, _ in linked]
            card.reference_images = [path for path, kind in linked if kind == "image"]
            card.audio_samples = [path for path, kind in linked if kind == "audio"]
            card.video_clips = [path for path, kind in linked if kind == "video"]

    def save_prompt_card(self, card: PromptCard) -> PromptCard:
        self.get_project(card.project_id)
        card.updated_at = datetime.now(timezone.utc)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO prompt_cards
                (id, project_id, segment_id, order_index, title, prompt_text, anchor_text,
                 duration, source_text, source_start, source_end, source_hash, status, locked, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.id,
                    card.project_id,
                    card.segment_id,
                    card.order,
                    card.title,
                    card.prompt_text,
                    card.anchor_text,
                    float(card.duration),
                    card.source_text,
                    int(card.source_start),
                    int(card.source_end),
                    card.source_hash,
                    card.status,
                    1 if card.locked else 0,
                    card.created_at.isoformat(),
                    card.updated_at.isoformat(),
                ),
            )
        self._refresh_structured_flags(card.project_id)
        self._sync_bundle_files(card.project_id)
        return card

    def append_prompt_card_version(self, card: PromptCard, version_type: str) -> dict[str, Any]:
        version_index = self.count_prompt_card_versions(card.id) + 1
        version_id = new_id("pcv")
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "id": version_id,
            "prompt_card_id": card.id,
            "version_index": version_index,
            "version_type": str(version_type or "generated").strip() or "generated",
            "title": card.title,
            "prompt_text": card.prompt_text,
            "anchor_text": card.anchor_text,
            "source_hash": card.source_hash,
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_card_versions
                (id, prompt_card_id, version_index, version_type, title, prompt_text, anchor_text, source_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["prompt_card_id"],
                    payload["version_index"],
                    payload["version_type"],
                    payload["title"],
                    payload["prompt_text"],
                    payload["anchor_text"],
                    payload["source_hash"],
                    payload["created_at"],
                ),
            )
        return payload

    def count_prompt_card_versions(self, prompt_card_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM prompt_card_versions WHERE prompt_card_id = ?",
                (prompt_card_id,),
            ).fetchone()
        return int(row["total"] or 0) if row else 0

    def list_prompt_card_versions(self, prompt_card_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, prompt_card_id, version_index, version_type, title, prompt_text, anchor_text, source_hash, created_at
                FROM prompt_card_versions
                WHERE prompt_card_id = ?
                ORDER BY version_index ASC
                """,
                (prompt_card_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "prompt_card_id": row["prompt_card_id"],
                "version_index": int(row["version_index"]),
                "version_type": row["version_type"],
                "title": row["title"],
                "prompt_text": row["prompt_text"],
                "anchor_text": row["anchor_text"],
                "source_hash": row["source_hash"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_prompt_card_with_version(self, card: PromptCard, version_type: str | None = None) -> PromptCard:
        existing: PromptCard | None = None
        try:
            existing = self.get_prompt_card(card.id)
        except KeyError:
            existing = None
        saved = self.save_prompt_card(card)
        should_record = existing is None
        if existing is not None:
            text_changed = (
                existing.prompt_text != card.prompt_text
                or existing.anchor_text != card.anchor_text
                or existing.title != card.title
            )
            should_record = text_changed or version_type in {"rerun", "generated"}
        if should_record:
            inferred = version_type or ("edited" if card.status == "edited" else "generated")
            self.append_prompt_card_version(saved, inferred)
        return saved

    def save_prompt_cards(
        self,
        project_id: str,
        segment_id: str,
        cards: list[PromptCard],
        *,
        replace: bool = False,
    ) -> list[PromptCard]:
        self.get_project(project_id)
        now = datetime.now(timezone.utc)
        existing_locked = [card for card in self.list_prompt_cards(project_id, segment_id) if card.locked] if replace else []
        cards_to_save = self._merge_locked_prompt_cards(existing_locked, cards) if replace else cards
        with self.connect() as conn:
            if replace:
                conn.execute(
                    "DELETE FROM prompt_cards WHERE project_id = ? AND segment_id = ? AND locked = 0",
                    (project_id, segment_id),
                )
            start_index = 1
            if not replace:
                row = conn.execute(
                    "SELECT COALESCE(MAX(order_index), 0) AS max_order FROM prompt_cards WHERE project_id = ? AND segment_id = ?",
                    (project_id, segment_id),
                ).fetchone()
                start_index = int(row["max_order"] or 0) + 1
            for index, card in enumerate(cards_to_save, start_index):
                card.project_id = project_id
                card.segment_id = segment_id
                card.order = index
                card.updated_at = now
                conn.execute(
                    """
                    INSERT OR REPLACE INTO prompt_cards
                    (id, project_id, segment_id, order_index, title, prompt_text, anchor_text,
                     duration, source_text, source_start, source_end, source_hash, status, locked, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card.id,
                        project_id,
                        segment_id,
                        card.order,
                        card.title,
                        card.prompt_text,
                        card.anchor_text,
                        float(card.duration),
                        card.source_text,
                        int(card.source_start),
                        int(card.source_end),
                        card.source_hash,
                        card.status,
                        1 if card.locked else 0,
                        card.created_at.isoformat(),
                        card.updated_at.isoformat(),
                    ),
                )
        self._refresh_structured_flags(project_id)
        saved = self.list_prompt_cards(project_id, segment_id)
        saved_by_id = {item.id: item for item in saved}
        for card in cards_to_save:
            if card.locked and replace:
                continue
            current = saved_by_id.get(card.id)
            if current and (replace or self.count_prompt_card_versions(card.id) == 0):
                self.append_prompt_card_version(current, "generated")
        self._sync_bundle_files(project_id)
        return saved

    def import_assets_from_source_root(self, project_id: str, source_root: str) -> dict[str, int]:
        root = Path(str(source_root or "").strip()).expanduser()
        if not root.is_absolute():
            root = (self.workspace_root / root).resolve()
        if not root.is_dir():
            raise ValueError(f"原始素材目录不存在：{root}")

        image_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        audio_ext = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
        video_ext = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
        imported = {"image": 0, "audio": 0, "video": 0}

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext in image_ext:
                asset_type = "image"
            elif ext in audio_ext:
                asset_type = "audio"
            elif ext in video_ext:
                asset_type = "video"
            else:
                continue
            self.save_asset(project_id, asset_type, path.name, path.read_bytes())
            imported[asset_type] += 1
        return {
            "imported": sum(imported.values()),
            "by_type": imported,
        }

    def _merge_locked_prompt_cards(self, locked_cards: list[PromptCard], incoming_cards: list[PromptCard]) -> list[PromptCard]:
        if not locked_cards:
            return incoming_cards
        locked_by_order: dict[int, list[PromptCard]] = {}
        for card in sorted(locked_cards, key=lambda item: (item.order, item.created_at.isoformat(), item.id)):
            locked_by_order.setdefault(max(1, int(card.order or 1)), []).append(card)

        merged: list[PromptCard] = []
        incoming_index = 0
        max_order = max(max(locked_by_order), len(locked_cards) + len(incoming_cards))
        for order in range(1, max_order + 1):
            if order in locked_by_order:
                merged.extend(locked_by_order[order])
            elif incoming_index < len(incoming_cards):
                merged.append(incoming_cards[incoming_index])
                incoming_index += 1
        while incoming_index < len(incoming_cards):
            merged.append(incoming_cards[incoming_index])
            incoming_index += 1
        return merged

    def list_prompt_cards(self, project_id: str, segment_id: str | None = None) -> list[PromptCard]:
        self.get_project(project_id)
        query = "SELECT * FROM prompt_cards WHERE project_id = ?"
        params: tuple[Any, ...] = (project_id,)
        if segment_id:
            query += " AND segment_id = ?"
            params = (project_id, segment_id)
        query += " ORDER BY segment_id ASC, order_index ASC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_prompt_card(row) for row in rows]

    def get_prompt_card(self, card_id: str) -> PromptCard:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM prompt_cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise KeyError(f"Prompt card not found: {card_id}")
        return self._row_to_prompt_card(row)

    def delete_prompt_card(self, card_id: str) -> None:
        card = self.get_prompt_card(card_id)
        with self.connect() as conn:
            conn.execute("DELETE FROM prompt_card_entity_links WHERE prompt_card_id = ?", (card_id,))
            conn.execute("DELETE FROM prompt_cards WHERE id = ?", (card_id,))
        self._refresh_structured_flags(card.project_id)
        self._sync_bundle_files(card.project_id)

    def replace_prompt_card_entity_links(
        self,
        project_id: str,
        prompt_card_id: str,
        entity_card_ids: list[str],
        *,
        source: str,
        confirmed: bool,
    ) -> list[dict[str, Any]]:
        card = self.get_prompt_card(prompt_card_id)
        if card.project_id != project_id:
            raise KeyError(f"Prompt card not found in project: {prompt_card_id}")
        clean_ids = list(dict.fromkeys(str(item).strip() for item in entity_card_ids if str(item).strip()))
        available = {item.id for item in self.list_entity_cards(project_id)}
        missing = [item for item in clean_ids if item not in available]
        if missing:
            raise KeyError(f"Entity cards not found: {', '.join(missing)}")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM prompt_card_entity_links WHERE project_id = ? AND prompt_card_id = ?",
                (project_id, prompt_card_id),
            )
            for entity_card_id in clean_ids:
                conn.execute(
                    """
                    INSERT INTO prompt_card_entity_links
                    (id, project_id, prompt_card_id, entity_card_id, source, confidence,
                     confirmed, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        new_id("pcel"), project_id, prompt_card_id, entity_card_id,
                        source, int(confirmed), now, now,
                    ),
                )
        return self.list_prompt_card_entity_links(project_id, prompt_card_id)

    def list_prompt_card_entity_links(
        self, project_id: str, prompt_card_id: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM prompt_card_entity_links WHERE project_id = ?"
        params: tuple[Any, ...] = (project_id,)
        if prompt_card_id:
            query += " AND prompt_card_id = ?"
            params = (project_id, prompt_card_id)
        query += " ORDER BY created_at, id"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def prompt_card_entity_ids(self, project_id: str, prompt_card_id: str) -> list[str]:
        return [
            str(item["entity_card_id"])
            for item in self.list_prompt_card_entity_links(project_id, prompt_card_id)
        ]

    def _row_to_prompt_card(self, row: sqlite3.Row) -> PromptCard:
        return PromptCard(
            id=row["id"],
            project_id=row["project_id"],
            segment_id=row["segment_id"],
            order=row["order_index"],
            title=row["title"],
            prompt_text=row["prompt_text"],
            anchor_text=row["anchor_text"],
            duration=float(row["duration"]),
            source_text=row["source_text"],
            source_start=int(row["source_start"] or 0),
            source_end=int(row["source_end"] or 0),
            source_hash=row["source_hash"],
            status=row["status"],
            locked=bool(row["locked"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _has_prompt_cards(self, project_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM prompt_cards WHERE project_id = ? AND TRIM(prompt_text) != '' LIMIT 1",
                (project_id,),
            ).fetchone()
        return row is not None

    def _refresh_structured_flags(self, project_id: str) -> None:
        project = self.get_project(project_id)
        with self.connect() as conn:
            project.has_bindings = conn.execute(
                "SELECT 1 FROM prompt_card_entity_links WHERE project_id = ? AND confirmed = 1 LIMIT 1",
                (project_id,),
            ).fetchone() is not None
        project.has_prompts = self._has_prompt_cards(project_id)
        project.current_state = self._derive_current_state(project)
        project.updated_at = datetime.now(timezone.utc)
        self.save_project(project)

    def save_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO checkpoints (id, project_id, state, data, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    checkpoint.id,
                    checkpoint.project_id,
                    checkpoint.state.value,
                    json.dumps(checkpoint.data, ensure_ascii=False, default=str),
                    checkpoint.created_at.isoformat(),
                ),
            )
        return checkpoint

    def list_checkpoints(self, project_id: str) -> list[Checkpoint]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM checkpoints WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,),
            ).fetchall()
        return [self._row_to_checkpoint(row) for row in rows]

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
        if row is None:
            raise KeyError(f"Checkpoint not found: {checkpoint_id}")
        return self._row_to_checkpoint(row)

    def latest_checkpoint(self, project_id: str, state: WorkflowState | None = None) -> Checkpoint | None:
        query = "SELECT * FROM checkpoints WHERE project_id = ?"
        params: tuple[Any, ...] = (project_id,)
        if state:
            query += " AND state = ?"
            params = (project_id, state.value)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return self._row_to_checkpoint(row) if row else None

    def restore_checkpoint(self, checkpoint_id: str) -> Project:
        checkpoint = self.get_checkpoint(checkpoint_id)
        project = self.get_project(checkpoint.project_id)
        data = checkpoint.data
        project.current_state = WorkflowState(str(data.get("current_state", checkpoint.state.value)))
        for name in self._project_flags(project):
            if name in data:
                setattr(project, name, bool(data[name]))
        project.updated_at = datetime.now(timezone.utc)
        return self.save_project(project)

    def _row_to_checkpoint(self, row: sqlite3.Row) -> Checkpoint:
        return Checkpoint(
            id=row["id"],
            project_id=row["project_id"],
            state=WorkflowState(row["state"]),
            data=json.loads(row["data"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_video_task(self, task: VideoTask) -> VideoTask:
        self.get_project(task.project_id)
        self.ensure_project_layout(task.project_id)
        task.updated_at = datetime.now(timezone.utc)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO video_tasks
                (id, project_id, segment_id, prompt, assets, duration, status, result_path, api_task_id,
                 provider, prompt_card_id, source_prompt_hash, is_preview, version, prompt_version,
                 request_snapshot, attempt, orphaned, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.project_id,
                    task.segment_id,
                    task.prompt,
                    json.dumps(task.assets, ensure_ascii=False, default=str),
                    task.duration,
                    task.status.value,
                    task.result_path,
                    task.api_task_id,
                    task.provider or "mock",
                    task.prompt_card_id,
                    task.source_prompt_hash,
                    int(task.is_preview),
                    task.version,
                    int(getattr(task, "prompt_version", None) or 1),
                    json.dumps(task.request_snapshot, ensure_ascii=False, default=str),
                    int(task.attempt or 0),
                    int(task.orphaned),
                    task.error_message,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )
        return task

    def get_video_task(self, task_id: str) -> VideoTask:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM video_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Video task not found: {task_id}")
        return self._row_to_video_task(row)

    def list_video_tasks(self, project_id: str, segment_id: str | None = None) -> list[VideoTask]:
        self.get_project(project_id)
        query = "SELECT * FROM video_tasks WHERE project_id = ?"
        params: tuple[Any, ...] = (project_id,)
        if segment_id:
            query += " AND segment_id = ?"
            params = (project_id, segment_id)
        query += " ORDER BY created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_video_task(row) for row in rows]

    def list_incomplete_video_tasks(self) -> list[VideoTask]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM video_tasks WHERE status IN (?, ?) ORDER BY created_at ASC",
                (TaskStatus.PENDING.value, TaskStatus.PROCESSING.value),
            ).fetchall()
        return [self._row_to_video_task(row) for row in rows]

    def delete_video_task(self, task_id: str) -> None:
        task = self.get_video_task(task_id)
        if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            raise ValueError(f"Only completed or failed tasks can be deleted: {task.status.value}")
        with self.connect() as conn:
            conn.execute("DELETE FROM video_outputs WHERE video_task_id = ?", (task_id,))
            conn.execute("DELETE FROM video_tasks WHERE id = ?", (task_id,))

    def record_video_output(self, task: VideoTask) -> VideoOutput:
        """Persist a completed task result once, without adopting it implicitly."""
        if task.status != TaskStatus.COMPLETED or not str(task.result_path or "").strip():
            raise ValueError("Only completed video tasks with a result can become outputs")
        stored_task = self.get_video_task(task.id)
        if stored_task.project_id != task.project_id:
            raise ValueError("Video task project mismatch")
        storage_path = str(task.result_path).strip()
        metadata = {
            "provider": task.provider,
            "api_task_id": task.api_task_id,
            "version": task.version,
            "prompt_version": task.prompt_version,
            "duration": task.duration,
            "is_preview": task.is_preview,
        }
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM video_outputs WHERE video_task_id = ? AND storage_path = ?",
                (task.id, storage_path),
            ).fetchone()
            if existing is None:
                output = VideoOutput(
                    project_id=task.project_id,
                    video_task_id=task.id,
                    prompt_card_id=task.prompt_card_id,
                    storage_path=storage_path,
                    metadata=metadata,
                )
                conn.execute(
                    """
                    INSERT INTO video_outputs
                    (id, project_id, video_task_id, prompt_card_id, storage_path, metadata, adopted, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        output.id,
                        output.project_id,
                        output.video_task_id,
                        output.prompt_card_id,
                        output.storage_path,
                        json.dumps(output.metadata, ensure_ascii=False),
                        int(output.adopted),
                        output.created_at.isoformat(),
                    ),
                )
                return output
        return self._row_to_video_output(existing)

    def list_video_outputs(
        self, project_id: str, prompt_card_id: str | None = None
    ) -> list[VideoOutput]:
        self.get_project(project_id)
        query = "SELECT * FROM video_outputs WHERE project_id = ?"
        params: tuple[Any, ...] = (project_id,)
        if prompt_card_id:
            query += " AND prompt_card_id = ?"
            params = (project_id, prompt_card_id)
        query += " ORDER BY adopted DESC, created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_video_output(row) for row in rows]

    def adopt_video_output(self, project_id: str, output_id: str) -> VideoOutput:
        """Atomically select one output per PromptCard."""
        self.get_project(project_id)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM video_outputs WHERE id = ? AND project_id = ?",
                (output_id, project_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"Video output not found in project: {output_id}")
            prompt_card_id = str(row["prompt_card_id"] or "").strip()
            if not prompt_card_id:
                raise ValueError("Video output is not linked to a prompt card")
            conn.execute(
                "UPDATE video_outputs SET adopted = 0 WHERE project_id = ? AND prompt_card_id = ?",
                (project_id, prompt_card_id),
            )
            conn.execute("UPDATE video_outputs SET adopted = 1 WHERE id = ?", (output_id,))
            adopted = conn.execute("SELECT * FROM video_outputs WHERE id = ?", (output_id,)).fetchone()
        return self._row_to_video_output(adopted)

    def _row_to_video_output(self, row: sqlite3.Row) -> VideoOutput:
        return VideoOutput(
            id=row["id"],
            project_id=row["project_id"],
            video_task_id=row["video_task_id"],
            prompt_card_id=row["prompt_card_id"] if "prompt_card_id" in row.keys() else None,
            storage_path=row["storage_path"],
            metadata=json.loads(row["metadata"] or "{}"),
            adopted=bool(row["adopted"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def next_video_task_version(self, project_id: str, segment_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS max_version FROM video_tasks WHERE project_id = ? AND segment_id = ?",
                (project_id, segment_id),
            ).fetchone()
        return int(row["max_version"]) + 1

    def _has_completed_video_task(self, project_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM video_tasks WHERE project_id = ? AND status = ? AND is_preview = 0 LIMIT 1",
                (project_id, TaskStatus.COMPLETED.value),
            ).fetchone()
        return row is not None

    def _row_to_video_task(self, row: sqlite3.Row) -> VideoTask:
        return VideoTask(
            id=row["id"],
            project_id=row["project_id"],
            segment_id=row["segment_id"],
            prompt=row["prompt"],
            assets=json.loads(row["assets"]),
            duration=row["duration"],
            prompt_card_id=row["prompt_card_id"] if "prompt_card_id" in row.keys() else None,
            source_prompt_hash=row["source_prompt_hash"] if "source_prompt_hash" in row.keys() else "",
            status=TaskStatus(row["status"]),
            result_path=row["result_path"],
            api_task_id=row["api_task_id"],
            provider=row["provider"] if "provider" in row.keys() and row["provider"] else "mock",
            is_preview=bool(row["is_preview"]),
            version=row["version"],
            prompt_version=int(row["prompt_version"]) if "prompt_version" in row.keys() else 1,
            request_snapshot=(
                json.loads(row["request_snapshot"] or "{}")
                if "request_snapshot" in row.keys()
                else {}
            ),
            attempt=int(row["attempt"] or 0) if "attempt" in row.keys() else 0,
            orphaned=bool(row["orphaned"]) if "orphaned" in row.keys() else False,
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def mark_video_tasks_orphaned(self, project_id: str, keep_segment_ids: set[str] | list[str] | None = None) -> int:
        keep = {str(item) for item in (keep_segment_ids or []) if str(item)}
        tasks = self.list_video_tasks(project_id)
        updated = 0
        for task in tasks:
            should_orphan = task.segment_id not in keep if keep else True
            if should_orphan and not task.orphaned:
                task.orphaned = True
                self.save_video_task(task)
                updated += 1
            elif not should_orphan and task.orphaned:
                task.orphaned = False
                self.save_video_task(task)
                updated += 1
        return updated

    def replace_project_document_segments(
        self,
        *,
        project_id: str,
        document: Document,
        segments: list[Segment],
    ) -> tuple[Document, list[Segment]]:
        self.get_project(project_id)
        document.project_id = project_id
        with self.connect() as conn:
            old_docs = conn.execute(
                "SELECT id FROM documents WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            old_ids = [row["id"] for row in old_docs]
            if old_ids:
                placeholders = ",".join("?" for _ in old_ids)
                conn.execute(
                    f"DELETE FROM script_segments WHERE document_id IN ({placeholders})",
                    old_ids,
                )
                conn.execute(
                    f"DELETE FROM documents WHERE id IN ({placeholders})",
                    old_ids,
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO documents
                (id, project_id, filename, format, content, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.id,
                    document.project_id,
                    document.filename,
                    document.format.value,
                    document.content,
                    json.dumps(document.metadata, ensure_ascii=False),
                    document.created_at.isoformat(),
                ),
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO script_segments
                (id, document_id, order_index, content, is_converted)
                VALUES (?, ?, ?, ?, ?)
                """,
                [(s.id, s.document_id, s.order, s.content, int(s.is_script)) for s in segments],
            )
        return document, segments

    def get_preprocess(self, project_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_preprocess WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        doc_file = json.loads(row["document_file"]) if row["document_file"] else {}
        return {
            "project_id": row["project_id"],
            "document_text": row["document_text"],
            "split_strategy": row["split_strategy"],
            "custom_split_pattern": row["custom_split_pattern"],
            "duration_minutes": row["duration_minutes"],
            "document_file": doc_file if isinstance(doc_file, dict) else {},
            "active_segment_id": row["active_segment_id"],
            "content_type": row["content_type"] if "content_type" in row.keys() else "分集原文",
            "script_convert_template_id": row["script_convert_template_id"] if "script_convert_template_id" in row.keys() else "",
            "project_style_prompt": row["project_style_prompt"] if "project_style_prompt" in row.keys() else "",
            "expected_total_duration_seconds": row["expected_total_duration_seconds"],
            "default_aspect_ratio": row["default_aspect_ratio"],
            "default_video_duration": row["default_video_duration"],
            "default_video_model": row["default_video_model"],
            "default_resolution": row["default_resolution"],
            "output_root": row["output_root"] if "output_root" in row.keys() else "",
            "source_assets_root": row["source_assets_root"] if "source_assets_root" in row.keys() else "",
            "data_root": row["data_root"] if "data_root" in row.keys() else "",
            "assets_confirmed": bool(row["assets_confirmed"]),
            "revision": int(row["revision"]),
            "migrated_from_blob": bool(row["migrated_from_blob"]),
            "updated_at": row["updated_at"],
        }

    def upsert_preprocess(self, project_id: str, patch: dict[str, Any], *, bump_revision: bool = True) -> dict[str, Any]:
        self.get_project(project_id)
        current = self.get_preprocess(project_id) or {
            "project_id": project_id,
            "document_text": "",
            "split_strategy": "chapter",
            "custom_split_pattern": "",
            "duration_minutes": 2.0,
            "document_file": {},
            "active_segment_id": "",
            "content_type": "分集原文",
            "script_convert_template_id": "",
            "project_style_prompt": "",
            "expected_total_duration_seconds": None,
            "default_aspect_ratio": "9:16",
            "default_video_duration": 5,
            "default_video_model": "",
            "default_resolution": "720p",
            "output_root": "",
            "source_assets_root": "",
            "data_root": "",
            "assets_confirmed": False,
            "revision": 0,
            "migrated_from_blob": False,
        }
        next_row = {**current, **patch}
        revision = int(next_row.get("revision") or 0)
        if bump_revision:
            revision += 1
        document_file = next_row.get("document_file")
        if not isinstance(document_file, dict):
            document_file = {}
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO project_preprocess (
                    project_id, document_text, split_strategy, custom_split_pattern, duration_minutes,
                    document_file, active_segment_id, content_type, script_convert_template_id, project_style_prompt,
                    expected_total_duration_seconds,
                    default_aspect_ratio, default_video_duration, default_video_model, default_resolution,
                    output_root, source_assets_root, data_root,
                    assets_confirmed, revision, migrated_from_blob, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    str(next_row.get("document_text") or ""),
                    str(next_row.get("split_strategy") or "chapter"),
                    str(next_row.get("custom_split_pattern") or ""),
                    float(next_row.get("duration_minutes") or 2),
                    json.dumps(document_file, ensure_ascii=False),
                    str(next_row.get("active_segment_id") or ""),
                    str(next_row.get("content_type") or "分集原文"),
                    str(next_row.get("script_convert_template_id") or ""),
                    str(next_row.get("project_style_prompt") or ""),
                    next_row.get("expected_total_duration_seconds"),
                    str(next_row.get("default_aspect_ratio") or "9:16"),
                    int(next_row.get("default_video_duration") or 5),
                    str(next_row.get("default_video_model") or ""),
                    str(next_row.get("default_resolution") or "720p"),
                    str(next_row.get("output_root") or ""),
                    str(next_row.get("source_assets_root") or ""),
                    str(next_row.get("data_root") or ""),
                    int(bool(next_row.get("assets_confirmed"))),
                    revision,
                    int(bool(next_row.get("migrated_from_blob"))),
                    now,
                ),
            )
        self._sync_bundle_files(project_id)
        return self.get_preprocess(project_id) or {}

    def get_project_style_prompt(self, project_id: str) -> str:
        preprocess = self.get_preprocess(project_id) or {}
        return str(preprocess.get("project_style_prompt") or "").strip()

    def bump_preprocess_revision(self, project_id: str) -> None:
        current = self.get_preprocess(project_id) or {}
        self.upsert_preprocess(project_id, current, bump_revision=True)

    def list_project_segments(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, project_id, order_index, title, source_text AS content, metadata
                FROM episodes
                WHERE project_id = ?
                ORDER BY order_index ASC
                """,
                (project_id,),
            ).fetchall()
        segments: list[dict[str, Any]] = []
        for row in rows:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            item = {
                "id": row["id"],
                "order": row["order_index"],
                "title": row["title"],
                "content": row["content"],
            }
            if isinstance(metadata, dict):
                item.update(metadata)
            segments.append(item)
        return segments

    def replace_project_segments(self, project_id: str, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.get_project(project_id)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            existing_rows = conn.execute(
                "SELECT * FROM episodes WHERE project_id = ?", (project_id,)
            ).fetchall()
            existing = {row["id"]: row for row in existing_rows}
            keep_ids = {str(segment["id"]) for segment in segments}
            if keep_ids:
                placeholders = ",".join("?" for _ in keep_ids)
                conn.execute(
                    f"DELETE FROM episodes WHERE project_id = ? AND id NOT IN ({placeholders})",
                    (project_id, *keep_ids),
                )
            else:
                conn.execute("DELETE FROM episodes WHERE project_id = ?", (project_id,))
            for index, segment in enumerate(segments, start=1):
                conn.execute(
                    "UPDATE episodes SET order_index = ? WHERE project_id = ? AND id = ?",
                    (-index, project_id, str(segment["id"])),
                )
            for segment in segments:
                metadata = {
                    key: value
                    for key, value in segment.items()
                    if key not in {"id", "order", "title", "content"}
                }
                previous = existing.get(str(segment["id"]))
                conn.execute(
                    """
                    INSERT INTO episodes
                    (id, project_id, document_id, order_index, title, source_text, script_text,
                     metadata, script_validation, source_start, source_end, status, revision,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        order_index=excluded.order_index,
                        title=excluded.title,
                        source_text=excluded.source_text,
                        metadata=excluded.metadata,
                        source_end=excluded.source_end,
                        revision=episodes.revision + 1,
                        updated_at=excluded.updated_at
                    """,
                    (
                        segment["id"],
                        project_id,
                        previous["document_id"] if previous else None,
                        int(segment["order"]),
                        str(segment.get("title") or f"第{segment['order']}集"),
                        str(segment.get("content") or ""),
                        previous["script_text"] if previous else "",
                        json.dumps(metadata, ensure_ascii=False),
                        previous["script_validation"] if previous else "{}",
                        len(str(segment.get("content") or "")),
                        previous["status"] if previous else "source_ready",
                        int(previous["revision"]) if previous else 0,
                        previous["created_at"] if previous else now,
                        now,
                    ),
                )
        return self.list_project_segments(project_id)

    def list_project_scripts(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id AS segment_id, project_id, script_text AS content,
                       script_validation AS validation
                FROM episodes
                WHERE project_id = ? AND (script_text <> '' OR script_validation <> '{}')
                """,
                (project_id,),
            ).fetchall()
        scripts: list[dict[str, Any]] = []
        for row in rows:
            validation = json.loads(row["validation"]) if row["validation"] else {}
            scripts.append(
                {
                    "segment_id": row["segment_id"],
                    "content": row["content"],
                    "validation": validation if isinstance(validation, dict) else {},
                }
            )
        return scripts

    def upsert_project_script(
        self,
        project_id: str,
        segment_id: str,
        content: str,
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE episodes
                SET script_text = ?, script_validation = ?,
                    status = CASE WHEN trim(?) <> '' THEN 'script_ready' ELSE 'source_ready' END,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (
                    content,
                    json.dumps(validation, ensure_ascii=False, default=str),
                    content,
                    now,
                    segment_id,
                    project_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Segment not found: {segment_id}")
        return {"segment_id": segment_id, "content": content, "validation": validation}

    def clear_project_scripts(self, project_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE episodes SET script_text = '', script_validation = '{}',
                    status = 'source_ready', revision = revision + 1, updated_at = ?
                WHERE project_id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), project_id),
            )

    def clear_project_prompt_cards(self, project_id: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM prompt_cards WHERE project_id = ?", (project_id,))
        return int(cursor.rowcount)

    def get_workspace_blob(self, project_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'project_workspaces'"
            ).fetchone()
            if exists is None:
                return {}
            row = conn.execute(
                "SELECT data FROM project_workspaces WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            return {}
        return json.loads(row["data"])

    def delete_workspace_blob(self, project_id: str) -> None:
        with self.connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'project_workspaces'"
            ).fetchone()
            if exists is not None:
                conn.execute("DELETE FROM project_workspaces WHERE project_id = ?", (project_id,))

    def drop_legacy_workspace_table(self) -> None:
        with self.connect() as conn:
            conn.execute("DROP TABLE IF EXISTS project_workspaces")

    def get_workspace(self, project_id: str) -> dict[str, Any]:
        from ai_video_manager.project_domain import ProjectDomainService

        return ProjectDomainService(self).get_workspace_view(project_id)

    def _sync_project_flags_from_workspace(self, project: Project, data: dict[str, Any]) -> None:
        document_text = str(data.get("documentText") or "").strip()
        segments = data.get("segments") if isinstance(data.get("segments"), list) else []
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        script_validation = data.get("scriptValidation") if isinstance(data.get("scriptValidation"), dict) else {}
        entities = data.get("entities") if isinstance(data.get("entities"), list) else []
        prompts = data.get("prompts") if isinstance(data.get("prompts"), dict) else {}
        video_tasks = data.get("videoTasks") if isinstance(data.get("videoTasks"), list) else []

        confirmed_entities = [
            entity for entity in entities if isinstance(entity, dict) and bool(entity.get("confirmed"))
        ]
        completed_tasks = [
            task
            for task in video_tasks
            if isinstance(task, dict)
            and task.get("status") == TaskStatus.COMPLETED.value
            and not bool(task.get("is_preview"))
        ]

        project.has_document = bool(document_text)
        project.has_segments = bool(segments)
        project.has_scripts = self._workspace_scripts_ready(segments, scripts, script_validation)
        project.has_entities = bool(entities)
        project.has_bindings = (
            (bool(entities) and len(confirmed_entities) == len(entities))
        )
        project.has_prompts = any(bool(str(value).strip()) for value in prompts.values()) or self._has_prompt_cards(project.id)
        project.assets_confirmed = bool(data.get("assetsConfirmed"))
        project.has_completed_video = bool(completed_tasks) or self._has_completed_video_task(project.id)
        project.current_state = self._derive_current_state(project)

    def _derive_current_state(self, project: Project) -> WorkflowState:
        if project.has_completed_video:
            return WorkflowState.VIDEO_COMPLETED
        if project.has_prompts and project.assets_confirmed:
            return WorkflowState.ASSETS_CONFIRMED
        if project.has_prompts:
            return WorkflowState.PROMPTS_GENERATED
        if project.has_bindings:
            return WorkflowState.ENTITIES_BOUND
        if project.has_entities:
            return WorkflowState.ENTITIES_EXTRACTED
        if project.has_scripts:
            return WorkflowState.SCRIPT_CONVERTED
        if project.has_segments:
            return WorkflowState.DOCUMENT_SPLIT
        return WorkflowState.INITIALIZED

    def _workspace_scripts_ready(
        self,
        segments: list[Any],
        scripts: dict[str, Any],
        script_validation: dict[str, Any],
    ) -> bool:
        if not segments:
            return False
        for segment in segments:
            if not isinstance(segment, dict):
                return False
            segment_id = str(segment.get("id") or "")
            if not segment_id or not str(scripts.get(segment_id) or "").strip():
                return False
        return True

    def get_setting(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default or {}
        return json.loads(row["value"])

    def save_setting(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (
                    key,
                    json.dumps(value, ensure_ascii=False, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return value

    def get_user_setting(self, user_id: str, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
                (user_id, key),
            ).fetchone()
        if row is None:
            return default or {}
        return json.loads(row["value"])

    def save_user_setting(self, user_id: str, key: str, value: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO user_settings (user_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    key,
                    json.dumps(value, ensure_ascii=False, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return value

    def record_command_operation(
        self,
        *,
        operation_id: str,
        command_id: str,
        source: str,
        project_id: str | None,
        user_id: str | None,
        arguments: dict[str, Any],
        status: str,
        result: Any,
        error_message: str,
        started_at: str,
    ) -> None:
        completed_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO command_operations
                (operation_id, command_id, source, project_id, user_id, arguments_json,
                 status, result_json, error_message, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    command_id,
                    source,
                    project_id,
                    user_id,
                    json.dumps(arguments, ensure_ascii=False),
                    status,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error_message,
                    started_at,
                    completed_at,
                ),
            )

    def _project_flags(self, project: Project) -> dict[str, bool]:
        return {
            "has_document": project.has_document,
            "has_segments": project.has_segments,
            "has_scripts": project.has_scripts,
            "has_entities": project.has_entities,
            "has_bindings": project.has_bindings,
            "has_prompts": project.has_prompts,
            "assets_confirmed": project.assets_confirmed,
            "has_completed_video": project.has_completed_video,
        }

    # --- Auth / ACL ---

    AUTH_DEFAULTS_KEY = "auth_defaults"

    def ensure_auth_defaults(self) -> dict[str, Any]:
        current = self.get_setting(self.AUTH_DEFAULTS_KEY, default=None)
        if current:
            return current
        defaults = {
            "default_project_role_on_create": ProjectRole.OWNER.value,
            "public_default_role": ProjectRole.EDITOR.value,
            "allow_user_create_project": True,
            "allow_user_make_public": False,
        }
        self.save_setting(self.AUTH_DEFAULTS_KEY, defaults)
        return defaults

    def get_auth_defaults(self) -> dict[str, Any]:
        return self.ensure_auth_defaults()

    def save_auth_defaults(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_auth_defaults()
        merged = {**current, **patch}
        merged["default_project_role_on_create"] = ProjectRole.OWNER.value
        if merged.get("public_default_role") not in {ProjectRole.EDITOR.value, ProjectRole.VIEWER.value}:
            merged["public_default_role"] = ProjectRole.EDITOR.value
        self.save_setting(self.AUTH_DEFAULTS_KEY, merged)
        return merged

    def _row_to_user(self, row: sqlite3.Row) -> User:
        try:
            permissions = normalize_user_permissions(json.loads(row["permissions"] or "{}"))
        except (TypeError, json.JSONDecodeError, KeyError):
            permissions = {}
        return User(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            display_name=row["display_name"] or "",
            role=SystemRole(row["role"]),
            is_active=bool(row["is_active"]),
            permissions=permissions,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def count_users(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"] if row else 0)

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        display_name: str = "",
        role: SystemRole = SystemRole.USER,
        user_id: str | None = None,
    ) -> User:
        now = datetime.now(timezone.utc)
        user = User(
            id=user_id or new_id("user"),
            username=username.strip(),
            password_hash=password_hash,
            display_name=display_name.strip() or username.strip(),
            role=role,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, password_hash, display_name, role, is_active, permissions, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    user.id,
                    user.username,
                    user.password_hash,
                    user.display_name,
                    user.role.value,
                    json.dumps(user.permissions or {}, ensure_ascii=False),
                    user.created_at.isoformat(),
                    user.updated_at.isoformat(),
                ),
            )
        return user

    def list_users(self) -> list[User]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
        return [self._row_to_user(row) for row in rows]

    def get_user(self, user_id: str) -> User:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(f"User not found: {user_id}")
        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> User | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        return self._row_to_user(row) if row else None

    def update_user(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        role: SystemRole | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
        permissions: dict[str, bool | None] | None = None,
    ) -> User:
        user = self.get_user(user_id)
        if display_name is not None:
            user.display_name = display_name.strip()
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        if password_hash is not None:
            user.password_hash = password_hash
        if permissions is not None:
            user.permissions = normalize_user_permissions(permissions)
        user.updated_at = datetime.now(timezone.utc)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET display_name = ?, role = ?, is_active = ?, password_hash = ?, permissions = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    user.display_name,
                    user.role.value,
                    1 if user.is_active else 0,
                    user.password_hash,
                    json.dumps(user.permissions or {}, ensure_ascii=False),
                    user.updated_at.isoformat(),
                    user.id,
                ),
            )
        return user

    def create_session(self, user_id: str, token_hash: str, expires_at: datetime) -> str:
        session_id = new_id("sess")
        now = datetime.now(timezone.utc)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, user_id, token_hash, expires_at.isoformat(), now.isoformat()),
            )
        return session_id

    def delete_session_by_token_hash(self, token_hash: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def get_user_by_session_token(self, token_hash: str) -> User | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT u.*
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1
                """,
                (token_hash, now),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_project_auth_meta(self, project_id: str) -> dict[str, str]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, owner_id, visibility FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        return {
            "id": row["id"],
            "owner_id": row["owner_id"],
            "visibility": row["visibility"] or ProjectVisibility.PRIVATE.value,
        }

    def set_project_owner(self, project_id: str, owner_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE projects SET owner_id = ? WHERE id = ?", (owner_id, project_id))

    def set_project_visibility(self, project_id: str, visibility: ProjectVisibility) -> Project:
        project = self.get_project(project_id)
        project.visibility = visibility
        project.updated_at = datetime.now(timezone.utc)
        return self.save_project(project)

    def get_project_member(self, project_id: str, user_id: str) -> ProjectMember | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_members WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return ProjectMember(
            project_id=row["project_id"],
            user_id=row["user_id"],
            role=ProjectRole(row["role"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_project_members(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT pm.project_id, pm.user_id, pm.role, pm.created_at,
                       u.username, u.display_name, u.role AS system_role
                FROM project_members pm
                JOIN users u ON u.id = pm.user_id
                WHERE pm.project_id = ?
                ORDER BY pm.created_at ASC
                """,
                (project_id,),
            ).fetchall()
        return [
            {
                "project_id": row["project_id"],
                "user_id": row["user_id"],
                "role": row["role"],
                "created_at": row["created_at"],
                "username": row["username"],
                "display_name": row["display_name"],
                "system_role": row["system_role"],
            }
            for row in rows
        ]

    def upsert_project_member(self, project_id: str, user_id: str, role: ProjectRole) -> ProjectMember:
        now = datetime.now(timezone.utc)
        member = ProjectMember(project_id=project_id, user_id=user_id, role=role, created_at=now)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO project_members (project_id, user_id, role, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role
                """,
                (project_id, user_id, role.value, now.isoformat()),
            )
        return member

    def remove_project_member(self, project_id: str, user_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            )

    def list_segment_locks(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT project_id, segment_id, user_id, display_name, locked_at, expires_at
                FROM segment_locks
                WHERE project_id = ?
                ORDER BY locked_at ASC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_segment_lock(self, project_id: str, segment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT project_id, segment_id, user_id, display_name, locked_at, expires_at
                FROM segment_locks
                WHERE project_id = ? AND segment_id = ?
                """,
                (project_id, segment_id),
            ).fetchone()
        return dict(row) if row else None

    def upsert_segment_lock(
        self,
        project_id: str,
        segment_id: str,
        *,
        user_id: str,
        display_name: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO segment_locks (project_id, segment_id, user_id, display_name, locked_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, segment_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    display_name = excluded.display_name,
                    locked_at = excluded.locked_at,
                    expires_at = excluded.expires_at
                """,
                (
                    project_id,
                    segment_id,
                    user_id,
                    display_name,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        lock = self.get_segment_lock(project_id, segment_id)
        return lock or {}

    def delete_segment_lock(self, project_id: str, segment_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM segment_locks WHERE project_id = ? AND segment_id = ?",
                (project_id, segment_id),
            )

    def cleanup_expired_segment_locks(self, project_id: str | None = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            if project_id:
                cursor = conn.execute(
                    "DELETE FROM segment_locks WHERE project_id = ? AND expires_at <= ?",
                    (project_id, now),
                )
            else:
                cursor = conn.execute("DELETE FROM segment_locks WHERE expires_at <= ?", (now,))
        return int(cursor.rowcount or 0)


def model_to_dict(value: Any) -> dict[str, Any]:
    return asdict(value)
