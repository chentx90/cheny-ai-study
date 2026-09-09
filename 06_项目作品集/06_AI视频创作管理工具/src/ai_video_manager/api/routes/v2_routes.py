from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.application import EpisodeService, RevisionConflict
from ai_video_manager.api.utils import _dump
from ai_video_manager.auth.acl import require_project_access


class CreateEpisodeRequest(BaseModel):
    order: int = Field(ge=1)
    title: str = ""
    source_text: str = ""
    script_text: str = ""


class UpdateEpisodeRequest(BaseModel):
    revision: int = Field(ge=0)
    title: str | None = None
    source_text: str | None = None
    script_text: str | None = None


class ReorderEpisodesRequest(BaseModel):
    episode_ids: list[str]


def register_v2_routes(app: FastAPI, services: AppServices) -> None:
    episodes = EpisodeService(services.production_repository)

    @app.get("/api/v2/projects/{project_id}/episodes")
    def list_episodes(project_id: str) -> dict:
        try:
            return {"episodes": episodes.list(project_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v2/projects/{project_id}/episodes", status_code=201)
    def create_episode(project_id: str, request: CreateEpisodeRequest) -> dict:
        try:
            return {
                "episode": episodes.create(
                    project_id,
                    order=request.order,
                    title=request.title,
                    source_text=request.source_text,
                    script_text=request.script_text,
                )
            }
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/v2/projects/{project_id}/episodes/{episode_id}")
    def update_episode(project_id: str, episode_id: str, request: UpdateEpisodeRequest) -> dict:
        try:
            return {
                "episode": episodes.update(
                    project_id,
                    episode_id,
                    revision=request.revision,
                    title=request.title,
                    source_text=request.source_text,
                    script_text=request.script_text,
                )
            }
        except RevisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/v2/projects/{project_id}/episodes/reorder")
    def reorder_episodes(project_id: str, request: ReorderEpisodesRequest) -> dict:
        try:
            return {"episodes": episodes.reorder(project_id, request.episode_ids)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/v2/projects/{project_id}/episodes/{episode_id}")
    def delete_episode(project_id: str, episode_id: str) -> dict:
        try:
            episodes.delete(project_id, episode_id)
            return {"deleted": True, "episode_id": episode_id}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v2/projects/{project_id}/ai-runs")
    def list_ai_runs(project_id: str, limit: int = 100) -> dict:
        return {"runs": services.production_repository.list_ai_runs(project_id, limit=limit)}

    @app.get("/api/v2/projects/{project_id}/ai-runs/{run_id}")
    def get_ai_run(project_id: str, run_id: str) -> dict:
        try:
            return {"run": services.production_repository.get_ai_run(project_id, run_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v2/projects/{project_id}/video-outputs")
    def list_video_outputs(
        project_id: str,
        request: Request,
        prompt_card_id: str | None = None,
    ) -> dict:
        require_project_access(services.store, request.state.user, project_id, "read")
        try:
            outputs = services.store.list_video_outputs(project_id, prompt_card_id)
            return {"outputs": [_dump(output) for output in outputs]}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v2/projects/{project_id}/video-outputs/{output_id}/adopt")
    def adopt_video_output(project_id: str, output_id: str, request: Request) -> dict:
        require_project_access(services.store, request.state.user, project_id, "write")
        try:
            return {"output": _dump(services.store.adopt_video_output(project_id, output_id))}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
