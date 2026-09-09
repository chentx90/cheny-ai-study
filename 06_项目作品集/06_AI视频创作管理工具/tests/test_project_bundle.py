from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

from ai_video_manager.models import EntityCard, EntityType, Project, PromptCard
from ai_video_manager.project_bundle import (
    ENTITY_CARDS_FILE,
    MANIFEST_FILE,
    PROMPT_CARDS_FILE,
    PathOutsideWorkspaceError,
    export_project_zip,
    import_project_from_path,
    import_project_zip,
    resolve_bounded_workspace_path,
    resolve_project_data_root,
    sync_cards_to_files,
    validate_data_root_path,
)
from ai_video_manager.project_domain import ProjectDomainService
from ai_video_manager.storage import SQLiteStore


@pytest.fixture
def isolated_store() -> SQLiteStore:
    tmp = Path(tempfile.mkdtemp(prefix="avm_test_"))
    db_path = tmp / "database" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path, workspace_root=tmp)
    store.init_schema()
    yield store
    shutil.rmtree(tmp, ignore_errors=True)


def _seed_project(store: SQLiteStore) -> tuple[str, str, str, str]:
    project = store.save_project(Project(name="源项目", category="draft", description="pytest"))
    domain = ProjectDomainService(store)
    domain.import_workspace_dict(
        project.id,
        {
            "documentText": "第一章",
            "segments": [{"id": "seg_src", "order": 1, "title": "第1集", "content": "第一章"}],
            "activeSegmentId": "seg_src",
            "scripts": {"seg_src": "场景：室内"},
        },
    )
    entity = EntityCard(
        entity_name="主角",
        type=EntityType.CHARACTER,
        project_id=project.id,
        state="青年",
    )
    store.save_entity_card(project.id, entity)
    original_entity_id = entity.id

    prompt = PromptCard(
        project_id=project.id,
        segment_id="seg_src",
        order=1,
        title="开场",
        prompt_text="推进镜头",
        anchor_text="",
    )
    store.save_prompt_card(prompt)
    original_prompt_id = prompt.id
    original_segment_id = "seg_src"
    return project.id, original_entity_id, original_prompt_id, original_segment_id


def test_sync_writes_bundle_json(isolated_store: SQLiteStore) -> None:
    project_id, _, _, _ = _seed_project(isolated_store)
    root = sync_cards_to_files(isolated_store, project_id)
    assert (root / MANIFEST_FILE).is_file()
    assert (root / ENTITY_CARDS_FILE).is_file()
    assert (root / PROMPT_CARDS_FILE).is_file()
    manifest = json.loads((root / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["project"]["name"] == "源项目"


def test_import_remaps_ids_without_touching_source(isolated_store: SQLiteStore) -> None:
    project_id, original_entity_id, original_prompt_id, original_segment_id = _seed_project(isolated_store)
    payload, _ = export_project_zip(isolated_store, project_id)

    imported = import_project_zip(isolated_store, payload, owner_id="", name_override="导入项目")
    assert imported.id != project_id
    assert imported.name == "导入项目"

    source_entities = isolated_store.list_entity_cards(project_id)
    source_prompts = isolated_store.list_prompt_cards(project_id)
    assert len(source_entities) == 1
    assert source_entities[0].id == original_entity_id
    assert len(source_prompts) == 1
    assert source_prompts[0].id == original_prompt_id
    assert source_prompts[0].segment_id == original_segment_id

    imported_entities = isolated_store.list_entity_cards(imported.id)
    imported_prompts = isolated_store.list_prompt_cards(imported.id)
    assert len(imported_entities) == 1
    assert imported_entities[0].id != original_entity_id
    assert imported_entities[0].entity_name == "主角"
    assert len(imported_prompts) == 1
    assert imported_prompts[0].id != original_prompt_id
    assert imported_prompts[0].segment_id != original_segment_id
    assert imported_prompts[0].segment_id.startswith("seg_")


def test_double_import_does_not_corrupt_first_import(isolated_store: SQLiteStore) -> None:
    project_id, _, _, _ = _seed_project(isolated_store)
    payload, _ = export_project_zip(isolated_store, project_id)

    first = import_project_zip(isolated_store, payload, owner_id="", name_override="第一次")
    second = import_project_zip(isolated_store, payload, owner_id="", name_override="第二次")
    assert first.id != second.id

    first_entities = isolated_store.list_entity_cards(first.id)
    second_entities = isolated_store.list_entity_cards(second.id)
    assert len(first_entities) == 1
    assert len(second_entities) == 1
    assert first_entities[0].id != second_entities[0].id


def test_data_root_must_stay_in_workspace(isolated_store: SQLiteStore) -> None:
    project_id, _, _, _ = _seed_project(isolated_store)
    domain = ProjectDomainService(isolated_store)

    with pytest.raises(PathOutsideWorkspaceError):
        validate_data_root_path(isolated_store, "/tmp/outside")

    with pytest.raises(PathOutsideWorkspaceError):
        domain.update_settings(project_id, data_root="../outside")

    custom = f"projects/custom_{project_id[:8]}"
    view = domain.update_settings(project_id, data_root=custom)
    assert view["dataRoot"] == custom
    root = resolve_project_data_root(isolated_store, project_id)
    assert root == (isolated_store.workspace_root / custom).resolve()


def test_import_folder_rejects_outside_workspace(isolated_store: SQLiteStore) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        resolve_bounded_workspace_path(isolated_store, "/etc", must_exist=False)

    project_id, _, _, _ = _seed_project(isolated_store)
    bundle_root = sync_cards_to_files(isolated_store, project_id)
    imported = import_project_from_path(
        isolated_store,
        str(bundle_root.relative_to(isolated_store.workspace_root)),
        owner_id="",
        name_override="文件夹导入",
    )
    assert imported.name == "文件夹导入"


def test_zip_slip_is_rejected(isolated_store: SQLiteStore) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../../evil.txt", "bad")
    with pytest.raises(ValueError, match="非法路径"):
        import_project_zip(isolated_store, buffer.getvalue(), owner_id="")
