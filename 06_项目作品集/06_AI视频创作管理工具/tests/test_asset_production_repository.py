from __future__ import annotations

from pathlib import Path

from ai_video_manager.infrastructure.db.asset_production_repository import AssetProductionRepository
from ai_video_manager.application.entity_assets import EntityAssetService
from ai_video_manager.infrastructure.db.v3_migrations import migrate_v3
from ai_video_manager.models import Project
from ai_video_manager.storage import SQLiteStore


def _store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "database" / "app.db", workspace_root=tmp_path)


def test_v3_migration_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with store.connect() as conn:
        migrate_v3(conn)
        migrate_v3(conn)
        migration = conn.execute("SELECT name FROM schema_migrations WHERE version = 6").fetchone()
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }

    assert migration[0] == "entity_analysis_and_native_assets"
    assert {
        "entity_extraction_runs",
        "entity_profiles",
        "entity_mentions",
        "entity_variants",
        "project_visual_styles",
        "asset_generation_presets",
        "entity_asset_prompts",
        "image_generation_tasks",
        "image_outputs",
    } <= tables


def test_v3_migration_removes_deprecated_image_prompt_templates(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO prompt_templates (id, name, category, template, variables, is_default, current_version) "
            "VALUES ('tpl_old_image', '旧图片提示词', 'image_prompt', '$entity', '[\"entity\"]', 0, 1)"
        )
        conn.execute(
            "INSERT INTO prompt_template_versions "
            "(id, template_id, version_index, template_text, variables, created_at) "
            "VALUES ('tplver_old', 'tpl_old_image', 1, '$entity', '[\"entity\"]', '')"
        )
        migrate_v3(conn)
        assert conn.execute("SELECT count(*) FROM prompt_templates WHERE category = 'image_prompt'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM prompt_template_versions WHERE template_id = 'tpl_old_image'").fetchone()[0] == 0


def test_profiles_are_isolated_by_project(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.save_project(Project(name="A"))
    second = store.save_project(Project(name="B"))
    repository = AssetProductionRepository(store)

    first_profile = repository.upsert_profile(
        first.id, {"canonical_name": "主角", "type": "character", "importance": "S"}
    )
    second_profile = repository.upsert_profile(
        second.id, {"canonical_name": "主角", "type": "character", "importance": "B"}
    )

    assert first_profile["id"] != second_profile["id"]
    assert [item["importance"] for item in repository.list_profiles(first.id)] == ["S"]
    assert [item["importance"] for item in repository.list_profiles(second.id)] == ["B"]


def test_entity_flags_and_interrupted_runs_are_reconciled(tmp_path: Path) -> None:
    store = _store(tmp_path)
    project = store.save_project(Project(name="workflow"))
    repository = AssetProductionRepository(store)
    repository.upsert_profile(project.id, {"canonical_name": "主角", "type": "character"})
    run = repository.start_extraction_run(project.id, {"ep_1": 1})

    refreshed = store.refresh_entity_workflow_flags(project.id)
    recovered = repository.recover_interrupted_runs()

    assert refreshed.has_entities is True
    assert refreshed.current_state.value == "entities_extracted"
    assert recovered == 1
    assert repository.get_extraction_run(project.id, run["id"])["status"] == "failed"


def test_consolidation_is_validated_before_profiles_are_persisted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    project = store.save_project(Project(name="atomic"))
    repository = AssetProductionRepository(store)
    extracted = [
        {"name": "主角", "type": "character", "aliases": []},
        {"name": "旧宅", "type": "scene", "aliases": []},
    ]
    groups = [{"canonical_name": "主角", "type": "character", "member_names": ["主角"]}]

    try:
        EntityAssetService._match_groups(extracted, groups)
    except ValueError as exc:
        assert "旧宅" in str(exc)
    else:
        raise AssertionError("incomplete consolidation should fail")

    assert repository.list_profiles(project.id) == []


def test_manual_profile_fields_survive_analysis_upsert(tmp_path: Path) -> None:
    store = _store(tmp_path)
    project = store.save_project(Project(name="manual"))
    repository = AssetProductionRepository(store)
    profile = repository.upsert_profile(
        project.id,
        {
            "canonical_name": "林舟",
            "type": "character",
            "role": "supporting",
            "importance": "B",
            "setting": "初始设定",
            "mention_count": 2,
        },
    )
    repository.update_profile(
        project.id,
        profile["id"],
        {"role": "protagonist", "importance": "S", "setting": "人工确认设定"},
    )

    refreshed = repository.upsert_profile(
        project.id,
        {
            "canonical_name": "林舟",
            "type": "character",
            "role": "minor",
            "importance": "C",
            "setting": "模型新设定",
            "mention_count": 9,
            "scene_count": 4,
            "episode_ids": ["ep_1", "ep_2"],
            "first_episode": 1,
            "last_episode": 2,
        },
    )

    assert refreshed["role"] == "protagonist"
    assert refreshed["importance"] == "S"
    assert refreshed["setting"] == "人工确认设定"
    assert refreshed["mention_count"] == 9
    assert refreshed["episode_ids"] == ["ep_1", "ep_2"]

    renamed = repository.update_profile(project.id, profile["id"], {"canonical_name": "林川"})
    assert "林舟" in renamed["aliases"]
    matched = repository.upsert_profile(
        project.id,
        {"canonical_name": "林舟", "type": "character", "mention_count": 12},
    )
    assert matched["id"] == profile["id"]
    assert matched["canonical_name"] == "林川"


def test_style_presets_prompts_and_image_outputs_are_persistent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    project = store.save_project(Project(name="assets"))
    repository = AssetProductionRepository(store)
    profile = repository.upsert_profile(project.id, {"canonical_name": "古城", "type": "scene"})
    style = repository.save_visual_style(
        project.id,
        {"name": "国风", "prompt": "水墨", "negative_prompt": "现代建筑", "is_active": True},
    )
    preset = repository.save_preset(
        project.id,
        "scene",
        {"provider": "newapi", "model": "image-model", "size": "1536x1024", "view_types": ["全景"]},
    )
    prompt = repository.save_asset_prompt(
        project.id,
        {
            "profile_id": profile["id"], "style_id": style["id"], "style_version": style["version"],
            "view_type": "全景", "prompt_text": "古城全景", "negative_prompt": "现代建筑",
        },
    )
    task = repository.create_image_task(
        project.id, {"profile_id": profile["id"], "asset_prompt_id": prompt["id"], "model": preset["model"]}
    )
    path = store.save_asset(project.id, "image", "city.png", b"fake-png")
    asset = store.get_project_asset(project.id, path)
    output = repository.add_image_output(project.id, task["id"], asset, {"index": 1})
    duplicate = repository.add_image_output(project.id, task["id"], asset, {"index": 2})

    assert repository.list_visual_styles(project.id)[0]["prompt"] == "水墨"
    assert repository.list_presets(project.id)[1]["model"] == "image-model"
    assert repository.list_asset_prompts(project.id, profile["id"])[0]["prompt_text"] == "古城全景"
    assert repository.get_image_task(project.id, task["id"])["outputs"][0]["id"] == output["id"]
    assert duplicate["id"] == output["id"]
