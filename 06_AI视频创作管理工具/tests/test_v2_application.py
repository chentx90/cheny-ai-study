from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from ai_video_manager.application import EpisodeService, RevisionConflict, TrackedLLMClient
from ai_video_manager.auth.acl import PROJECT_PATH_RE, required_level_for_request
from ai_video_manager.infrastructure.db.production_repository import ProductionRepository
from ai_video_manager.llm import _message_content
from ai_video_manager.models import Project
from ai_video_manager.storage import SQLiteStore


class FakeLLM:
    provider = "test"
    model = "test-model"

    def test_connection(self) -> dict[str, object]:
        return {"ok": True}

    def complete(self, prompt: str, **_: object) -> str:
        if prompt == "fail":
            raise RuntimeError("boom")
        return "final content"


def _service(tmp_path: Path) -> tuple[SQLiteStore, Project, EpisodeService, ProductionRepository]:
    store = SQLiteStore(tmp_path / "database" / "app.db", workspace_root=tmp_path)
    project = store.save_project(Project(name="V2"))
    repository = ProductionRepository(store)
    return store, project, EpisodeService(repository), repository


def test_episode_crud_revision_and_reorder(tmp_path: Path) -> None:
    _, project, service, _ = _service(tmp_path)
    one = service.create(project.id, order=1, title="", source_text="一")
    two = service.create(project.id, order=2, title="第二集", source_text="二")
    updated = service.update(
        project.id, one["id"], revision=one["revision"], script_text="场景：室内"
    )
    assert updated["status"].value == "script_ready"
    with pytest.raises(RevisionConflict):
        service.update(project.id, one["id"], revision=one["revision"], title="过期")
    reordered = service.reorder(project.id, [two["id"], one["id"]])
    assert [item["id"] for item in reordered] == [two["id"], one["id"]]
    service.delete(project.id, two["id"])
    assert [item["id"] for item in service.list(project.id)] == [one["id"]]


def test_tracked_llm_records_success_and_failure(tmp_path: Path) -> None:
    _, project, _, repository = _service(tmp_path)
    client = TrackedLLMClient(FakeLLM(), repository, "subject_match", project.id)
    assert client.complete("ok") == "final content"
    with pytest.raises(RuntimeError, match="boom"):
        client.complete("fail")
    runs = repository.list_ai_runs(project.id)
    assert {item["status"] for item in runs} == {"succeeded", "failed"}
    success = next(item for item in runs if item["status"] == "succeeded")
    detail = repository.get_ai_run(project.id, success["id"])
    assert detail["input_snapshot"]["prompt"] == "ok"
    assert detail["output_snapshot"] == {"content": "final content"}


def test_repository_finds_project_for_migrated_episode(tmp_path: Path) -> None:
    _, project, service, repository = _service(tmp_path)
    episode = service.create(project.id, order=1, title="第1集", source_text="原文")
    assert repository.find_project_id_for_episode(episode["id"]) == project.id


def test_v2_project_routes_are_acl_protected() -> None:
    match = PROJECT_PATH_RE.match("/api/v2/projects/proj_1/episodes")
    assert match and match.group(1) == "proj_1"
    assert required_level_for_request("GET", "/api/v2/projects/proj_1/episodes", "proj_1") == "read"
    assert required_level_for_request("POST", "/api/v2/projects/proj_1/episodes", "proj_1") == "write"


def test_reasoning_content_is_never_used_as_final_content() -> None:
    message = AIMessage(content="", additional_kwargs={"reasoning_content": "private reasoning"})
    assert _message_content(message) == ""
