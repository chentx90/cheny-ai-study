from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.config import _load_api_config
from ai_video_manager.auth.acl import require_project_access
from ai_video_manager.api.schemas import GenerateVideoRequest, RecoverVideoTaskRequest, RetryVideoTaskRequest
from ai_video_manager.api.utils import _dump
from ai_video_manager.api.video_submit import build_video_task_from_generate_request
from ai_video_manager.api.video_tasks import (
    _ensure_video_generation_allowed,
    _run_and_store_video_task,
    assets_for_retry_task,
    attach_video_request_settings,
    recover_and_store_video_task,
    sync_project_video_tasks,
    video_request_settings,
)
from ai_video_manager.models import VideoTask


def register_video_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store
    checkpoint_manager = services.checkpoint_manager
    video_engine = services.video_engine
    refresh_video_engine = services.refresh_video_engine

    @app.get("/api/videos/tasks")
    async def list_video_tasks(
        project_id: str,
        request: Request,
        segment_id: str | None = None,
        sync: bool = False,
    ) -> dict:
        require_project_access(store, request.state.user, project_id, "read")
        try:
            if sync:
                user_config = _load_api_config(store, user_id=request.state.user.id)
                refresh_video_engine(user_config)
                tasks = await sync_project_video_tasks(project_id, store, video_engine)
                if segment_id:
                    tasks = [task for task in tasks if task.segment_id == segment_id]
            else:
                tasks = store.list_video_tasks(project_id, segment_id=segment_id)
            return {"tasks": [_dump(task) for task in tasks]}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/videos/tasks/sync")
    async def sync_video_tasks(project_id: str, request: Request) -> dict:
        require_project_access(store, request.state.user, project_id, "read")
        try:
            user_config = _load_api_config(store, user_id=request.state.user.id)
            refresh_video_engine(user_config)
            tasks = await sync_project_video_tasks(project_id, store, video_engine)
            return {"tasks": [_dump(task) for task in tasks]}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/videos/tasks/{task_id}")
    def get_video_task(task_id: str, request: Request) -> dict:
        try:
            task = store.get_video_task(task_id)
            require_project_access(store, request.state.user, task.project_id, "read")
            return _dump(task)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/videos/tasks/{task_id}")
    def delete_video_task(task_id: str, request: Request) -> dict:
        try:
            task = store.get_video_task(task_id)
            require_project_access(store, request.state.user, task.project_id, "write")
            store.delete_video_task(task_id)
            return {"deleted": True, "task_id": task_id}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/videos/tasks/{task_id}/retry")
    async def retry_video_task(task_id: str, request: RetryVideoTaskRequest = RetryVideoTaskRequest()) -> dict:
        try:
            previous = store.get_video_task(task_id)
            project = store.get_project(previous.project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        overrides = request.model_dump(exclude_unset=True)
        prompt = str(overrides.pop("prompt", previous.prompt) or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="提示词不能为空")
        _ensure_video_generation_allowed(project, prompt, previous.is_preview, checkpoint_manager)

        if overrides:
            try:
                assets, duration = assets_for_retry_task(store, previous, prompt, **overrides)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            assets = dict(previous.assets)
            duration = previous.duration

        task = VideoTask(
            project_id=previous.project_id,
            segment_id=previous.segment_id,
            prompt=prompt,
            assets=assets,
            duration=duration,
            prompt_card_id=previous.prompt_card_id,
            source_prompt_hash=previous.source_prompt_hash,
            is_preview=previous.is_preview,
            version=store.next_video_task_version(previous.project_id, previous.segment_id),
            prompt_version=previous.prompt_version,
            provider=video_engine.provider,
            attempt=max(1, previous.attempt + 1),
        )
        result = await _run_and_store_video_task(task, previous.is_preview, store, video_engine)
        return _dump(result)

    @app.get("/api/videos/tasks/{task_id}/download")
    def download_video_task(task_id: str, inline: bool = False):
        try:
            task = store.get_video_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not task.result_path:
            raise HTTPException(status_code=404, detail="视频文件尚未就绪")
        from pathlib import Path

        from ai_video_manager.project_bundle import resolve_project_data_root, stored_path_value

        raw = str(task.result_path).strip()
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (store.workspace_root / raw).resolve()
        if not path.exists() or not path.is_file():
            # 兼容旧记录里混进 Windows 盘符的绝对路径 / 相对 generated 路径
            name = Path(raw.replace("\\", "/")).name
            fallback = resolve_project_data_root(store, task.project_id) / "generated" / task.segment_id / name
            if fallback.exists() and fallback.is_file():
                path = fallback
            else:
                raise HTTPException(status_code=404, detail="视频文件不存在")
        if path.stat().st_size <= 0:
            raise HTTPException(status_code=404, detail="视频文件为空，请用「追回」重新拉取远端成片")
        # 顺手把可相对化的路径写回，避免后续下载再踩坑
        try:
            relative = stored_path_value(store, path)
            if relative != raw:
                task.result_path = relative
                store.save_video_task(task)
        except Exception:
            pass
        return FileResponse(
            path,
            filename=path.name,
            media_type="video/mp4",
            content_disposition_type="inline" if inline else "attachment",
        )

    @app.post("/api/videos/tasks/{task_id}/recover")
    async def recover_video_task(task_id: str, request: RecoverVideoTaskRequest = RecoverVideoTaskRequest()) -> dict:
        """Poll remote gateway by api_task_id and download result without re-submitting."""
        try:
            task = store.get_video_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        result = await recover_and_store_video_task(
            task,
            store,
            video_engine,
            api_task_id=request.api_task_id,
        )
        return _dump(result)

    @app.post("/api/videos/generate")
    async def generate_video(body: GenerateVideoRequest, http_request: Request) -> dict:
        user_config = _load_api_config(store, user_id=http_request.state.user.id)
        refresh_video_engine(user_config)
        try:
            project = store.get_project(body.project_id)
            prompt = body.prompt
            source_prompt_hash = ""
            prompt_version = 1
            card = None
            if body.prompt_card_id:
                card = store.get_prompt_card(body.prompt_card_id)
                if card.project_id != body.project_id or card.segment_id != body.segment_id:
                    raise ValueError("Prompt card does not belong to the requested project segment")
                prompt = card.prompt_text
                source_prompt_hash = card.source_hash
                prompt_version = max(1, store.count_prompt_card_versions(card.id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _ensure_video_generation_allowed(project, prompt, body.preview, checkpoint_manager)
        task = build_video_task_from_generate_request(
            store,
            body,
            provider=video_engine.provider,
            prompt=prompt,
            source_prompt_hash=source_prompt_hash,
            prompt_version=prompt_version,
            prompt_card=card,
        )
        result = await _run_and_store_video_task(task, body.preview, store, video_engine)
        return _dump(result)
