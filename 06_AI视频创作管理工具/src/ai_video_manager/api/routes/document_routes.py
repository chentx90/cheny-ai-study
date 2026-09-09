from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from ai_video_manager.api.app_helpers import normalize_script_format_decision
from ai_video_manager.api.app_services import AppServices
from ai_video_manager.auth.acl import require_project_access
from ai_video_manager.api.config import _load_api_config
from ai_video_manager.api.schemas import (
    ConvertSegmentRequest,
    IngestDocumentRequest,
    SplitDocumentRequest,
    UploadDocumentRequest,
    ValidateScriptRequest,
)
from ai_video_manager.api.utils import _dump, _strategy
from ai_video_manager.application.ai_runs import TrackedLLMClient
from ai_video_manager.llm import build_llm_client, llm_use_case_config
from ai_video_manager.models import Project, Script, WorkflowState
from ai_video_manager.project_domain import ProjectDomainService
from ai_video_manager.prompt_engine import PromptTemplateError, request_template_for_category


def register_document_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store
    document_processor = services.document_processor
    prompt_engine = services.prompt_engine
    checkpoint_manager = services.checkpoint_manager
    duration_split_client = services.duration_split_client

    @app.post("/api/documents/ingest")
    def ingest_document(request_body: IngestDocumentRequest, request: Request) -> dict:
        require_project_access(store, request.state.user, request_body.project_id, "write")
        path = Path(request_body.path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Document not found: {request_body.path}")
        try:
            project = store.get_project(request_body.project_id)
            document = document_processor.load_document(path, project.id)
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project.has_document = True
        store.save_document(document)
        store.save_project(project)
        return _dump(document)

    domain = ProjectDomainService(store, document_processor)

    @app.post("/api/projects/{project_id}/documents/upload")
    def upload_project_document(project_id: str, request: UploadDocumentRequest) -> dict:
        try:
            content = base64.b64decode(request.content_base64, validate=True)
            if len(content) > 20 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Document exceeds 20 MB limit")
            relative_path = store.save_original_file(project_id, request.filename, content)
            project_root = store.ensure_project_layout(project_id)
            document = document_processor.load_document(project_root / relative_path, project_id)
            store.save_document(document)
            workspace = domain.reset_on_document_upload(
                project_id,
                document_text=document.content,
                document_file={
                    "path": relative_path,
                    "filename": document.filename,
                    "format": document.format.value,
                },
            )
            return {"document": _dump(document), "path": relative_path, "workspace": workspace}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/documents/split")
    def split_document(request: SplitDocumentRequest, http_request: Request) -> dict:
        try:
            llm_client = (
                duration_split_client(http_request.state.user.id, request.project_id)
                if request.strategy in {"duration", "duration_2min"}
                else None
            )
            strategy = _strategy(
                request.strategy,
                request.max_chars,
                llm_client=llm_client,
                custom_pattern=request.custom_pattern,
                duration_minutes=request.duration_minutes,
            )
            project_id = request.project_id
            if request.persist:
                if not project_id:
                    raise ValueError("persist=true 时必须提供 project_id")
                require_project_access(store, http_request.state.user, project_id, "write")
                project = store.get_project(project_id)
            else:
                project = Project(name="inline", id=project_id or "inline")
            document = document_processor.load_document_from_text(
                request.content,
                project_id=project.id,
            )
            segments = document_processor.split_document(document, strategy)
            orphaned_count = 0
            workspace: dict[str, object] = {}
            if request.persist and project_id:
                result = domain.apply_split_persist(
                    project_id,
                    segments,
                    split_strategy=request.strategy,
                    mark_orphaned_tasks=request.mark_orphaned_tasks,
                )
                workspace = result["workspace"]
                orphaned_count = int(result["orphaned_task_count"])
                store.replace_project_document_segments(
                    project_id=project_id,
                    document=document,
                    segments=segments,
                )
                checkpoint_manager.save_checkpoint(store.get_project(project_id), WorkflowState.DOCUMENT_SPLIT)
            return {
                "document": _dump(document),
                "segments": [_dump(segment) for segment in segments],
                "persisted": bool(request.persist and project_id),
                "orphaned_task_count": orphaned_count,
                "workspace": workspace,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/documents/split/suggest")
    def suggest_document_split(request: SplitDocumentRequest, http_request: Request) -> dict:
        try:
            llm_client = (
                duration_split_client(http_request.state.user.id, request.project_id)
                if request.strategy in {"duration", "duration_2min"}
                else None
            )
            return {
                "suggestions": document_processor.suggest_split_points(
                    request.content,
                    llm_client=llm_client,
                    strategy_names=[request.strategy],
                    max_chars=request.max_chars,
                    custom_pattern=request.custom_pattern,
                    duration_minutes=request.duration_minutes,
                )
            }
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/segments/convert")
    def convert_segment(request: ConvertSegmentRequest, http_request: Request) -> dict:
        try:
            source_decision = normalize_script_format_decision(request.source_format)
            if source_decision is None:
                raise ValueError("请先人工选择：直接转存或 LLM 转写成剧本")
            decision_payload = {
                "decision": source_decision,
                "is_script": source_decision == "script",
                "confidence": 1,
                "reason": "人工选择直接转存" if source_decision == "script" else "人工选择 LLM 转写成剧本",
                "source": "manual",
                "sample_chars": min(len(request.content.strip()), 3000),
            }

            if source_decision == "script":
                script_content = request.content.strip()
                source_format = "script"
            else:
                config = _load_api_config(store, user_id=http_request.state.user.id)
                use_config = llm_use_case_config(config, "script_convert")
                template = request_template_for_category(
                    prompt_engine, "script_convert", request.template_id
                )
                project_id = services.production_repository.find_project_id_for_episode(
                    request.segment_id
                )
                prompt = prompt_engine.render_prompt(
                    template,
                    {
                        "content_type": request.content_type.strip() or "分集原文",
                        "content": request.content,
                        "project_style_prompt": store.get_project_style_prompt(project_id) if project_id else "",
                    },
                )
                client = build_llm_client(config, "script_convert")
                if project_id:
                    client = TrackedLLMClient(
                        client,
                        services.production_repository,
                        "script_convert",
                        project_id,
                        episode_id=request.segment_id,
                        template_id=template.id,
                        template_version=template.version,
                    )
                script_content = client.complete(
                    prompt,
                    temperature=float(use_config.get("temperature") or 0.2),
                    max_tokens=int(use_config.get("maxTokens") or 100000),
                )
                source_format = "converted"
        except (KeyError, PromptTemplateError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        script = Script(segment_id=request.segment_id, content=script_content)
        return {
            "script": _dump(script),
            "validation": _dump(document_processor.validate_script(script.content)),
            "source_format": source_format,
            "converted": source_format == "converted",
            "format_decision": decision_payload,
            "template_id": template.id if source_decision != "script" else None,
            "template_version": template.version if source_decision != "script" else None,
        }

    @app.post("/api/scripts/validate")
    def validate_script(request: ValidateScriptRequest) -> dict:
        return {"validation": _dump(document_processor.validate_script(request.content))}
