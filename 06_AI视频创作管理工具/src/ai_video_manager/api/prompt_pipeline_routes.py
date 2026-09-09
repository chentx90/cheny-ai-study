from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from ai_video_manager.api.config import _load_api_config
from ai_video_manager.api.schemas import (
    GeneratePromptCardsRequest,
    GeneratePromptCardVideoRequest,
    ResolveMentionsRequest,
    RerunPromptCardRequest,
    SavePromptCardRequest,
    SavePromptCardSubjectsRequest,
)
from ai_video_manager.api.utils import _dump
from ai_video_manager.api.video_assets import (
    entity_cards_by_ids,
    format_subject_anchor_text,
    match_prompt_card_subjects,
    parse_subject_match_entity_ids,
    resolve_prompt_mentions,
    subject_match_entity_catalog_json,
    subject_match_prompt_card_json,
)
from ai_video_manager.api.video_submit import build_video_task_from_prompt_card
from ai_video_manager.api.video_tasks import (
    _ensure_video_generation_allowed,
    _run_and_store_video_task,
)
from ai_video_manager.application.ai_runs import TrackedLLMClient
from ai_video_manager.infrastructure.db.production_repository import ProductionRepository
from ai_video_manager.llm import build_llm_client, llm_use_case_config, parse_json_list_payload
from ai_video_manager.models import PromptCard
from ai_video_manager.prompt_engine import (
    PromptEngine,
    PromptTemplateError,
    request_template_for_category,
    template_context,
    template_for_category,
)
from ai_video_manager.prompt_pipeline import (
    build_prompt_cards_from_script,
    entity_catalog_json,
    prompt_card_target_json,
    prompt_card_with_inferred_source,
    prompt_cards_context_json,
    rerun_prompt_card_from_script,
)
from ai_video_manager.storage import SQLiteStore
from ai_video_manager.video_generation import VideoGenerationEngine
from ai_video_manager.workflow import CheckpointManager


def register_prompt_pipeline_routes(
    app: FastAPI,
    *,
    store: SQLiteStore,
    prompt_engine: PromptEngine,
    checkpoint_manager: CheckpointManager,
    video_engine: VideoGenerationEngine,
    production_repository: ProductionRepository,
) -> None:
    @app.get("/api/projects/{project_id}/segments/{segment_id}/prompt-cards")
    def list_segment_prompt_cards(project_id: str, segment_id: str) -> dict:
        try:
            return {"cards": [_dump(card) for card in store.list_prompt_cards(project_id, segment_id)]}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/segments/{segment_id}/prompt-cards/generate")
    def generate_segment_prompt_cards(
        project_id: str,
        segment_id: str,
        request: GeneratePromptCardsRequest,
        http_request: Request,
    ) -> dict:
        try:
            config = _load_api_config(store, user_id=http_request.state.user.id)
            split_config = llm_use_case_config(config, "prompt_split")
            write_config = llm_use_case_config(config, "video_generate")
            split_template = request_template_for_category(prompt_engine, "prompt_split", None)
            write_template = request_template_for_category(
                prompt_engine, "video_generate", request.template_name_or_id
            )
            if "script" not in split_template.variables:
                raise ValueError("提示词切分模板必须包含 $script 变量")
            if "script_excerpt" not in write_template.variables:
                raise ValueError("视频生成提示词模板必须包含 $script_excerpt 变量")
            entity_cards = store.list_entity_cards(project_id)
            project_style_prompt = store.get_project_style_prompt(project_id)
            duration_limit = request.max_duration_seconds
            expected_total = _format_expected_total_duration(request.expected_total_duration_seconds)
            split_prompt = prompt_engine.render_prompt(
                split_template,
                template_context(
                    split_template,
                    {
                        "script": request.script,
                        "entity_catalog": entity_catalog_json(entity_cards),
                        "max_duration_seconds": duration_limit,
                        "expected_total_duration_seconds": expected_total,
                        "project_style_prompt": project_style_prompt,
                    },
                ),
            )

            def render_write_prompt(values: dict[str, object]) -> str:
                return prompt_engine.render_prompt(
                    write_template,
                    template_context(
                        write_template,
                        {**values, "project_style_prompt": project_style_prompt},
                    ),
                )

            cards = build_prompt_cards_from_script(
                project_id=project_id,
                segment_id=segment_id,
                script=request.script,
                entity_cards=entity_cards,
                split_llm_client=TrackedLLMClient(
                    build_llm_client(config, "prompt_split"), production_repository,
                    "prompt_split", project_id, episode_id=segment_id,
                    template_id=split_template.id,
                    template_version=split_template.version,
                ),
                write_llm_client=TrackedLLMClient(
                    build_llm_client(config, "video_generate"), production_repository,
                    "video_generate", project_id, episode_id=segment_id,
                    template_id=write_template.id,
                    template_version=write_template.version,
                ),
                split_prompt=split_prompt,
                write_prompt_renderer=render_write_prompt,
                max_duration_seconds=duration_limit,
                temperature_split=float(split_config.get("temperature") or 0.3),
                temperature_write=float(write_config.get("temperature") or 0.6),
                max_tokens_split=int(split_config.get("maxTokens") or 100000),
                max_tokens_write=int(write_config.get("maxTokens") or 100000),
            )
            saved = store.save_prompt_cards(project_id, segment_id, cards, replace=request.replace)
            total_duration = sum(float(card.duration or 0) for card in saved)
            return {
                "cards": [_dump(card) for card in saved],
                "template_id": write_template.id,
                "split_template_id": split_template.id,
                "total_duration": total_duration,
            }
        except (KeyError, PromptTemplateError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/prompt-cards/{prompt_card_id}")
    def update_prompt_card(prompt_card_id: str, request: SavePromptCardRequest) -> dict:
        try:
            existing = store.get_prompt_card(prompt_card_id)
            card = PromptCard(
                id=existing.id,
                project_id=existing.project_id,
                segment_id=existing.segment_id,
                order=existing.order,
                title=request.title,
                prompt_text=request.prompt_text,
                anchor_text=request.anchor_text,
                duration=request.duration,
                source_text=existing.source_text if request.source_text is None else request.source_text,
                source_start=existing.source_start if request.source_start is None else request.source_start,
                source_end=existing.source_end if request.source_end is None else request.source_end,
                source_hash=existing.source_hash,
                status=request.status,
                locked=existing.locked if request.locked is None else request.locked,
                created_at=existing.created_at,
            )
            return _dump(store.save_prompt_card_with_version(card, "edited"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/prompt-cards/{prompt_card_id}/versions")
    def list_prompt_card_versions(prompt_card_id: str) -> dict:
        try:
            store.get_prompt_card(prompt_card_id)
            versions = store.list_prompt_card_versions(prompt_card_id)
            return {"versions": versions}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/prompt-cards/{prompt_card_id}/rerun")
    def rerun_prompt_card(prompt_card_id: str, request: RerunPromptCardRequest, http_request: Request) -> dict:
        try:
            target_card = store.get_prompt_card(prompt_card_id)
            if target_card.locked:
                raise ValueError("提示词卡片已锁定，请先解锁后再重跑")
            config = _load_api_config(store, user_id=http_request.state.user.id)
            use_config = llm_use_case_config(config, "prompt_rerun")
            template = request_template_for_category(prompt_engine, "prompt_rerun", request.template_name_or_id)
            if "script_excerpt" not in template.variables and "script" not in template.variables:
                raise ValueError("提示词单卡重跑模板必须包含 $script_excerpt 或 $script 变量")
            entity_cards = store.list_entity_cards(target_card.project_id)
            existing_cards = store.list_prompt_cards(target_card.project_id, target_card.segment_id)
            context_cards = [
                prompt_card_with_inferred_source(card, request.script, len(existing_cards))
                for card in existing_cards
            ]
            target_card = prompt_card_with_inferred_source(target_card, request.script, len(existing_cards))
            script_excerpt = target_card.source_text or request.script
            rendered_prompt = prompt_engine.render_prompt(
                template,
                template_context(
                    template,
                    {
                        "script_excerpt": script_excerpt,
                        "script": request.script,
                        "entity_catalog": entity_catalog_json(entity_cards),
                        "max_duration_seconds": request.max_duration_seconds,
                        "target_card": prompt_card_target_json(target_card),
                        "generated_context": prompt_cards_context_json(context_cards, target_card_id=target_card.id),
                        "project_style_prompt": store.get_project_style_prompt(target_card.project_id),
                    },
                ),
            )
            updated = rerun_prompt_card_from_script(
                target_card=target_card,
                script=request.script,
                entity_cards=entity_cards,
                llm_client=TrackedLLMClient(
                    build_llm_client(config, "prompt_rerun"), production_repository,
                    "prompt_rerun", target_card.project_id,
                    episode_id=target_card.segment_id, prompt_card_id=target_card.id,
                    template_id=template.id,
                    template_version=template.version,
                ),
                rendered_prompt=rendered_prompt,
                max_duration_seconds=request.max_duration_seconds,
                temperature=float(use_config.get("temperature") or 0.6),
                max_tokens=int(use_config.get("maxTokens") or 100000),
            )
            return _dump(store.save_prompt_card_with_version(updated, "rerun"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (PromptTemplateError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompt-cards/{prompt_card_id}/match-subjects")
    def match_prompt_card_subjects_route(prompt_card_id: str, http_request: Request) -> dict:
        try:
            card = store.get_prompt_card(prompt_card_id)
            if card.locked:
                raise ValueError("提示词卡片已锁定，请先解锁后再匹配主体")
            config = _load_api_config(store, user_id=http_request.state.user.id)
            use_config = llm_use_case_config(config, "subject_match")
            template = template_for_category(prompt_engine, "subject_match")
            rendered_prompt = prompt_engine.render_prompt(
                template,
                template_context(
                    template,
                    {
                        "prompt_card": subject_match_prompt_card_json(card),
                        "entity_catalog": subject_match_entity_catalog_json(store, card.project_id),
                        "project_style_prompt": store.get_project_style_prompt(card.project_id),
                    },
                ),
            )
            raw = TrackedLLMClient(
                build_llm_client(config, "subject_match"), production_repository,
                "subject_match", card.project_id, episode_id=card.segment_id,
                prompt_card_id=card.id, template_id=template.id,
                template_version=template.version,
            ).complete(
                rendered_prompt,
                temperature=float(use_config.get("temperature") or 0.1),
                max_tokens=int(use_config.get("maxTokens") or 100000),
            )
            available_ids = {entity_card.id for entity_card in store.list_entity_cards(card.project_id)}
            entity_card_ids, reasons_by_id = parse_subject_match_entity_ids(
                parse_json_list_payload(raw), available_ids
            )
            matched_entities = entity_cards_by_ids(store, card.project_id, entity_card_ids)
            card = _save_prompt_card_subjects(card, matched_entities, store, source="llm")
            return {"card": _dump(card), **match_prompt_card_subjects(store, card, matched_entities, reasons_by_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (PromptTemplateError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/prompt-cards/{prompt_card_id}/subjects")
    def update_prompt_card_subjects(prompt_card_id: str, request: SavePromptCardSubjectsRequest) -> dict:
        try:
            card = store.get_prompt_card(prompt_card_id)
            if card.locked:
                raise ValueError("提示词卡片已锁定，请先解锁后再调整主体")
            matched_entities = entity_cards_by_ids(store, card.project_id, request.entity_card_ids)
            card = _save_prompt_card_subjects(card, matched_entities, store, source="manual")
            return {"card": _dump(card), **match_prompt_card_subjects(store, card, matched_entities)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompt-cards/{prompt_card_id}/resolve-mentions")
    def resolve_prompt_card_mentions(prompt_card_id: str, request: ResolveMentionsRequest) -> dict:
        try:
            card = store.get_prompt_card(prompt_card_id)
            resolved = resolve_prompt_mentions(
                store,
                card.project_id,
                request.prompt_text or card.prompt_text,
                existing_anchor_text=request.existing_anchor_text or card.anchor_text,
            )
            if request.apply:
                matched = entity_cards_by_ids(store, card.project_id, list(resolved["entity_card_ids"]))
                card = _save_prompt_card_subjects(card, matched, store, source="manual")
                resolved["card"] = _dump(card)
            else:
                resolved["card"] = _dump(card)
            return resolved
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/prompt-cards/{prompt_card_id}")
    def delete_prompt_card(prompt_card_id: str) -> dict:
        try:
            store.delete_prompt_card(prompt_card_id)
            return {"deleted": True, "prompt_card_id": prompt_card_id}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/prompt-cards/{prompt_card_id}/video-tasks")
    async def generate_prompt_card_video(prompt_card_id: str, request: GeneratePromptCardVideoRequest) -> dict:
        try:
            card = store.get_prompt_card(prompt_card_id)
            project = store.get_project(card.project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _ensure_video_generation_allowed(project, card.prompt_text, request.preview, checkpoint_manager)
        task = build_video_task_from_prompt_card(
            store,
            card,
            request,
            provider=video_engine.provider,
        )
        result = await _run_and_store_video_task(task, request.preview, store, video_engine)
        return _dump(result)


def _format_expected_total_duration(value: object) -> str:
    if value is None or value == "":
        return "未指定（按剧情自然切分）"
    return str(value)


def _save_prompt_card_subjects(
    card: PromptCard,
    matched_entities: list[object],
    store: SQLiteStore,
    *,
    source: str,
) -> PromptCard:
    updated = PromptCard(
        id=card.id,
        project_id=card.project_id,
        segment_id=card.segment_id,
        order=card.order,
        title=card.title,
        prompt_text=card.prompt_text,
        anchor_text=format_subject_anchor_text(matched_entities),
        duration=card.duration,
        source_text=card.source_text,
        source_start=card.source_start,
        source_end=card.source_end,
        source_hash=card.source_hash,
        status="matched" if matched_entities else "generated",
        locked=card.locked,
        created_at=card.created_at,
    )
    saved = store.save_prompt_card(updated)
    store.replace_prompt_card_entity_links(
        card.project_id,
        card.id,
        [str(getattr(entity, "id")) for entity in matched_entities],
        source=source,
        confirmed=source == "manual",
    )
    return saved
