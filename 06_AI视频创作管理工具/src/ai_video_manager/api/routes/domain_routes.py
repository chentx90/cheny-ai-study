from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.schemas import (
    ConfirmAssetsRequest,
    SaveProjectDocumentRequest,
    SaveProjectScriptsRequest,
    SaveProjectScriptRequest,
    SaveProjectSegmentsRequest,
    SaveProjectSettingsRequest,
)
from ai_video_manager.api.utils import _dump
from ai_video_manager.project_domain import ProjectDomainService, RevisionConflictError
from ai_video_manager.segment_lock import SegmentLockError, require_no_foreign_locks, require_segment_writable


def register_domain_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store
    checkpoint_manager = services.checkpoint_manager
    domain = ProjectDomainService(store, services.document_processor)

    @app.get("/api/projects/{project_id}/session")
    def get_project_session(project_id: str) -> dict:
        try:
            return {"data": domain.get_workspace_view(project_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/document")
    def get_project_document(project_id: str) -> dict:
        try:
            view = domain.get_workspace_view(project_id)
            return {
                "document_text": view.get("documentText", ""),
                "split_strategy": view.get("splitStrategy", "chapter"),
                "custom_split_pattern": view.get("customSplitPattern", ""),
                "duration_minutes": view.get("durationMinutes", 2),
                "document_file": view.get("documentFile"),
                "active_segment_id": view.get("activeSegmentId", ""),
                "content_type": view.get("contentType", "分集原文"),
                "script_convert_template_id": view.get("scriptConvertTemplateId", ""),
                "revision": view.get("revision", 0),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}/document")
    def save_project_document(project_id: str, request: SaveProjectDocumentRequest) -> dict:
        try:
            data = domain.update_document(
                project_id,
                document_text=request.document_text,
                split_strategy=request.split_strategy,
                custom_split_pattern=request.custom_split_pattern,
                duration_minutes=request.duration_minutes,
                active_segment_id=request.active_segment_id,
                content_type=request.content_type,
                script_convert_template_id=request.script_convert_template_id,
                revision=request.revision,
            )
            return {"data": data}
        except RevisionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/segments")
    def list_project_segments(project_id: str) -> dict:
        try:
            view = domain.get_workspace_view(project_id)
            return {
                "segments": view.get("segments", []),
                "active_segment_id": view.get("activeSegmentId", ""),
                "revision": view.get("revision", 0),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}/segments")
    def replace_project_segments(project_id: str, request: SaveProjectSegmentsRequest, http_request: Request) -> dict:
        try:
            require_no_foreign_locks(store, project_id, http_request.state.user)
            data = domain.replace_segments(
                project_id,
                [segment.model_dump() for segment in request.segments],
                clear_downstream=request.clear_downstream,
                active_segment_id=request.active_segment_id,
                revision=request.revision,
            )
            return {"data": data}
        except RevisionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SegmentLockError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}/segments/{segment_id}/script")
    def save_project_segment_script(
        project_id: str,
        segment_id: str,
        request: SaveProjectScriptRequest,
        http_request: Request,
    ) -> dict:
        try:
            require_segment_writable(store, project_id, segment_id, http_request.state.user)
            data = domain.save_segment_script(
                project_id,
                segment_id,
                content=request.content,
                validation=request.validation,
                revision=request.revision,
            )
            return {"data": data}
        except RevisionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SegmentLockError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}/scripts")
    def replace_project_scripts(project_id: str, request: SaveProjectScriptsRequest, http_request: Request) -> dict:
        try:
            for segment_id in request.scripts:
                require_segment_writable(store, project_id, str(segment_id), http_request.state.user)
            data = domain.replace_scripts(
                project_id,
                request.scripts,
                script_validation=request.script_validation,
                revision=request.revision,
            )
            return {"data": data}
        except RevisionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SegmentLockError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}/settings")
    def save_project_settings(project_id: str, request: SaveProjectSettingsRequest) -> dict:
        try:
            data = domain.update_settings(
                project_id,
                expected_total_duration_seconds=request.expected_total_duration_seconds,
                default_aspect_ratio=request.default_aspect_ratio,
                default_video_duration=request.default_video_duration,
                default_video_model=request.default_video_model,
                default_resolution=request.default_resolution,
                project_style_prompt=request.project_style_prompt,
                output_root=request.output_root,
                source_assets_root=request.source_assets_root,
                data_root=request.data_root,
                revision=request.revision,
            )
            return {"data": data}
        except RevisionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/assets/confirm")
    def confirm_project_assets(project_id: str, request: ConfirmAssetsRequest = ConfirmAssetsRequest()) -> dict:
        try:
            data = domain.confirm_assets(project_id, confirmed=request.confirmed)
            return {"data": data}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/assets/refresh-source")
    def refresh_project_source_assets(project_id: str) -> dict:
        try:
            data = domain.refresh_source_assets(project_id)
            return {"data": data}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/workflow/ui")
    def get_project_workflow_ui(project_id: str) -> dict:
        try:
            return domain.workflow_ui(project_id, checkpoint_manager)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/video/providers/{provider}/catalog")
    def get_video_provider_catalog(provider: str) -> dict:
        return domain.video_provider_catalog(provider)
