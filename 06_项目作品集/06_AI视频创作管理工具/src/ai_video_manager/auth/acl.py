from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import HTTPException, Request

from ai_video_manager.models import ProjectRole, ProjectVisibility, SystemRole, User
from ai_video_manager.storage import SQLiteStore

PROJECT_PATH_RE = re.compile(r"^/api/(?:v2/)?projects/([^/]+)(?:/|$)")


@dataclass(frozen=True)
class ProjectAccess:
    project_id: str
    role: ProjectRole


def _role_rank(role: ProjectRole) -> int:
    return {
        ProjectRole.VIEWER: 1,
        ProjectRole.EDITOR: 2,
        ProjectRole.OWNER: 3,
    }[role]


def resolve_project_role(store: SQLiteStore, user: User, project_id: str) -> ProjectRole | None:
    if user.role == SystemRole.ADMIN:
        return ProjectRole.OWNER
    member = store.get_project_member(project_id, user.id)
    if member is not None:
        return member.role
    try:
        meta = store.get_project_auth_meta(project_id)
    except KeyError:
        return None
    if meta["visibility"] == ProjectVisibility.PUBLIC.value:
        defaults = store.get_auth_defaults()
        public_role = str(defaults.get("public_default_role") or ProjectRole.EDITOR.value)
        try:
            return ProjectRole(public_role)
        except ValueError:
            return ProjectRole.EDITOR
    return None


def role_allows(role: ProjectRole | None, level: str) -> bool:
    if role is None:
        return False
    if level == "read":
        return True
    if level == "write":
        return role in {ProjectRole.OWNER, ProjectRole.EDITOR}
    if level == "delete":
        return role == ProjectRole.OWNER
    if level == "manage_members":
        return role == ProjectRole.OWNER
    return False


def require_project_access(
    store: SQLiteStore,
    user: User,
    project_id: str,
    level: str,
) -> ProjectAccess:
    role = resolve_project_role(store, user, project_id)
    if not role_allows(role, level):
        if role is None:
            raise HTTPException(status_code=404, detail="Project not found")
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return ProjectAccess(project_id=project_id, role=role)


def required_level_for_request(method: str, path: str, project_id: str) -> str | None:
    prefix = f"/api/v2/projects/{project_id}" if path.startswith("/api/v2/") else f"/api/projects/{project_id}"
    suffix = path[len(prefix) :] or ""
    if suffix == "" or suffix == "/":
        if method == "GET":
            return "read"
        if method == "PUT":
            return "write"
        if method == "DELETE":
            return "delete"
        if method == "POST":
            return "write"
        return "write"
    if suffix.startswith("/members"):
        return "manage_members"
    if suffix.startswith("/visibility"):
        return "manage_members"
    if suffix.endswith("/lock"):
        if method == "DELETE":
            return "write"
        if method == "POST":
            return "write"
    if suffix.endswith("/restore") and method == "POST":
        return "delete"
    if method == "GET":
        return "read"
    return "write"


def enforce_project_acl_middleware(store: SQLiteStore, request: Request) -> None:
    user: User | None = getattr(request.state, "user", None)
    if user is None:
        return
    match = PROJECT_PATH_RE.match(request.url.path)
    if not match:
        return
    project_id = match.group(1)
    if project_id in {"restore", "import", "import-folder"}:
        return
    level = required_level_for_request(request.method, request.url.path, project_id)
    if level is None:
        return
    access = require_project_access(store, user, project_id, level)
    request.state.project_access = access


def get_request_project_role(request: Request) -> ProjectRole | None:
    access: ProjectAccess | None = getattr(request.state, "project_access", None)
    return access.role if access else None
