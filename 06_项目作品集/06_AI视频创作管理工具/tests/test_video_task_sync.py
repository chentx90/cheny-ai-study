from __future__ import annotations

import asyncio
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from types import SimpleNamespace

from ai_video_manager.api.video_tasks import _run_and_store_video_task, sync_video_task_status
from ai_video_manager.models import Project, TaskStatus, VideoTask
from ai_video_manager.storage import SQLiteStore
from ai_video_manager.video_generation import MockVideoAPIAdapter, UnconfiguredVideoAPIAdapter, VideoGenerationEngine
from ai_video_manager.workers.video_recovery import recover_incomplete_video_tasks


@pytest.fixture
def isolated_store() -> SQLiteStore:
    tmp = Path(tempfile.mkdtemp(prefix="avm_task_sync_"))
    db_path = tmp / "database" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path, workspace_root=tmp)
    store.init_schema()
    yield store
    shutil.rmtree(tmp, ignore_errors=True)


def test_sync_marks_stale_submit_without_api_task_id(isolated_store: SQLiteStore) -> None:
    project = isolated_store.save_project(Project(name="stale-submit"))
    stale_at = datetime.now(timezone.utc) - timedelta(hours=2)
    task = VideoTask(
        project_id=project.id,
        segment_id="seg_test",
        prompt="prompt",
        status=TaskStatus.PROCESSING,
        created_at=stale_at,
        updated_at=stale_at,
    )
    saved = isolated_store.save_video_task(task)
    stale_iso = stale_at.isoformat()
    with isolated_store.connect() as conn:
        conn.execute(
            "UPDATE video_tasks SET created_at = ?, updated_at = ? WHERE id = ?",
            (stale_iso, stale_iso, saved.id),
        )
    saved = isolated_store.get_video_task(saved.id)
    engine = VideoGenerationEngine()
    engine.set_api_client(UnconfiguredVideoAPIAdapter())

    synced = asyncio.run(sync_video_task_status(saved, isolated_store, engine))
    assert synced.status == TaskStatus.FAILED
    assert "未拿到远端任务 ID" in (synced.error_message or "")


def test_video_request_is_persisted_before_execution_and_records_output(isolated_store: SQLiteStore) -> None:
    project = isolated_store.save_project(Project(name="persistent queue"))
    task = VideoTask(
        project_id=project.id,
        segment_id="episode_1",
        prompt_card_id="pcard_1",
        prompt="video prompt",
        assets={"reference_mode": "none", "settings": {"model": "test-model"}},
    )
    engine = VideoGenerationEngine(
        api_client=MockVideoAPIAdapter(),
        archive_root=isolated_store.workspace_root / "projects",
    )

    result = asyncio.run(_run_and_store_video_task(task, False, isolated_store, engine))
    stored = isolated_store.get_video_task(result.id)

    assert stored.status == TaskStatus.COMPLETED
    assert stored.attempt == 1
    assert stored.request_snapshot["request"]["prompt"] == "video prompt"
    assert stored.request_snapshot["lifecycle"]["phase"] == "completed"
    assert len(isolated_store.list_video_outputs(project.id, "pcard_1")) == 1


def test_startup_resubmits_persisted_task_without_remote_id(
    isolated_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = isolated_store.save_project(Project(name="startup recovery"))
    task = isolated_store.save_video_task(
        VideoTask(
            project_id=project.id,
            segment_id="episode_1",
            prompt_card_id="pcard_1",
            prompt="resume me",
            status=TaskStatus.PENDING,
            request_snapshot={"lifecycle": {"phase": "queued"}},
            attempt=1,
        )
    )
    base_engine = VideoGenerationEngine(
        api_client=MockVideoAPIAdapter(),
        archive_root=isolated_store.workspace_root / "projects",
    )
    services = SimpleNamespace(store=isolated_store, video_engine=base_engine)
    monkeypatch.setattr(
        "ai_video_manager.workers.video_recovery.build_video_adapter",
        lambda _config: MockVideoAPIAdapter(),
    )

    report = asyncio.run(recover_incomplete_video_tasks(services))
    recovered = isolated_store.get_video_task(task.id)

    assert report == {"found": 1, "remote_recovery": 0, "resubmitted": 1, "waiting_config": 0}
    assert recovered.status == TaskStatus.COMPLETED
    assert recovered.request_snapshot["lifecycle"]["phase"] == "completed"
