from __future__ import annotations

import logging

from ai_video_manager.api.config import _load_api_config
from ai_video_manager.api.video_tasks import _run_and_store_video_task, _spawn_recover_video_task
from ai_video_manager.video_generation import VideoGenerationEngine, build_video_adapter

logger = logging.getLogger(__name__)


async def recover_incomplete_video_tasks(services) -> dict[str, int]:
    """Resume persisted video work without blocking application startup."""
    report = {"found": 0, "remote_recovery": 0, "resubmitted": 0, "waiting_config": 0}
    for task in services.store.list_incomplete_video_tasks():
        report["found"] += 1
        try:
            project = services.store.get_project(task.project_id)
            config = _load_api_config(services.store, user_id=project.owner_id or None)
            adapter = build_video_adapter(config)
        except (KeyError, RuntimeError, ValueError) as exc:
            task.error_message = f"启动恢复等待视频服务配置：{exc}"
            services.store.save_video_task(task)
            report["waiting_config"] += 1
            continue

        engine = VideoGenerationEngine(
            api_client=adapter,
            archive_root=services.video_engine.archive_root,
            archive_path_resolver=services.video_engine.archive_path_resolver,
        )
        if task.api_task_id:
            _spawn_recover_video_task(task, services.store, engine, api_task_id=task.api_task_id)
            report["remote_recovery"] += 1
            continue

        if task.status.value == "processing":
            task.attempt = max(1, int(task.attempt or 0)) + 1
        try:
            await _run_and_store_video_task(task, task.is_preview, services.store, engine)
            report["resubmitted"] += 1
        except Exception as exc:
            task.error_message = f"启动恢复提交失败：{exc}"
            services.store.save_video_task(task)
            logger.exception("Failed to resume video task %s", task.id)
    return report
