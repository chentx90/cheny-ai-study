from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from ai_video_manager.models import Project
from ai_video_manager.signed_media import mint_signed_media_url, verify_signed_media_token
from ai_video_manager.storage import SQLiteStore


@pytest.fixture
def isolated_store() -> SQLiteStore:
    tmp = Path(tempfile.mkdtemp(prefix="avm_signed_media_"))
    db_path = tmp / "database" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path, workspace_root=tmp)
    store.init_schema()
    yield store
    shutil.rmtree(tmp, ignore_errors=True)


def test_mint_and_verify_signed_media_url(isolated_store: SQLiteStore) -> None:
    project = isolated_store.save_project(Project(name="signed"))
    path = isolated_store.save_asset(project.id, "image", "a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    url = mint_signed_media_url(
        isolated_store,
        project_id=project.id,
        relative_path=path,
        public_base="https://example.test",
    )
    assert url.startswith("https://example.test/api/public/media/")
    token = url.rsplit("/", 1)[-1]
    project_id, file_path = verify_signed_media_token(isolated_store, token)
    assert project_id == project.id
    assert file_path.exists()
