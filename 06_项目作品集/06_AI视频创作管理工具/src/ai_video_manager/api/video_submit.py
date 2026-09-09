"""Shared video-task assembly for generate / prompt-card video routes.

Keep asset merge + VideoTask construction in one place so
`video_routes` and `prompt_pipeline_routes` stay thin.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ai_video_manager.api.video_assets import (
    apply_reference_mode,
    collect_prompt_card_assets,
    collect_video_assets,
    merge_video_assets,
    resolve_prompt_mentions,
)
from ai_video_manager.api.video_tasks import attach_video_request_settings, video_request_settings
from ai_video_manager.models import PromptCard, VideoTask
from ai_video_manager.storage import SQLiteStore


def assemble_generation_assets(
    store: SQLiteStore,
    *,
    project_id: str,
    segment_id: str,
    prompt: str,
    request_assets: dict[str, object] | None,
    reference_mode: str | None,
    first_frame: str | None,
    last_frame: str | None,
    reference_images: list[str] | None,
    reference_videos: list[str] | None,
    reference_audios: list[str] | None,
    model: str | None,
    aspect_ratio: str | None,
    resolution: str | None,
    duration: int | None,
    generate_audio: bool | None,
    prompt_card: PromptCard | None = None,
) -> dict[str, object]:
    """Collect entity/card/mention assets and apply reference mode + request settings."""
    assets = collect_video_assets(
        store=store,
        project_id=project_id,
        segment_id=segment_id,
        request_assets=request_assets,
    )
    if prompt_card is not None:
        assets = merge_video_assets(assets, collect_prompt_card_assets(store, prompt_card))
        existing_anchor = prompt_card.anchor_text
    else:
        existing_anchor = ""

    mention_assets = resolve_prompt_mentions(
        store,
        project_id,
        prompt,
        existing_anchor_text=existing_anchor,
    ).get("assets")
    if isinstance(mention_assets, dict):
        assets = merge_video_assets(assets, mention_assets)

    try:
        assets = apply_reference_mode(
            assets,
            reference_mode=reference_mode,
            first_frame=first_frame,
            last_frame=last_frame,
            reference_images=reference_images,
            reference_videos=reference_videos,
            reference_audios=reference_audios,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return attach_video_request_settings(
        assets,
        video_request_settings(
            model=model,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=duration,
            generate_audio=generate_audio,
        ),
    )


def build_video_task_from_prompt_card(
    store: SQLiteStore,
    card: PromptCard,
    request: Any,
    *,
    provider: str,
) -> VideoTask:
    duration = request.duration or int(card.duration or 0) or None
    assets = assemble_generation_assets(
        store,
        project_id=card.project_id,
        segment_id=card.segment_id,
        prompt=card.prompt_text,
        request_assets=request.assets,
        reference_mode=request.reference_mode,
        first_frame=request.first_frame,
        last_frame=request.last_frame,
        reference_images=request.reference_images,
        reference_videos=request.reference_videos,
        reference_audios=request.reference_audios,
        model=request.model,
        aspect_ratio=request.aspect_ratio,
        resolution=request.resolution,
        duration=duration,
        generate_audio=request.generate_audio,
        prompt_card=card,
    )
    return VideoTask(
        project_id=card.project_id,
        segment_id=card.segment_id,
        prompt=card.prompt_text,
        assets=assets,
        duration=duration,
        prompt_card_id=card.id,
        source_prompt_hash=card.source_hash,
        is_preview=bool(request.preview),
        version=store.next_video_task_version(card.project_id, card.segment_id),
        provider=provider,
    )


def build_video_task_from_generate_request(
    store: SQLiteStore,
    body: Any,
    *,
    provider: str,
    prompt: str,
    source_prompt_hash: str,
    prompt_version: int,
    prompt_card: PromptCard | None,
) -> VideoTask:
    assets = assemble_generation_assets(
        store,
        project_id=body.project_id,
        segment_id=body.segment_id,
        prompt=prompt,
        request_assets=body.assets,
        reference_mode=body.reference_mode,
        first_frame=body.first_frame,
        last_frame=body.last_frame,
        reference_images=body.reference_images,
        reference_videos=body.reference_videos,
        reference_audios=body.reference_audios,
        model=body.model,
        aspect_ratio=body.aspect_ratio,
        resolution=body.resolution,
        duration=body.duration,
        generate_audio=body.generate_audio,
        prompt_card=prompt_card,
    )
    return VideoTask(
        project_id=body.project_id,
        segment_id=body.segment_id,
        prompt=prompt,
        assets=assets,
        duration=body.duration,
        prompt_card_id=body.prompt_card_id,
        source_prompt_hash=source_prompt_hash,
        is_preview=bool(body.preview),
        version=store.next_video_task_version(body.project_id, body.segment_id),
        prompt_version=prompt_version,
        provider=provider,
    )
