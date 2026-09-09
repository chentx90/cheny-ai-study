from __future__ import annotations

import zipfile

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.schemas import (
    CreateProjectRequest,
    ImportProjectBundleRequest,
    ProjectMemberRequest,
    ProjectVisibilityRequest,
    UpdateProjectRequest,
)
from ai_video_manager.api.utils import _dump
from ai_video_manager.auth.acl import resolve_project_role
from ai_video_manager.auth.permissions import resolve_user_capabilities
from ai_video_manager.models import Project, ProjectRole, ProjectVisibility, SystemRole, WorkflowState
from ai_video_manager.project_bundle import (
    PathOutsideWorkspaceError,
    export_project_zip,
    import_project_from_path,
    import_project_zip,
    resolve_project_data_root,
    stored_path_value,
    sync_project_bundle,
)
from ai_video_manager.segment_lock import (
    SegmentLockError,
    acquire_lock,
    list_active_locks,
    release_lock,
)
from ai_video_manager.workflow import WorkflowEngine


def register_project_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store
    checkpoint_manager = services.checkpoint_manager

    def dump_project_for_user(project: Project, user) -> dict:
        data = _dump(project)
        role = resolve_project_role(store, user, project.id)
        data["my_role"] = role.value if role else None
        data["visibility"] = (
            project.visibility.value
            if hasattr(project.visibility, "value")
            else str(project.visibility or "private")
        )
        data["owner_id"] = project.owner_id
        return data

    @app.post("/api/projects")
    def create_project(request_body: CreateProjectRequest, request: Request) -> dict:
        user = request.state.user
        capabilities = resolve_user_capabilities(user, store.get_auth_defaults())
        if not capabilities.get("can_create_project", True):
            raise HTTPException(status_code=403, detail="当前账号不允许创建项目")
        project = Project(
            name=request_body.name,
            category=request_body.category,
            owner_id=user.id,
            description=(request_body.description or "").strip(),
        )
        project = store.save_project(project)
        store.upsert_project_member(project.id, user.id, ProjectRole.OWNER)
        return dump_project_for_user(project, user)

    @app.get("/api/projects")
    def list_projects(request: Request, include_deleted: bool = False) -> dict:
        user = request.state.user
        is_admin = user.role == SystemRole.ADMIN
        projects = store.list_projects(include_deleted=include_deleted, user_id=user.id, is_admin=is_admin)
        return {"projects": [dump_project_for_user(project, user) for project in projects]}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str, request: Request) -> dict:
        try:
            project = store.get_project(project_id)
            return dump_project_for_user(project, request.state.user)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}")
    def update_project(project_id: str, request_body: UpdateProjectRequest, request: Request) -> dict:
        try:
            project = store.update_project(
                project_id,
                name=request_body.name,
                category=request_body.category,
                description=request_body.description,
            )
            return dump_project_for_user(project, request.state.user)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str, request: Request) -> dict:
        try:
            project = store.delete_project(project_id)
            return dump_project_for_user(project, request.state.user)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/restore")
    def restore_project(project_id: str, request: Request) -> dict:
        try:
            project = store.restore_project(project_id)
            return dump_project_for_user(project, request.state.user)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/state")
    def get_project_state(project_id: str, request: Request) -> dict:
        try:
            project = store.get_project(project_id)
            engine = WorkflowEngine(project, checkpoint_manager)
            states = {}
            for state in WorkflowState:
                states[state.value] = {
                    "can_jump": engine.can_jump_to(state),
                    "missing": engine.missing_prerequisites(state),
                }
            dumped = dump_project_for_user(project, request.state.user)
            return {"project": dumped, "states": states}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/members")
    def list_project_members(project_id: str, request: Request) -> dict:
        return {"members": store.list_project_members(project_id)}

    @app.get("/api/projects/{project_id}/members/candidates")
    def list_project_member_candidates(project_id: str, request: Request) -> dict:
        try:
            project = store.get_project(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        users = []
        for user in store.list_users():
            if not user.is_active or user.id == project.owner_id:
                continue
            users.append(
                {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "system_role": user.role.value,
                }
            )
        return {"users": users}

    @app.put("/api/projects/{project_id}/members")
    def upsert_project_member(project_id: str, request_body: ProjectMemberRequest, request: Request) -> dict:
        try:
            role = ProjectRole(request_body.role)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="无效的项目角色") from exc
        user_id = (request_body.user_id or "").strip()
        if not user_id and request_body.username:
            found = store.get_user_by_username(request_body.username.strip())
            if found is None:
                raise HTTPException(status_code=404, detail="用户不存在")
            user_id = found.id
        if not user_id:
            raise HTTPException(status_code=400, detail="请提供 user_id 或 username")
        try:
            store.get_user(user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="用户不存在") from exc
        member = store.upsert_project_member(project_id, user_id, role)
        user = store.get_user(user_id)
        return {
            "member": {
                "project_id": member.project_id,
                "user_id": member.user_id,
                "role": member.role.value,
                "created_at": member.created_at.isoformat(),
                "username": user.username,
                "display_name": user.display_name,
            }
        }

    @app.delete("/api/projects/{project_id}/members/{user_id}")
    def remove_project_member(project_id: str, user_id: str, request: Request) -> dict:
        project = store.get_project(project_id)
        if project.owner_id == user_id:
            raise HTTPException(status_code=400, detail="不能移除项目所有者，请先转移所有权")
        store.remove_project_member(project_id, user_id)
        return {"ok": True}

    @app.patch("/api/projects/{project_id}/visibility")
    def update_project_visibility(project_id: str, request_body: ProjectVisibilityRequest, request: Request) -> dict:
        user = request.state.user
        try:
            visibility = ProjectVisibility(request_body.visibility)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="无效的可见性") from exc
        if visibility == ProjectVisibility.PUBLIC:
            capabilities = resolve_user_capabilities(user, store.get_auth_defaults())
            if not capabilities.get("can_make_public", False):
                raise HTTPException(status_code=403, detail="当前账号不允许将项目设为公共")
        project = store.set_project_visibility(project_id, visibility)
        return dump_project_for_user(project, user)

    @app.get("/api/projects/{project_id}/segment-locks")
    def list_segment_locks(project_id: str, request: Request) -> dict:
        return {"locks": list_active_locks(store, project_id)}

    @app.post("/api/projects/{project_id}/segments/{segment_id}/lock")
    def acquire_segment_lock(project_id: str, segment_id: str, request: Request) -> dict:
        try:
            lock = acquire_lock(store, project_id, segment_id, request.state.user)
            return {"lock": lock}
        except SegmentLockError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}/segments/{segment_id}/lock")
    def release_segment_lock(project_id: str, segment_id: str, request: Request, force: bool = False) -> dict:
        try:
            released = release_lock(store, project_id, segment_id, request.state.user, force=force)
            return {"released": released}
        except SegmentLockError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/data-root")
    def get_project_data_root(project_id: str, request: Request) -> dict:
        try:
            root = resolve_project_data_root(store, project_id)
            preprocess = store.get_preprocess(project_id) or {}
            return {
                "configured": str(preprocess.get("data_root") or "").strip(),
                "resolved": str(root),
                "relative": stored_path_value(store, root),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/sync-bundle")
    def sync_project_bundle_files(project_id: str, request: Request) -> dict:
        try:
            root = sync_project_bundle(store, project_id)
            return {"ok": True, "data_root": str(root)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/export")
    def export_project(project_id: str, request: Request) -> Response:
        try:
            payload, filename = export_project_zip(store, project_id)
            headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
            return Response(content=payload, media_type="application/zip", headers=headers)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"导出失败：{exc}") from exc

    @app.post("/api/projects/import")
    async def import_project_zip_route(
        request: Request,
        file: UploadFile = File(...),
        name: str | None = None,
    ) -> dict:
        user = request.state.user
        capabilities = resolve_user_capabilities(user, store.get_auth_defaults())
        if not capabilities.get("can_create_project", True):
            raise HTTPException(status_code=403, detail="当前账号不允许创建项目")
        payload = await file.read()
        if not payload:
            raise HTTPException(status_code=400, detail="上传文件为空")
        try:
            project = import_project_zip(store, payload, owner_id=user.id, name_override=name)
            return {"project": dump_project_for_user(project, user)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="无效的 ZIP 文件") from exc

    @app.post("/api/projects/import-folder")
    def import_project_folder_route(request_body: ImportProjectBundleRequest, request: Request) -> dict:
        user = request.state.user
        capabilities = resolve_user_capabilities(user, store.get_auth_defaults())
        if not capabilities.get("can_create_project", True):
            raise HTTPException(status_code=403, detail="当前账号不允许创建项目")
        path = (request_body.path or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="请填写项目文件夹路径")
        try:
            project = import_project_from_path(
                store,
                path,
                owner_id=user.id,
                name_override=request_body.name,
            )
            return {"project": dump_project_for_user(project, user)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
