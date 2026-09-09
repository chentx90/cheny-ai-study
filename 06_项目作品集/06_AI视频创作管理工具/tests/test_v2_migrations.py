from __future__ import annotations

import sqlite3
from pathlib import Path

from ai_video_manager.infrastructure.db.v2_migrations import migrate_v2, validate_v2
from ai_video_manager.infrastructure.db.migration_runner import migrate_database, restore_database
from ai_video_manager.models import EntityCard, EntityType, Project, PromptCard
from ai_video_manager.project_domain import ProjectDomainService
from ai_video_manager.storage import SQLiteStore


def test_v2_migration_combines_segment_and_script(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "database" / "app.db", workspace_root=tmp_path)
    project = store.save_project(Project(name="迁移项目"))
    domain = ProjectDomainService(store)
    domain.import_workspace_dict(
        project.id,
        {
            "segments": [
                {"id": "seg_1", "order": 1, "title": "第1集", "content": "原文"},
                {"id": "seg_2", "order": 2, "title": "第2集", "content": "后续"},
            ],
            "scripts": {"seg_1": "场景：室内"},
        },
    )

    with store.connect() as conn:
        first = migrate_v2(conn)
        second = migrate_v2(conn)
        rows = conn.execute(
            "SELECT id, source_text, script_text, status FROM episodes "
            "WHERE project_id = ? ORDER BY order_index",
            (project.id,),
        ).fetchall()

    assert first.valid
    assert second.valid
    assert second.episodes == first.episodes
    assert [(row[0], row[1], row[2], row[3]) for row in rows] == [
        ("seg_1", "原文", "场景：室内", "script_ready"),
        ("seg_2", "后续", "", "source_ready"),
    ]


def test_v2_schema_records_migration_and_new_columns(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "database" / "app.db", workspace_root=tmp_path)
    with store.connect() as conn:
        report = validate_v2(conn)
        migration = conn.execute(
            "SELECT name FROM schema_migrations WHERE version = 2"
        ).fetchone()
        prompt_columns = {row[1] for row in conn.execute("PRAGMA table_info(prompt_cards)")}
        asset_columns = {row[1] for row in conn.execute("PRAGMA table_info(project_assets)")}

    assert report.valid
    assert migration[0] == "production_chain_v2"
    assert {"episode_id", "revision"} <= prompt_columns
    assert {"sha256", "mime_type", "width", "height", "duration_seconds"} <= asset_columns


def test_v2_validation_detects_dangling_prompt_card(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "database" / "app.db", workspace_root=tmp_path)
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO prompt_cards
            (id, project_id, segment_id, episode_id, order_index, title,
             prompt_text, anchor_text, duration, source_text, source_start, source_end,
             source_hash, status, locked, revision, created_at, updated_at)
            VALUES ('pcard_bad', 'proj_missing', 'ep_missing', 'ep_missing', 1, '',
                    'x', '', 1, '', 0, 0, '', 'draft', 0, 0, '', '')
            """
        )
        report = validate_v2(conn)

    assert report.dangling_prompt_cards == 1
    assert not report.valid


def test_migration_runner_dry_run_backup_and_restore(tmp_path: Path) -> None:
    db_path = tmp_path / "database" / "app.db"
    store = SQLiteStore(db_path, workspace_root=tmp_path)
    project = store.save_project(Project(name="备份项目"))

    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM schema_migrations WHERE version = 2")
        conn.execute("DROP TABLE episodes")

    dry_run = migrate_database(db_path, dry_run=True)
    assert dry_run.report.valid
    assert dry_run.backup_path is None
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version = 2"
        ).fetchone()[0] == 0

    migrated = migrate_database(db_path)
    assert migrated.report.valid
    assert migrated.backup_path and migrated.backup_path.is_file()
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project.id,))
    restore_database(db_path, migrated.backup_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT name FROM projects WHERE id = ?", (project.id,)).fetchone()[0] == "备份项目"


def test_legacy_workspace_methods_write_only_v2_episodes(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "database" / "app.db", workspace_root=tmp_path)
    project = store.save_project(Project(name="兼容写入"))
    store.replace_project_segments(
        project.id,
        [{"id": "seg_1", "order": 1, "title": "第1集", "content": "原文"}],
    )
    store.upsert_project_script(project.id, "seg_1", "剧本", {"status": "edited"})

    assert store.list_project_segments(project.id)[0]["content"] == "原文"
    assert store.list_project_scripts(project.id)[0]["content"] == "剧本"
    with store.connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM project_segments WHERE project_id = ?", (project.id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM project_scripts WHERE project_id = ?", (project.id,)
        ).fetchone()[0] == 0


def test_migration_converts_anchor_ids_to_entity_links(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "database" / "app.db", workspace_root=tmp_path)
    project = store.save_project(Project(name="anchor-migration"))
    entity = store.save_entity_card(
        project.id,
        EntityCard(project_id=project.id, entity_name="主角", type=EntityType.CHARACTER),
    )
    prompt = store.save_prompt_card(
        PromptCard(
            project_id=project.id,
            segment_id="ep_1",
            order=1,
            title="镜头",
            prompt_text="内容",
            anchor_text=f"[主角](entity:{entity.id})",
        )
    )
    with store.connect() as conn:
        migrate_v2(conn)
    links = store.list_prompt_card_entity_links(project.id, prompt.id)
    assert [item["entity_card_id"] for item in links] == [entity.id]
    assert links[0]["source"] == "legacy"
