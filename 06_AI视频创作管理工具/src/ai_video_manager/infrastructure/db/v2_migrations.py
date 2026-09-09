from __future__ import annotations

import sqlite3
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone


V2_VERSION = 5


V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    document_id TEXT,
    order_index INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    source_text TEXT NOT NULL DEFAULT '',
    script_text TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    script_validation TEXT NOT NULL DEFAULT '{}',
    source_start INTEGER NOT NULL DEFAULT 0,
    source_end INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'source_ready',
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, order_index)
);
CREATE INDEX IF NOT EXISTS idx_episodes_project_order
    ON episodes(project_id, order_index);
CREATE TABLE IF NOT EXISTS prompt_card_entity_links (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    prompt_card_id TEXT NOT NULL,
    entity_card_id TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL,
    confirmed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(prompt_card_id, entity_card_id)
);
CREATE INDEX IF NOT EXISTS idx_prompt_card_entity_links_project
    ON prompt_card_entity_links(project_id, prompt_card_id);
CREATE TABLE IF NOT EXISTS entity_material_links (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    entity_card_id TEXT NOT NULL,
    project_asset_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(entity_card_id, project_asset_id)
);
CREATE INDEX IF NOT EXISTS idx_entity_material_links_project_card
    ON entity_material_links(project_id, entity_card_id);
CREATE TABLE IF NOT EXISTS prompt_template_versions (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    version_index INTEGER NOT NULL,
    template_text TEXT NOT NULL,
    variables TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(template_id, version_index)
);
CREATE TABLE IF NOT EXISTS ai_runs (
    id TEXT PRIMARY KEY,
    use_case TEXT NOT NULL,
    project_id TEXT NOT NULL,
    episode_id TEXT,
    prompt_card_id TEXT,
    provider_profile_id TEXT,
    model TEXT NOT NULL DEFAULT '',
    template_id TEXT,
    template_version INTEGER,
    input_snapshot TEXT NOT NULL DEFAULT '{}',
    output_snapshot TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    error_code TEXT,
    error_message TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_runs_project_created
    ON ai_runs(project_id, created_at DESC);
CREATE TABLE IF NOT EXISTS video_outputs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    video_task_id TEXT NOT NULL,
    prompt_card_id TEXT,
    storage_path TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    adopted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(video_task_id, storage_path)
);
CREATE INDEX IF NOT EXISTS idx_video_outputs_task
    ON video_outputs(video_task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_outputs_project_card
    ON video_outputs(project_id, prompt_card_id, created_at DESC);
"""


@dataclass(frozen=True, slots=True)
class V2MigrationReport:
    version: int
    projects: int
    legacy_segments: int
    episodes: int
    prompt_cards: int
    dangling_prompt_cards: int
    video_tasks: int
    dangling_video_tasks: int

    @property
    def valid(self) -> bool:
        return self.dangling_prompt_cards == 0 and self.dangling_video_tasks == 0


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def migrate_v2(conn: sqlite3.Connection) -> V2MigrationReport:
    """Apply the additive V2 schema and copy legacy production data.

    This migration is intentionally idempotent. It never drops legacy tables,
    allowing the pre-V2 application and database backup to remain a rollback path.
    """

    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(V2_SCHEMA)
    _add_column(conn, "projects", "revision INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "project_assets", "sha256 TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "project_assets", "mime_type TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "project_assets", "width INTEGER")
    _add_column(conn, "project_assets", "height INTEGER")
    _add_column(conn, "project_assets", "duration_seconds REAL")
    _add_column(conn, "prompt_cards", "episode_id TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "prompt_cards", "revision INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "video_tasks", "request_snapshot TEXT NOT NULL DEFAULT '{}'")
    _add_column(conn, "video_tasks", "attempt INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "video_outputs", "prompt_card_id TEXT")
    _add_column(conn, "prompt_templates", "current_version INTEGER NOT NULL DEFAULT 1")
    _add_column(conn, "episodes", "metadata TEXT NOT NULL DEFAULT '{}'")
    _add_column(conn, "episodes", "script_validation TEXT NOT NULL DEFAULT '{}'")

    conn.execute("UPDATE prompt_cards SET episode_id = segment_id WHERE episode_id = ''")
    conn.execute(
        """
        UPDATE video_outputs
        SET prompt_card_id = (
            SELECT prompt_card_id FROM video_tasks WHERE video_tasks.id = video_outputs.video_task_id
        )
        WHERE prompt_card_id IS NULL
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_video_outputs_project_card "
        "ON video_outputs(project_id, prompt_card_id, created_at DESC)"
    )
    _migrate_video_outputs(conn, now)
    _migrate_prompt_template_versions(conn, now)
    _migrate_prompt_card_entity_links(conn, now)
    _drop_legacy_shot_schema(conn)
    conn.execute(
        """
        INSERT OR IGNORE INTO episodes
        (id, project_id, document_id, order_index, title, source_text, script_text,
         metadata, script_validation,
         source_start, source_end, status, revision, created_at, updated_at)
        SELECT s.id, s.project_id,
               (SELECT d.id FROM documents d WHERE d.project_id = s.project_id
                ORDER BY d.created_at DESC LIMIT 1),
               s.order_index, s.title, s.content, COALESCE(sc.content, ''),
               COALESCE(s.metadata, '{}'), COALESCE(sc.validation, '{}'), 0,
               length(s.content),
               CASE WHEN COALESCE(sc.content, '') <> '' THEN 'script_ready' ELSE 'source_ready' END,
               0, s.updated_at, s.updated_at
        FROM project_segments s
        LEFT JOIN project_scripts sc
          ON sc.project_id = s.project_id AND sc.segment_id = s.id
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO episodes
        (id, project_id, document_id, order_index, title, source_text, script_text,
         metadata, script_validation,
         source_start, source_end, status, revision, created_at, updated_at)
        SELECT ss.id, d.project_id, d.id, ss.order_index, '', ss.content,
               CASE WHEN ss.is_converted = 1 THEN ss.content ELSE '' END, '{}', '{}',
               0, length(ss.content),
               CASE WHEN ss.is_converted = 1 THEN 'script_ready' ELSE 'source_ready' END,
               0, d.created_at, d.created_at
        FROM script_segments ss
        JOIN documents d ON d.id = ss.document_id
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (2, ?, ?)",
        ("production_chain_v2", now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
        (3, "video_output_candidates", now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
        (4, "prompt_template_versions", now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
        (V2_VERSION, "remove_legacy_shots", now),
    )
    return validate_v2(conn)


def _migrate_video_outputs(conn: sqlite3.Connection, created_at: str) -> None:
    """Backfill completed legacy tasks as independently selectable outputs."""
    rows = conn.execute(
        """
        SELECT id, project_id, prompt_card_id, result_path, provider, api_task_id,
               version, prompt_version, duration, updated_at
        FROM video_tasks
        WHERE status = 'completed' AND result_path IS NOT NULL AND trim(result_path) <> ''
        """
    ).fetchall()
    for row in rows:
        digest = hashlib.sha1(f"{row[0]}:{row[3]}".encode()).hexdigest()[:12]
        metadata = json.dumps(
            {
                "provider": str(row[4] or ""),
                "api_task_id": str(row[5] or ""),
                "version": int(row[6] or 1),
                "prompt_version": int(row[7] or 1),
                "duration": int(row[8]) if row[8] is not None else None,
            },
            ensure_ascii=False,
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO video_outputs
            (id, project_id, video_task_id, prompt_card_id, storage_path, metadata, adopted, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (f"vout_{digest}", row[1], row[0], row[2], row[3], metadata, row[9] or created_at),
        )


def _migrate_prompt_template_versions(conn: sqlite3.Connection, created_at: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO prompt_template_versions
        (id, template_id, version_index, template_text, variables, created_at)
        SELECT 'tplver_' || substr(lower(hex(randomblob(12))), 1, 12),
               id, current_version, template, variables, ?
        FROM prompt_templates
        """,
        (created_at,),
    )


def _migrate_prompt_card_entity_links(conn: sqlite3.Connection, created_at: str) -> None:
    valid_ids = {str(row[0]) for row in conn.execute("SELECT id FROM entity_cards").fetchall()}
    rows = conn.execute("SELECT id, project_id, anchor_text FROM prompt_cards").fetchall()
    for prompt_card_id, project_id, anchor_text in rows:
        card_ids = dict.fromkeys(re.findall(r"\bcard_[0-9a-fA-F]{12}\b", str(anchor_text or "")))
        for entity_card_id in card_ids:
            if entity_card_id not in valid_ids:
                continue
            digest = hashlib.sha1(f"{prompt_card_id}:{entity_card_id}".encode()).hexdigest()[:12]
            conn.execute(
                """
                INSERT OR IGNORE INTO prompt_card_entity_links
                (id, project_id, prompt_card_id, entity_card_id, source, confidence,
                 confirmed, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'legacy', NULL, 1, ?, ?)
                """,
                (f"pcel_{digest}", project_id, prompt_card_id, entity_card_id, created_at, created_at),
            )


def _drop_legacy_shot_schema(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS shots")
    if "shot_ids" in _columns(conn, "prompt_cards"):
        conn.execute("ALTER TABLE prompt_cards DROP COLUMN shot_ids")
    if "shot_ids" in _columns(conn, "video_tasks"):
        conn.execute("ALTER TABLE video_tasks DROP COLUMN shot_ids")


def validate_v2(conn: sqlite3.Connection) -> V2MigrationReport:
    scalar = lambda sql: int(conn.execute(sql).fetchone()[0])
    return V2MigrationReport(
        version=V2_VERSION,
        projects=scalar("SELECT count(*) FROM projects"),
        legacy_segments=scalar("SELECT count(*) FROM project_segments"),
        episodes=scalar("SELECT count(*) FROM episodes"),
        prompt_cards=scalar("SELECT count(*) FROM prompt_cards"),
        dangling_prompt_cards=scalar(
            "SELECT count(*) FROM prompt_cards p LEFT JOIN episodes e "
            "ON e.id = p.episode_id AND e.project_id = p.project_id "
            "WHERE p.episode_id <> '' AND e.id IS NULL"
        ),
        video_tasks=scalar("SELECT count(*) FROM video_tasks"),
        dangling_video_tasks=scalar(
            "SELECT count(*) FROM video_tasks v LEFT JOIN projects p ON p.id = v.project_id "
            "WHERE p.id IS NULL"
        ),
    )
