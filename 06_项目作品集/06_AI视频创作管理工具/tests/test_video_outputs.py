from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from ai_video_manager.models import Project, TaskStatus, VideoTask
from ai_video_manager.storage import SQLiteStore


@pytest.fixture
def store() -> SQLiteStore:
    root = Path(tempfile.mkdtemp(prefix="avm_video_outputs_"))
    value = SQLiteStore(root / "database" / "app.db", workspace_root=root)
    yield value
    shutil.rmtree(root, ignore_errors=True)


def completed_task(
    store: SQLiteStore,
    project_id: str,
    prompt_card_id: str,
    *,
    version: int,
) -> VideoTask:
    return store.save_video_task(
        VideoTask(
            project_id=project_id,
            segment_id="episode_1",
            prompt_card_id=prompt_card_id,
            prompt=f"prompt {version}",
            version=version,
            status=TaskStatus.COMPLETED,
            result_path=f"projects/{project_id}/generated/episode_1/result-{version}.mp4",
        )
    )


def test_record_video_output_is_idempotent(store: SQLiteStore) -> None:
    project = store.save_project(Project(name="outputs"))
    task = completed_task(store, project.id, "pcard_1", version=1)

    first = store.record_video_output(task)
    second = store.record_video_output(task)

    assert second.id == first.id
    assert second.prompt_card_id == "pcard_1"
    assert len(store.list_video_outputs(project.id)) == 1


def test_retries_are_candidates_and_adoption_switches_atomically(store: SQLiteStore) -> None:
    project = store.save_project(Project(name="candidates"))
    first = store.record_video_output(completed_task(store, project.id, "pcard_1", version=1))
    second = store.record_video_output(completed_task(store, project.id, "pcard_1", version=2))

    assert {item.id for item in store.list_video_outputs(project.id, "pcard_1")} == {first.id, second.id}

    store.adopt_video_output(project.id, first.id)
    store.adopt_video_output(project.id, second.id)
    outputs = store.list_video_outputs(project.id, "pcard_1")

    assert [item.id for item in outputs if item.adopted] == [second.id]


def test_cross_project_adoption_is_rejected(store: SQLiteStore) -> None:
    owner = store.save_project(Project(name="owner"))
    other = store.save_project(Project(name="other"))
    output = store.record_video_output(completed_task(store, owner.id, "pcard_1", version=1))

    with pytest.raises(KeyError, match="not found in project"):
        store.adopt_video_output(other.id, output.id)


def test_deleting_task_removes_output_record_but_not_file(store: SQLiteStore) -> None:
    project = store.save_project(Project(name="delete relation"))
    task = completed_task(store, project.id, "pcard_1", version=1)
    output_path = store.workspace_root / str(task.result_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"video")
    store.record_video_output(task)

    store.delete_video_task(task.id)

    assert store.list_video_outputs(project.id) == []
    assert output_path.read_bytes() == b"video"
