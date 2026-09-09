"""Resolve generated video archive paths and human-readable filenames."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ai_video_manager.models import VideoTask
from ai_video_manager.storage import SQLiteStore


def _sanitize_part(text: str, *, fallback: str = "未命名", max_len: int = 48) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", str(text or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_len]


def _segment_title_body(title: str, order: int) -> str:
    raw = str(title or "").strip()
    match = re.match(rf"^片段{order}[：:\s\-—]*(.*)$", raw)
    if match:
        body = str(match.group(1) or "").strip()
        return body or raw
    match = re.match(r"^片段\d+[：:\s\-—]*(.*)$", raw)
    if match and str(match.group(1) or "").strip():
        return str(match.group(1)).strip()
    return raw or f"片段{order}"


def build_video_archive_filename(
    store: SQLiteStore,
    task: VideoTask,
    *,
    timestamp: datetime | None = None,
) -> str:
    project = store.get_project(task.project_id)
    episode_order = 1
    episode_title = f"第{episode_order}集"
    for segment in store.list_project_segments(task.project_id):
        if segment["id"] == task.segment_id:
            episode_order = int(segment.get("order") or 1)
            episode_title = str(segment.get("title") or f"第{episode_order}集").strip()
            break

    shot_order = 1
    shot_title = "分镜"
    prompt_version = int(getattr(task, "prompt_version", None) or 1)
    if task.prompt_card_id:
        try:
            card = store.get_prompt_card(task.prompt_card_id)
            shot_order = int(card.order or 1)
            shot_title = _segment_title_body(card.title, shot_order)
            prompt_version = max(prompt_version, store.count_prompt_card_versions(card.id))
        except KeyError:
            pass

    when = timestamp or task.created_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")

    parts = [
        _sanitize_part(project.name, fallback="项目"),
        _sanitize_part(episode_title, fallback=f"第{episode_order}集"),
        f"片段{shot_order}{_sanitize_part(shot_title, fallback='分镜')}",
        f"提示v{prompt_version}重跑v{int(task.version or 1)}",
        stamp,
    ]
    return "-".join(parts) + ".mp4"


def resolve_output_root(store: SQLiteStore, project_id: str) -> Path | None:
    preprocess = store.get_preprocess(project_id) or {}
    raw = str(preprocess.get("output_root") or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser()
    if not root.is_absolute():
        root = (store.workspace_root / raw).resolve()
    return root


def resolve_video_archive_path(store: SQLiteStore, task: VideoTask) -> Path:
    from ai_video_manager.project_bundle import resolve_project_data_root

    filename = build_video_archive_filename(store, task)
    custom_root = resolve_output_root(store, task.project_id)
    if custom_root is not None:
        custom_root.mkdir(parents=True, exist_ok=True)
        return custom_root / filename
    project_root = resolve_project_data_root(store, task.project_id)
    target_dir = project_root / "generated" / task.segment_id
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / filename
