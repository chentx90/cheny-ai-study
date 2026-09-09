from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


V3_VERSION = 6

V3_SCHEMA = """
CREATE TABLE IF NOT EXISTS entity_extraction_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    episode_revisions TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_entity_extraction_runs_project
    ON entity_extraction_runs(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS entity_profiles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    type TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    role TEXT NOT NULL DEFAULT '',
    importance TEXT NOT NULL DEFAULT 'C',
    mention_count INTEGER NOT NULL DEFAULT 0,
    scene_count INTEGER NOT NULL DEFAULT 0,
    episode_ids TEXT NOT NULL DEFAULT '[]',
    first_episode INTEGER,
    last_episode INTEGER,
    setting TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    manual_fields TEXT NOT NULL DEFAULT '[]',
    linked_entity_card_id TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, canonical_name, type)
);
CREATE INDEX IF NOT EXISTS idx_entity_profiles_project_type
    ON entity_profiles(project_id, type, importance, canonical_name);

CREATE TABLE IF NOT EXISTS entity_mentions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    episode_order INTEGER NOT NULL,
    alias TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    mention_count INTEGER NOT NULL DEFAULT 0,
    scene_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_profile
    ON entity_mentions(project_id, profile_id, episode_order);

CREATE TABLE IF NOT EXISTS entity_variants (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    name TEXT NOT NULL,
    setting TEXT NOT NULL DEFAULT '',
    episode_ids TEXT NOT NULL DEFAULT '[]',
    is_default INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_id, name)
);
CREATE INDEX IF NOT EXISTS idx_entity_variants_profile
    ON entity_variants(project_id, profile_id);

CREATE TABLE IF NOT EXISTS project_visual_styles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    reference_asset_ids TEXT NOT NULL DEFAULT '[]',
    is_active INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, name, version)
);
CREATE INDEX IF NOT EXISTS idx_visual_styles_project
    ON project_visual_styles(project_id, is_active DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS asset_generation_presets (
    project_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'openai',
    model TEXT NOT NULL DEFAULT '',
    size TEXT NOT NULL DEFAULT '1024x1024',
    aspect_ratio TEXT NOT NULL DEFAULT '1:1',
    output_count INTEGER NOT NULL DEFAULT 1,
    view_types TEXT NOT NULL DEFAULT '[]',
    type_prompt TEXT NOT NULL DEFAULT '',
    type_negative_prompt TEXT NOT NULL DEFAULT '',
    auto_adopt INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, entity_type)
);

CREATE TABLE IF NOT EXISTS entity_asset_prompts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    variant_id TEXT,
    style_id TEXT,
    style_version INTEGER,
    view_type TEXT NOT NULL DEFAULT '',
    prompt_text TEXT NOT NULL,
    negative_prompt TEXT NOT NULL DEFAULT '',
    template_id TEXT,
    template_version INTEGER,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entity_asset_prompts_profile
    ON entity_asset_prompts(project_id, profile_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS image_generation_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    profile_id TEXT,
    asset_prompt_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    request_snapshot TEXT NOT NULL DEFAULT '{}',
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_image_tasks_project
    ON image_generation_tasks(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS image_outputs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    image_task_id TEXT NOT NULL,
    project_asset_id TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    adopted INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(image_task_id, project_asset_id)
);
CREATE INDEX IF NOT EXISTS idx_image_outputs_task
    ON image_outputs(project_id, image_task_id, created_at);
"""


def migrate_v3(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(V3_SCHEMA)
    deprecated_ids = [
        str(row[0])
        for row in conn.execute(
            "SELECT id FROM prompt_templates WHERE category = 'image_prompt'"
        ).fetchall()
    ]
    for template_id in deprecated_ids:
        conn.execute("DELETE FROM prompt_template_versions WHERE template_id = ?", (template_id,))
    conn.execute("DELETE FROM prompt_templates WHERE category = 'image_prompt'")
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
        (V3_VERSION, "entity_analysis_and_native_assets", now),
    )
