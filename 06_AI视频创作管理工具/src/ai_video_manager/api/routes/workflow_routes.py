from __future__ import annotations

from fastapi import FastAPI, HTTPException

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.schemas import LoadCheckpointRequest, WorkflowJumpRequest
from ai_video_manager.api.utils import _dump
from ai_video_manager.workflow import WorkflowEngine, WorkflowError


def register_workflow_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store
    checkpoint_manager = services.checkpoint_manager

    @app.post("/api/workflow/jump")
    def jump_workflow(request: WorkflowJumpRequest) -> dict:
        try:
            project = store.get_project(request.project_id)
            engine = WorkflowEngine(project, checkpoint_manager)
            engine.jump_to(request.target_state)
            store.save_project(project)
            return _dump(project)
        except (KeyError, WorkflowError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/checkpoints/{project_id}")
    def list_checkpoints(project_id: str) -> dict:
        return {"checkpoints": [_dump(item) for item in checkpoint_manager.list_checkpoints(project_id)]}

    @app.post("/api/checkpoints/load")
    def load_checkpoint(request: LoadCheckpointRequest) -> dict:
        try:
            checkpoint = store.get_checkpoint(request.checkpoint_id)
            project = store.restore_checkpoint(request.checkpoint_id)
            return {"project": _dump(project), "checkpoint": _dump(checkpoint)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
