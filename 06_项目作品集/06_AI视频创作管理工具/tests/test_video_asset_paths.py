from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from ai_video_manager.api.video_assets import resolve_project_asset_file, resolve_video_asset_reference
from ai_video_manager.models import EntityCard, EntityType, Project
from ai_video_manager.storage import SQLiteStore


@pytest.fixture
def isolated_store() -> SQLiteStore:
    tmp = Path(tempfile.mkdtemp(prefix="avm_asset_paths_"))
    db_path = tmp / "database" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path, workspace_root=tmp)
    store.init_schema()
    yield store
    shutil.rmtree(tmp, ignore_errors=True)


def test_resolve_project_asset_file_uses_custom_data_root(isolated_store: SQLiteStore) -> None:
    project = isolated_store.save_project(Project(name="custom-root"))
    custom_root = isolated_store.workspace_root / "external" / "bundle"
    image_dir = custom_root / "assets" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    image_path = image_dir / "hero.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    isolated_store.upsert_preprocess(
        project.id,
        {"data_root": str(custom_root.relative_to(isolated_store.workspace_root)).replace("\\", "/")},
    )

    resolved = resolve_project_asset_file(isolated_store, project.id, "assets/images/hero.png")
    assert resolved == image_path.resolve()


def test_resolve_rejects_data_url() -> None:
    with pytest.raises(ValueError, match="禁止使用 base64"):
        # store/project unused for remote-looking data URL branch
        from ai_video_manager.api.video_assets import resolve_video_asset_reference as resolve

        # Build minimal store just to call function
        tmp = Path(tempfile.mkdtemp(prefix="avm_dataurl_"))
        try:
            db_path = tmp / "database" / "app.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            store = SQLiteStore(db_path, workspace_root=tmp)
            store.init_schema()
            project = store.save_project(Project(name="dataurl"))
            resolve(store, project.id, "data:image/png;base64,aaaa")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def test_resolve_local_without_uploader_errors(isolated_store: SQLiteStore) -> None:
    project = isolated_store.save_project(Project(name="need-upload"))
    image_path = isolated_store.save_asset(project.id, "image", "a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    with pytest.raises(ValueError, match="无法提交|上传"):
        resolve_video_asset_reference(isolated_store, project.id, image_path, uploader=None)


def test_resolve_upload_failure_errors(isolated_store: SQLiteStore) -> None:
    project = isolated_store.save_project(Project(name="upload-fail"))
    image_path = isolated_store.save_asset(project.id, "image", "a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    def boom(_path: Path, _asset_type: str) -> str:
        raise RuntimeError("OSS down")

    with pytest.raises(ValueError, match="上传到视频网关云空间失败|OSS 直传失败"):
        resolve_video_asset_reference(
            isolated_store,
            project.id,
            image_path,
            uploader=boom,
        )


def test_project_assets_are_deduplicated_by_sha256(isolated_store: SQLiteStore) -> None:
    project = isolated_store.save_project(Project(name="dedupe"))
    content = b"same-image-content"
    first = isolated_store.save_asset(project.id, "image", "first.png", content)
    second = isolated_store.save_asset(project.id, "image", "second.png", content)

    assert second == first
    assets = isolated_store.list_assets(project.id)
    assert len(assets) == 1
    assert assets[0]["sha256"]
    assert assets[0]["id"].startswith("asset_")


def test_entity_cards_link_to_stable_project_asset_ids(isolated_store: SQLiteStore) -> None:
    project = isolated_store.save_project(Project(name="links"))
    path = isolated_store.save_asset(project.id, "image", "hero.png", b"hero-image")
    first = isolated_store.save_entity_card(
        project.id,
        EntityCard(project_id=project.id, entity_name="主角", type=EntityType.CHARACTER, assets=[path]),
    )
    second = isolated_store.save_entity_card(
        project.id,
        EntityCard(
            project_id=project.id,
            entity_name="主角",
            type=EntityType.CHARACTER,
            state="战斗",
            assets=[path],
        ),
    )

    with isolated_store.connect() as conn:
        links = conn.execute(
            "SELECT entity_card_id, project_asset_id FROM entity_material_links ORDER BY entity_card_id"
        ).fetchall()
        asset_count = conn.execute("SELECT count(*) FROM project_assets").fetchone()[0]
    assert {row["entity_card_id"] for row in links} == {first.id, second.id}
    assert len({row["project_asset_id"] for row in links}) == 1
    assert asset_count == 1
    assert isolated_store.get_entity_card(project.id, first.id).assets == [path]
