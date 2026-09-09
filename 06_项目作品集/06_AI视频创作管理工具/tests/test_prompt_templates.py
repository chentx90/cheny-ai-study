from __future__ import annotations

from ai_video_manager.api.app_helpers import sync_default_prompt_templates
from ai_video_manager.models import PromptCategory, PromptTemplate
from ai_video_manager.prompt_engine import PromptEngine, load_default_templates, resolve_default_template_path, template_for_category
from ai_video_manager.storage import SQLiteStore
import tempfile
from pathlib import Path
import shutil


def test_default_template_file_exists() -> None:
    path = resolve_default_template_path()
    assert path.is_file(), f"missing default prompt templates: {path}"


def test_all_example_templates_validate() -> None:
    engine = PromptEngine()
    templates = load_default_templates()
    assert len(templates) == 14
    assert all(not template.is_default for template in templates)
    assert all(template.id.startswith("tpl_example_") for template in templates)
    for template in templates:
        engine.validate_template(template)


def test_each_category_has_example_template() -> None:
    engine = PromptEngine()
    categories = [
        "split_planning",
        "script_convert",
        "entity_extract",
        "entity_consolidate",
        "entity_setting",
        "character_asset_prompt",
        "scene_asset_prompt",
        "prop_asset_prompt",
        "subject_match",
        "prompt_split",
        "video_generate",
        "prompt_rerun",
        "video_agent",
    ]
    for category in categories:
        picked = template_for_category(engine, category)
        assert not picked.is_default
        assert picked.id.startswith("tpl_example_")


def test_workflow_agent_routes_asset_visual_styles_to_visual_style_tools() -> None:
    template = next(
        item for item in load_default_templates() if item.id == "tpl_example_workflow_agent"
    )

    assert "visual-style.list" in template.template
    assert "visual-style.save" in template.template
    assert "不得使用 project.settings.update 代替" in template.template


def test_sync_default_prompt_templates_seeds_database() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="avm_prompt_seed_"))
    try:
        db_path = tmp / "database" / "app.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = SQLiteStore(db_path, workspace_root=tmp)
        store.init_schema()
        engine = PromptEngine()
        sync_default_prompt_templates(store, engine)
        rows = store.list_prompt_templates()
        assert len(rows) == 14
        assert {row.id for row in rows} >= {"tpl_example_video_generate"}
        assert all(row.version == 1 for row in rows)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_prompt_template_versions_can_be_restored_without_losing_history() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="avm_prompt_versions_"))
    try:
        store = SQLiteStore(tmp / "database" / "app.db", workspace_root=tmp)
        first = store.save_prompt_template(
            PromptTemplate(
                id="tpl_custom_script",
                name="自定义转写",
                category=PromptCategory.SCRIPT_CONVERT,
                template="v1 $content_type $content",
                variables=["content", "content_type"],
            )
        )
        second = store.save_prompt_template(
            PromptTemplate(
                id=first.id,
                name=first.name,
                category=first.category,
                template="v2 $content_type $content",
                variables=first.variables,
            )
        )

        assert second.version == 2
        assert [item["version"] for item in store.list_prompt_template_versions(first.id)] == [2, 1]

        restored = store.restore_prompt_template_version(first.id, 1)
        assert restored.version == 3
        assert restored.template == "v1 $content_type $content"
        assert [item["version"] for item in store.list_prompt_template_versions(first.id)] == [3, 2, 1]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sync_removes_obsolete_default_templates() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="avm_prompt_cleanup_"))
    try:
        store = SQLiteStore(tmp / "database" / "app.db", workspace_root=tmp)
        engine = PromptEngine()
        obsolete = PromptTemplate(
            id="tpl_default_video_generate",
            name="旧默认模板",
            category=PromptCategory.VIDEO_GENERATE,
            template="$script_excerpt $entity_catalog $max_duration_seconds $neighbor_context",
            variables=["entity_catalog", "max_duration_seconds", "neighbor_context", "script_excerpt"],
            is_default=True,
        )
        engine.load_template_record(obsolete)
        store.save_prompt_template(obsolete)

        sync_default_prompt_templates(store, engine)

        assert all(not template.id.startswith("tpl_default_") for template in engine.list_templates())
        assert all(not template.id.startswith("tpl_default_") for template in store.list_prompt_templates())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
