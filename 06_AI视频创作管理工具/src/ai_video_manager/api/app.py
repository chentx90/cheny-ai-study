from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_video_manager.api.app_services import build_app_services
from ai_video_manager.api.job_runner import video_job_runner
from ai_video_manager.api.prompt_pipeline_routes import register_prompt_pipeline_routes
from ai_video_manager.api.routes import register_all_routes
from ai_video_manager.api.static_ui import SPAStaticFiles
from ai_video_manager.auth.middleware import AuthMiddleware
from ai_video_manager.process_registry import kill_all_processes
from ai_video_manager.runtime_paths import (
    cors_origins,
    resolve_runtime_paths,
    resolve_static_ui_dir,
    should_serve_ui,
)
from ai_video_manager.workers.video_recovery import recover_incomplete_video_tasks


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    services = getattr(app.state, "services", None)
    if services is not None:
        app.state.video_recovery_report = await recover_incomplete_video_tasks(services)
    yield
    # Reload / Ctrl+C: cancel poll jobs and kill CLI children so uvicorn isn't stuck.
    await video_job_runner.shutdown(timeout=3.0)
    kill_all_processes(grace_seconds=1.0)


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="AI Video Creation Manager", version="0.1.0", lifespan=app_lifespan)
    workspace_root, resolved_db = resolve_runtime_paths(db_path)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    services = build_app_services(db_path=resolved_db, workspace_root=workspace_root)
    app.state.services = services
    app.state.video_recovery_report = {"found": 0, "remote_recovery": 0, "resubmitted": 0, "waiting_config": 0}
    app.add_middleware(AuthMiddleware, store=services.store)
    register_all_routes(app, services)
    register_prompt_pipeline_routes(
        app,
        store=services.store,
        prompt_engine=services.prompt_engine,
        checkpoint_manager=services.checkpoint_manager,
        video_engine=services.video_engine,
        production_repository=services.production_repository,
    )
    static_dir = resolve_static_ui_dir(workspace_root=workspace_root)
    if should_serve_ui() and static_dir is not None:
        app.mount("/", SPAStaticFiles(directory=str(static_dir), html=True), name="ui")
    return app
