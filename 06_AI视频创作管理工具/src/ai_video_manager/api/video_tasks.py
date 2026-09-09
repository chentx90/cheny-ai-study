from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

from fastapi import HTTPException

from ai_video_manager.api.job_runner import video_job_runner
from ai_video_manager.api.video_assets import (
    apply_reference_mode,
    collect_prompt_card_assets,
    collect_video_assets,
    merge_video_assets,
    prepare_video_assets,
    prioritize_character_reference_images,
    resolve_prompt_mentions,
)
from ai_video_manager.gateway_media import GatewayMediaClient, media_uploader_from_client
from ai_video_manager.models import Project, TaskStatus, VideoTask, WorkflowState
from ai_video_manager.storage import SQLiteStore
from ai_video_manager.video_client import LangChainVideoClient
from ai_video_manager.video_generation import (
    LangChainVideoAPIAdapter,
    VideoGenerationEngine,
    video_task_settings,
)
from ai_video_manager.workflow import CheckpointManager
from ai_video_manager.xyq_cli import is_xyq_provider


def _gateway_media_uploader(video_engine: VideoGenerationEngine, *, model: str | None = None):
    if is_xyq_provider(video_engine.provider):
        return None
    adapter = video_engine.api_client
    if not isinstance(adapter, LangChainVideoAPIAdapter):
        return None
    client = getattr(adapter, "client", None)
    if not isinstance(client, LangChainVideoClient):
        return None
    media = GatewayMediaClient(
        provider=client.provider,
        base_url=client.base_url,
        api_key=client.api_key,
        timeout_seconds=max(float(client.timeout_seconds or 20), 120.0),
        allow_insecure_ssl=bool(client.allow_insecure_ssl),
        default_model=str(model or "").strip() or None,
    )
    return media_uploader_from_client(media)

def _video_jobs_inline() -> bool:
    """Tests await poll/download inline so assertions see final status."""
    flag = str(os.environ.get("AVM_VIDEO_INLINE") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    return "pytest" in sys.modules


def _set_video_task_phase(task: VideoTask, phase: str) -> None:
    snapshot = dict(task.request_snapshot or {})
    if "request" not in snapshot:
        snapshot["request"] = {
            "prompt": task.prompt,
            "assets": task.assets,
            "duration": task.duration,
            "prompt_card_id": task.prompt_card_id,
            "episode_id": task.segment_id,
            "is_preview": task.is_preview,
            "provider": task.provider,
        }
    snapshot["lifecycle"] = {
        "phase": phase,
        "attempt": task.attempt,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    task.request_snapshot = snapshot


def _ensure_video_generation_allowed(
    project: Project,
    prompt: str,
    preview: bool,
    checkpoint_manager: CheckpointManager,
) -> None:
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required before video generation")
    if preview:
        if not project.has_prompts:
            raise HTTPException(status_code=400, detail="Generate prompts before creating a video preview")
        return
    if not project.has_prompts:
        raise HTTPException(status_code=400, detail="Generate prompts before creating a full video")


async def _finalize_video_task(
    *,
    task: VideoTask,
    runtime_task: VideoTask,
    preview: bool,
    store: SQLiteStore,
    video_engine: VideoGenerationEngine,
) -> VideoTask:
    try:
        result = await video_engine.wait_until_done(runtime_task)
    except asyncio.CancelledError:
        runtime_task.status = TaskStatus.PROCESSING
        runtime_task.error_message = "服务重启中，远端任务可稍后追回"
        _set_video_task_phase(runtime_task, "interrupted")
        store.save_video_task(runtime_task)
        _sync_project_after_video_task(store, runtime_task, preview=preview)
        raise
    except Exception as exc:
        runtime_task.status = TaskStatus.FAILED
        runtime_task.error_message = str(exc)
        result = runtime_task
    result.assets = task.assets
    if result.result_path:
        from pathlib import Path

        from ai_video_manager.project_bundle import stored_path_value

        try:
            result.result_path = stored_path_value(store, Path(str(result.result_path)))
        except Exception:
            pass
    _set_video_task_phase(result, "completed" if result.status == TaskStatus.COMPLETED else "failed")
    store.save_video_task(result)
    if result.status == TaskStatus.COMPLETED and result.result_path:
        store.record_video_output(result)
    _sync_project_after_video_task(store, result, preview=preview)
    return result


async def _submit_and_finalize_video_task(
    *,
    task: VideoTask,
    runtime_task: VideoTask,
    preview: bool,
    store: SQLiteStore,
    video_engine: VideoGenerationEngine,
) -> VideoTask:
    """CLI/API submit + poll/download. Runs off the HTTP request so reload can finish."""

    def _persist_submitted(submitted: VideoTask) -> None:
        # 远端已接单时立刻落库 api_task_id，网络波动后仍可追回
        task.api_task_id = submitted.api_task_id
        task.status = submitted.status
        task.provider = submitted.provider
        task.error_message = None
        _set_video_task_phase(task, "submitted")
        store.save_video_task(task)

    try:
        submitted = (
            await video_engine.generate_preview(
                runtime_task,
                duration=runtime_task.duration or 4,
                on_submitted=_persist_submitted,
                wait=False,
            )
            if preview
            else await video_engine.generate_full_video(
                runtime_task,
                on_submitted=_persist_submitted,
                wait=False,
            )
        )
    except asyncio.CancelledError:
        task.status = TaskStatus.PROCESSING
        task.error_message = "服务重启中，远端任务可稍后追回"
        _set_video_task_phase(task, "interrupted")
        store.save_video_task(task)
        _sync_project_after_video_task(store, task, preview=preview)
        raise

    submitted.assets = task.assets
    if submitted.result_path:
        from pathlib import Path

        from ai_video_manager.project_bundle import stored_path_value

        try:
            submitted.result_path = stored_path_value(store, Path(str(submitted.result_path)))
        except Exception:
            pass
    _set_video_task_phase(
        submitted,
        "completed" if submitted.status == TaskStatus.COMPLETED else (
            "failed" if submitted.status == TaskStatus.FAILED else "submitted"
        ),
    )
    store.save_video_task(submitted)
    if submitted.status == TaskStatus.COMPLETED and submitted.result_path:
        store.record_video_output(submitted)

    if submitted.status == TaskStatus.FAILED or not submitted.api_task_id:
        _sync_project_after_video_task(store, submitted, preview=preview)
        return submitted

    return await _finalize_video_task(
        task=task,
        runtime_task=submitted,
        preview=preview,
        store=store,
        video_engine=video_engine,
    )


async def _run_and_store_video_task(
    task: VideoTask,
    preview: bool,
    store: SQLiteStore,
    video_engine: VideoGenerationEngine,
) -> VideoTask:
    if video_engine.provider == "unconfigured":
        raise HTTPException(status_code=400, detail="视频服务未配置，请先在设置中填写视频 Base URL 和 API Key")

    # Persist the queue item before any upload or remote API call.
    task.status = TaskStatus.PENDING
    task.provider = video_engine.provider
    task.attempt = max(1, int(task.attempt or 0))
    task.error_message = None
    _set_video_task_phase(task, "queued")
    store.save_video_task(task)
    if not preview:
        project = store.get_project(task.project_id)
        project.current_state = WorkflowState.VIDEO_GENERATING
        store.save_project(project)
    _sync_project_after_video_task(store, task, preview=preview)

    settings = video_task_settings(task)
    model = str(settings.get("model") or "").strip() or None

    async def _prepare_submit_and_finalize() -> VideoTask:
        task.status = TaskStatus.PROCESSING
        _set_video_task_phase(task, "preparing")
        store.save_video_task(task)
        try:
            ordered_assets = prioritize_character_reference_images(dict(task.assets))
            prepared_assets = await asyncio.to_thread(
                prepare_video_assets,
                store,
                task.project_id,
                ordered_assets,
                provider=video_engine.provider,
                uploader=_gateway_media_uploader(video_engine, model=model),
            )
            # 审计：把实际上云 URL 写入 settings，便于排查「有任务但无参考」
            from ai_video_manager.video_refs import collect_typed_references

            mode = str(prepared_assets.get("reference_mode") or "none")
            typed = collect_typed_references(prepared_assets, reference_mode=mode)
            settings_out = dict(prepared_assets.get("settings") or {}) if isinstance(prepared_assets.get("settings"), dict) else {}
            settings_out["prepared_reference_images"] = [item["url"] for item in (typed.get("images") or [])][:9]
            settings_out["prepared_reference_videos"] = [item["url"] for item in (typed.get("videos") or [])][:3]
            settings_out["prepared_reference_audios"] = [item["url"] for item in (typed.get("audios") or [])][:3]
            settings_out["outbound_ref_count"] = (
                len(settings_out["prepared_reference_images"])
                + len(settings_out["prepared_reference_videos"])
                + len(settings_out["prepared_reference_audios"])
            )
            if mode != "none" and int(settings_out["outbound_ref_count"] or 0) <= 0:
                raise ValueError(
                    f"参考模式为 {mode}，但准备后 outbound 引用数为 0，已中止提交（避免空参考浪费额度）。"
                )
            # 硬门槛：提交前先确认 OSS/公网 URL 真能拉到字节
            from ai_video_manager.gateway_media import verify_http_refs_reachable

            verify_urls = (
                list(settings_out["prepared_reference_images"])
                + list(settings_out["prepared_reference_videos"])
                + list(settings_out["prepared_reference_audios"])
            )
            fetch_report = verify_http_refs_reachable(verify_urls) if verify_urls else []
            settings_out["ref_fetch_ok"] = True
            settings_out["ref_fetch_checks"] = [
                {
                    "url": str(item.get("url") or "")[:200],
                    "ok": bool(item.get("ok")),
                    "status": item.get("status"),
                    "bytes": item.get("bytes"),
                    "content_type": item.get("content_type"),
                    "skipped": item.get("skipped"),
                }
                for item in fetch_report
            ]
            prepared_assets["settings"] = settings_out
            # 保留本地路径供 UI，同时记下远端引用
            task.assets = dict(task.assets or {})
            task_settings = dict(task.assets.get("settings") or {}) if isinstance(task.assets.get("settings"), dict) else {}
            task_settings.update(
                {
                    "prepared_reference_images": settings_out["prepared_reference_images"],
                    "prepared_reference_videos": settings_out["prepared_reference_videos"],
                    "prepared_reference_audios": settings_out["prepared_reference_audios"],
                    "outbound_ref_count": settings_out["outbound_ref_count"],
                    "ref_fetch_ok": True,
                    "ref_fetch_checks": settings_out["ref_fetch_checks"],
                }
            )
            task.assets["settings"] = task_settings
            store.save_video_task(task)
        except ValueError as exc:
            task.status = TaskStatus.FAILED
            task.error_message = str(exc)
            _set_video_task_phase(task, "failed")
            store.save_video_task(task)
            _sync_project_after_video_task(store, task, preview=preview)
            return task
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error_message = f"准备参考素材失败：{exc}"
            _set_video_task_phase(task, "failed")
            store.save_video_task(task)
            _sync_project_after_video_task(store, task, preview=preview)
            return task

        runtime_task = VideoTask(
            id=task.id,
            project_id=task.project_id,
            segment_id=task.segment_id,
            prompt=task.prompt,
            assets=prepared_assets,
            duration=task.duration,
            prompt_card_id=task.prompt_card_id,
            source_prompt_hash=task.source_prompt_hash,
            is_preview=task.is_preview,
            version=task.version,
            provider=task.provider or video_engine.provider,
            status=TaskStatus.PROCESSING,
            api_task_id=task.api_task_id,
            request_snapshot=dict(task.request_snapshot),
            attempt=task.attempt,
        )
        return await _submit_and_finalize_video_task(
            task=task,
            runtime_task=runtime_task,
            preview=preview,
            store=store,
            video_engine=video_engine,
        )

    # Return immediately; OSS upload + CLI/API submit must not block the HTTP response.
    job = video_job_runner.spawn(
        _prepare_submit_and_finalize(),
        name=f"video-submit:{task.id}",
    )
    if _video_jobs_inline():
        await job
        return store.get_video_task(task.id)

    return task


async def sync_video_task_status(
    task: VideoTask,
    store: SQLiteStore,
    video_engine: VideoGenerationEngine,
) -> VideoTask:
    """One-shot remote status check; download in background when already completed."""
    if task.status != TaskStatus.PROCESSING:
        if task.status == TaskStatus.COMPLETED and task.result_path:
            store.record_video_output(task)
        return task

    remote_id = str(task.api_task_id or "").strip()
    if not remote_id:
        anchor = task.updated_at or task.created_at
        age_seconds = 0.0
        if anchor is not None:
            now = datetime.now(timezone.utc)
            anchor_aware = anchor if anchor.tzinfo is not None else anchor.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (now - anchor_aware).total_seconds())
        if age_seconds > 600:
            task.status = TaskStatus.FAILED
            task.error_message = "提交阶段未完成，未拿到远端任务 ID，请重试"
            store.save_video_task(task)
            _sync_project_after_video_task(store, task, preview=task.is_preview)
        return task

    if video_engine.provider == "unconfigured":
        task.error_message = "视频服务未配置，无法同步远端状态"
        store.save_video_task(task)
        return task

    try:
        status = await video_engine.api_client.check_status(remote_id)
    except Exception as exc:
        task.error_message = f"状态查询失败：{exc}"
        store.save_video_task(task)
        return task

    if status == TaskStatus.PROCESSING:
        store.save_video_task(task)
        return task

    if status == TaskStatus.FAILED:
        remote_error = str(getattr(video_engine.api_client, "last_status_error", "") or "").strip()
        task.status = TaskStatus.FAILED
        task.error_message = remote_error or "远端视频任务失败"
        store.save_video_task(task)
        _sync_project_after_video_task(store, task, preview=task.is_preview)
        return task

    if status == TaskStatus.COMPLETED:
        task.status = TaskStatus.PROCESSING
        task.error_message = "远端已完成，正在下载成片…"
        store.save_video_task(task)
        _spawn_recover_video_task(task, store, video_engine, api_task_id=remote_id)
        return task

    store.save_video_task(task)
    return task


async def sync_project_video_tasks(
    project_id: str,
    store: SQLiteStore,
    video_engine: VideoGenerationEngine,
) -> list[VideoTask]:
    tasks = store.list_video_tasks(project_id)
    for task in tasks:
        if task.status == TaskStatus.PROCESSING:
            await sync_video_task_status(task, store, video_engine)
    return store.list_video_tasks(project_id)


def _spawn_recover_video_task(
    task: VideoTask,
    store: SQLiteStore,
    video_engine: VideoGenerationEngine,
    *,
    api_task_id: str | None = None,
) -> None:
    remote_id = str(api_task_id or task.api_task_id or "").strip()
    if not remote_id:
        return

    async def _recover() -> VideoTask:
        _set_video_task_phase(task, "recovering")
        store.save_video_task(task)
        try:
            result = await video_engine.recover_task(task, api_task_id=remote_id, timeout=180)
        except asyncio.CancelledError:
            task.status = TaskStatus.PROCESSING
            task.error_message = "服务重启中，远端任务可稍后追回"
            _set_video_task_phase(task, "interrupted")
            store.save_video_task(task)
            raise
        _set_video_task_phase(result, "completed" if result.status == TaskStatus.COMPLETED else "failed")
        store.save_video_task(result)
        if result.status == TaskStatus.COMPLETED and result.result_path:
            store.record_video_output(result)
        _sync_project_after_video_task(store, result, preview=result.is_preview)
        return result

    video_job_runner.spawn(_recover(), name=f"video-recover:{task.id}")


async def recover_and_store_video_task(
    task: VideoTask,
    store: SQLiteStore,
    video_engine: VideoGenerationEngine,
    *,
    api_task_id: str | None = None,
) -> VideoTask:
    if video_engine.provider == "unconfigured":
        raise HTTPException(status_code=400, detail="视频服务未配置，请先在设置中填写视频 Base URL 和 API Key")

    remote_id = str(api_task_id or task.api_task_id or "").strip()
    if not remote_id:
        raise HTTPException(status_code=400, detail="没有远端任务 ID，无法追回。请填写网关返回的 task id。")

    task.api_task_id = remote_id
    task.status = TaskStatus.PROCESSING
    task.error_message = None
    _set_video_task_phase(task, "recovering")
    store.save_video_task(task)

    async def _recover() -> VideoTask:
        try:
            # 用户主动追回：短轮询即可，远端通常已完成。
            result = await video_engine.recover_task(task, api_task_id=remote_id, timeout=180)
        except asyncio.CancelledError:
            task.status = TaskStatus.PROCESSING
            task.error_message = "服务重启中，远端任务可稍后追回"
            _set_video_task_phase(task, "interrupted")
            store.save_video_task(task)
            raise
        _set_video_task_phase(result, "completed" if result.status == TaskStatus.COMPLETED else "failed")
        store.save_video_task(result)
        if result.status == TaskStatus.COMPLETED and result.result_path:
            store.record_video_output(result)
        _sync_project_after_video_task(store, result, preview=result.is_preview)
        return result

    job = video_job_runner.spawn(_recover(), name=f"video-recover:{task.id}")
    if _video_jobs_inline():
        return await job
    return task


def _sync_project_after_video_task(store: SQLiteStore, result: VideoTask, *, preview: bool) -> None:
    project = store.get_project(result.project_id)
    if preview:
        return
    if result.status.value == "completed":
        project.has_completed_video = True
        project.current_state = WorkflowState.VIDEO_COMPLETED
    elif project.current_state == WorkflowState.VIDEO_GENERATING:
        project.current_state = (
            WorkflowState.PROMPTS_GENERATED if project.has_prompts else WorkflowState.ASSETS_CONFIRMED
        )
    store.save_project(project)


def video_request_settings(
    *,
    model: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    duration: int | None = None,
    generate_audio: bool | None = None,
) -> dict[str, object]:
    settings: dict[str, object] = {}
    clean_model = str(model or "").strip()
    clean_aspect_ratio = str(aspect_ratio or "").strip()
    clean_resolution = str(resolution or "").strip()
    if clean_model:
        settings["model"] = clean_model
    if clean_aspect_ratio:
        settings["aspect_ratio"] = clean_aspect_ratio
    if clean_resolution:
        settings["resolution"] = clean_resolution
    if duration:
        settings["duration"] = int(duration)
    if generate_audio is not None:
        settings["generate_audio"] = bool(generate_audio)
    elif "generate_audio" not in settings:
        settings["generate_audio"] = True
    return settings


def attach_video_request_settings(assets: dict[str, object], settings: dict[str, object]) -> dict[str, object]:
    merged = dict(assets or {})
    if not settings:
        return merged
    existing = merged.get("settings") if isinstance(merged.get("settings"), dict) else {}
    merged["settings"] = {**existing, **settings}
    return merged


def assets_for_retry_task(
    store: SQLiteStore,
    previous: VideoTask,
    prompt: str,
    *,
    reference_mode: str | None = None,
    first_frame: str | None = None,
    last_frame: str | None = None,
    reference_images: list[str] | None = None,
    reference_videos: list[str] | None = None,
    reference_audios: list[str] | None = None,
    model: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    duration: int | None = None,
    generate_audio: bool | None = None,
) -> tuple[dict[str, object], int | None]:
    """Rebuild task assets from the prior task, optionally applying edited refs and gateway params."""
    previous_assets = dict(previous.assets or {})
    card = None
    if previous.prompt_card_id:
        try:
            card = store.get_prompt_card(previous.prompt_card_id)
        except KeyError:
            card = None

    if card:
        mention_assets = resolve_prompt_mentions(
            store,
            card.project_id,
            prompt,
            existing_anchor_text=card.anchor_text,
        ).get("assets")
        assets = collect_video_assets(
            store=store,
            project_id=card.project_id,
            segment_id=card.segment_id,
            request_assets={},
        )
        assets = merge_video_assets(assets, collect_prompt_card_assets(store, card))
        if isinstance(mention_assets, dict):
            assets = merge_video_assets(assets, mention_assets)
    else:
        assets = {
            key: value
            for key, value in previous_assets.items()
            if key
            not in {
                "reference_mode",
                "first_frame",
                "last_frame",
                "reference_images",
                "reference_videos",
                "reference_audios",
                "video_clips",
                "audio_samples",
                "settings",
            }
        }

    prior_settings = previous_assets.get("settings") if isinstance(previous_assets.get("settings"), dict) else {}
    ref_mode = reference_mode if reference_mode is not None else str(previous_assets.get("reference_mode") or "omni")
    assets = apply_reference_mode(
        assets,
        reference_mode=ref_mode,
        first_frame=first_frame if first_frame is not None else previous_assets.get("first_frame"),
        last_frame=last_frame if last_frame is not None else previous_assets.get("last_frame"),
        reference_images=reference_images if reference_images is not None else None,
        reference_videos=reference_videos if reference_videos is not None else None,
        reference_audios=reference_audios if reference_audios is not None else None,
    )
    resolved_duration = duration if duration is not None else previous.duration or prior_settings.get("duration")
    assets = attach_video_request_settings(
        assets,
        video_request_settings(
            model=model if model is not None else prior_settings.get("model"),
            aspect_ratio=aspect_ratio if aspect_ratio is not None else prior_settings.get("aspect_ratio"),
            resolution=resolution if resolution is not None else prior_settings.get("resolution"),
            duration=int(resolved_duration) if resolved_duration else None,
            generate_audio=generate_audio if generate_audio is not None else prior_settings.get("generate_audio"),
        ),
    )
    return assets, int(resolved_duration) if resolved_duration else None
