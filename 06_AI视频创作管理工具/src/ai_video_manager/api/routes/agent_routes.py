from __future__ import annotations

import json
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.auth.acl import require_project_access
from ai_video_manager.commands import CommandContext


def _user_id(request: Request) -> str | None:
    user = getattr(request.state, "user", None)
    return str(getattr(user, "id", "") or "") or None


def register_agent_routes(app: FastAPI, services: AppServices) -> None:
    agent = services.workflow_agent

    @app.get("/api/commands/catalog")
    def command_catalog() -> dict[str, Any]:
        return {"commands": services.command_bus.catalog()}

    @app.post("/api/commands/execute")
    def execute_command(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        command_id = str(body.get("command") or "").strip()
        arguments = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
        spec = services.command_bus.registry.get(command_id)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"Unknown command: {command_id}")
        project_id = str(arguments.get("project_id") or "").strip()
        if project_id:
            require_project_access(services.store, request.state.user, project_id, "write" if spec.mutation else "read")
        if spec.confirmation != "none" and not bool(body.get("confirmed")):
            return {
                "ok": False,
                "requires_confirmation": True,
                "command": command_id,
                "confirmation": spec.confirmation,
                "arguments": arguments,
            }
        try:
            result = services.command_bus.execute(
                command_id,
                arguments,
                CommandContext(services, user_id=_user_id(request), source="api"),
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent/threads")
    def create_agent_thread(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        project_id = str(body.get("project_id") or "").strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        try:
            require_project_access(services.store, request.state.user, project_id, "read")
            return {"thread": agent.create_thread(project_id, _user_id(request), str(body.get("title") or "项目助手"))}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/agent/threads")
    def list_agent_threads(project_id: str, request: Request) -> dict[str, Any]:
        try:
            require_project_access(services.store, request.state.user, project_id, "read")
            return {"threads": agent.list_threads(project_id, _user_id(request))}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/agent/threads/{thread_id}")
    def get_agent_thread(thread_id: str, request: Request) -> dict[str, Any]:
        try:
            thread = agent.repository.get_thread(thread_id)
            require_project_access(services.store, request.state.user, thread["project_id"], "read")
            return agent.thread_detail(thread_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/agent/threads/{thread_id}/branches")
    def create_agent_branch(thread_id: str, request: Request, body: dict[str, Any]) -> dict[str, Any]:
        try:
            source = agent.repository.get_thread(thread_id)
            require_project_access(services.store, request.state.user, source["project_id"], "read")
            branch = agent.create_branch(
                thread_id,
                _user_id(request),
                title=str(body.get("title") or ""),
                from_message_id=str(body.get("from_message_id") or "") or None,
            )
            return {"thread": branch, "messages": agent.repository.list_messages(branch["id"])}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/agent/threads/{thread_id}/messages")
    def send_agent_message(thread_id: str, request: Request, body: dict[str, Any]) -> dict[str, Any]:
        try:
            thread = agent.repository.get_thread(thread_id)
            require_project_access(services.store, request.state.user, thread["project_id"], "write")
            return agent.send_message(
                thread_id,
                _user_id(request),
                str(body.get("content") or ""),
                body.get("ui_context") if isinstance(body.get("ui_context"), dict) else {},
                str(body.get("approval_mode") or "manual"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent/runs/{run_id}/approve")
    def approve_agent_run(run_id: str, request: Request) -> dict[str, Any]:
        try:
            run = agent.repository.get_run(run_id)
            thread = agent.repository.get_thread(run["thread_id"])
            require_project_access(services.store, request.state.user, thread["project_id"], "write")
            return agent.approve_run(run_id, _user_id(request))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/agent/runs/{run_id}/cancel")
    def cancel_agent_run(run_id: str, request: Request) -> dict[str, Any]:
        try:
            run = agent.repository.get_run(run_id)
            thread = agent.repository.get_thread(run["thread_id"])
            require_project_access(services.store, request.state.user, thread["project_id"], "write")
            return agent.cancel_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/agent/runs/{run_id}")
    def get_agent_run(run_id: str, request: Request) -> dict[str, Any]:
        try:
            run = agent.repository.get_run(run_id)
            thread = agent.repository.get_thread(run["thread_id"])
            require_project_access(services.store, request.state.user, thread["project_id"], "read")
            return agent.run_detail(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/agent/runs/{run_id}/events")
    def agent_events(run_id: str, request: Request, after_id: int = 0) -> StreamingResponse:
        try:
            run = agent.repository.get_run(run_id)
            thread = agent.repository.get_thread(run["thread_id"])
            require_project_access(services.store, request.state.user, thread["project_id"], "read")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        def stream():
            cursor = after_id
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                events = agent.repository.list_events(run_id, cursor)
                for event in events:
                    cursor = int(event["id"])
                    yield f"id: {cursor}\nevent: {event['event_type']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                run = agent.repository.get_run(run_id)
                if run["status"] in {"completed", "failed", "cancelled"} and not events:
                    break
                time.sleep(0.25)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
