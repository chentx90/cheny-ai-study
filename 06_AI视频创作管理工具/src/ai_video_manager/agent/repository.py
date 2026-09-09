from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class AgentRepository:
    def __init__(self, store) -> None:
        self.store = store

    def create_thread(
        self,
        project_id: str,
        user_id: str | None,
        title: str = "项目助手",
        *,
        summary: str = "",
        parent_thread_id: str | None = None,
        branch_point_message_id: str | None = None,
        branch_depth: int = 0,
    ) -> dict[str, Any]:
        self.store.get_project(project_id)
        now = _now()
        thread = {
            "id": _id("athr"), "project_id": project_id, "user_id": user_id,
            "title": title, "summary": summary, "summary_message_id": None,
            "parent_thread_id": parent_thread_id,
            "branch_point_message_id": branch_point_message_id,
            "branch_depth": int(branch_depth), "context_updated_at": now if summary else None,
            "created_at": now, "updated_at": now, "archived_at": None,
        }
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_threads(
                    id, project_id, user_id, title, summary, parent_thread_id,
                    branch_point_message_id, branch_depth, context_updated_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread["id"], project_id, user_id, title, summary, parent_thread_id,
                    branch_point_message_id, int(branch_depth), thread["context_updated_at"], now, now,
                ),
            )
        return thread

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM agent_threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            raise KeyError(f"Agent thread not found: {thread_id}")
        return dict(row)

    def list_threads(self, project_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_threads WHERE project_id = ? AND archived_at IS NULL"
        params: list[Any] = [project_id]
        if user_id:
            query += " AND (user_id = ? OR user_id IS NULL)"
            params.append(user_id)
        query += " ORDER BY updated_at DESC"
        with self.store.connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def create_branch(
        self,
        source_thread_id: str,
        user_id: str | None,
        *,
        title: str = "",
        from_message_id: str | None = None,
    ) -> dict[str, Any]:
        source = self.get_thread(source_thread_id)
        messages = self.list_messages(source_thread_id)
        if from_message_id:
            branch_index = next(
                (index for index, message in enumerate(messages) if message["id"] == from_message_id),
                None,
            )
            if branch_index is None:
                raise KeyError(f"Agent message not found: {from_message_id}")
            messages = messages[: branch_index + 1]
        branch_point = messages[-1]["id"] if messages else None
        summary_marker = str(source.get("summary_message_id") or "")
        if summary_marker:
            marker_index = next(
                (index for index, message in enumerate(messages) if message["id"] == summary_marker),
                None,
            )
            if marker_index is not None:
                messages = messages[marker_index + 1 :]
        with self.store.connect() as conn:
            branch_number = int(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_threads WHERE parent_thread_id = ?",
                    (source_thread_id,),
                ).fetchone()[0]
            ) + 1
        branch = self.create_thread(
            source["project_id"],
            user_id,
            title.strip() or f"{source['title']} · 分支 {branch_number}",
            summary=str(source.get("summary") or ""),
            parent_thread_id=source_thread_id,
            branch_point_message_id=branch_point,
            branch_depth=int(source.get("branch_depth") or 0) + 1,
        )
        for message in messages:
            self.add_message(
                branch["id"],
                message["role"],
                message["content"],
                {**(message.get("metadata") or {}), "source_message_id": message["id"]},
            )
        return self.get_thread(branch["id"])

    def update_thread_summary(self, thread_id: str, summary: str, summary_message_id: str | None) -> dict[str, Any]:
        now = _now()
        with self.store.connect() as conn:
            conn.execute(
                """
                UPDATE agent_threads
                SET summary = ?, summary_message_id = ?, context_updated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (summary, summary_message_id, now, now, thread_id),
            )
        return self.get_thread(thread_id)

    def add_message(self, thread_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self.get_thread(thread_id)
        now = _now()
        message = {"id": _id("amsg"), "thread_id": thread_id, "role": role, "content": content, "metadata": metadata or {}, "created_at": now}
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO agent_messages(id, thread_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message["id"], thread_id, role, content, json.dumps(message["metadata"], ensure_ascii=False), now),
            )
            conn.execute("UPDATE agent_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
        return message

    def list_messages(self, thread_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT * FROM agent_messages WHERE thread_id = ? ORDER BY created_at, id", (thread_id,)).fetchall()
        return [{**dict(row), "metadata": json.loads(row["metadata_json"] or "{}") } for row in rows]

    def create_run(self, thread_id: str, user_request: str) -> dict[str, Any]:
        now = _now()
        run = {"id": _id("arun"), "thread_id": thread_id, "status": "running", "user_request": user_request, "state": {}, "waiting_for_approval": False, "created_at": now, "updated_at": now}
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO agent_runs(id, thread_id, status, user_request, state_json, waiting_for_approval, created_at, updated_at) VALUES (?, ?, ?, ?, '{}', 0, ?, ?)",
                (run["id"], thread_id, "running", user_request, now, now),
            )
        return run

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Agent run not found: {run_id}")
        return {**dict(row), "state": json.loads(row["state_json"] or "{}"), "waiting_for_approval": bool(row["waiting_for_approval"])}

    def latest_run_for_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE thread_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "state": json.loads(row["state_json"] or "{}"),
            "waiting_for_approval": bool(row["waiting_for_approval"]),
        }

    def update_run(self, run_id: str, *, status: str, state: dict[str, Any], waiting: bool = False) -> dict[str, Any]:
        now = _now()
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE agent_runs SET status = ?, state_json = ?, waiting_for_approval = ?, updated_at = ? WHERE id = ?",
                (status, json.dumps(state, ensure_ascii=False), int(waiting), now, run_id),
            )
        return self.get_run(run_id)

    def add_tool_call(self, run_id: str, command_id: str, arguments: dict[str, Any], confirmation: str) -> dict[str, Any]:
        now = _now()
        call = {"id": _id("atool"), "run_id": run_id, "command_id": command_id, "arguments": arguments, "status": "pending", "confirmation": confirmation, "created_at": now}
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO agent_tool_calls(id, run_id, command_id, arguments_json, status, confirmation, created_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                (call["id"], run_id, command_id, json.dumps(arguments, ensure_ascii=False), confirmation, now),
            )
        return call

    def update_tool_call(self, call_id: str, *, status: str, result: Any = None, error: str = "") -> None:
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE agent_tool_calls SET status = ?, result_json = ?, error_message = ?, completed_at = ? WHERE id = ?",
                (status, json.dumps(result, ensure_ascii=False) if result is not None else None, error, _now(), call_id),
            )

    def cancel_pending_tool_calls(self, run_id: str) -> None:
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE agent_tool_calls SET status = 'cancelled', completed_at = ? WHERE run_id = ? AND status = 'pending'",
                (_now(), run_id),
            )

    def update_message_status_for_run(self, thread_id: str, run_id: str, status: str) -> None:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT id, metadata_json FROM agent_messages WHERE thread_id = ?",
                (thread_id,),
            ).fetchall()
            for row in rows:
                metadata = json.loads(row["metadata_json"] or "{}")
                if str(metadata.get("run_id") or "") != run_id:
                    continue
                metadata["status"] = status
                conn.execute(
                    "UPDATE agent_messages SET metadata_json = ? WHERE id = ?",
                    (json.dumps(metadata, ensure_ascii=False), row["id"]),
                )

    def list_tool_calls(self, run_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT * FROM agent_tool_calls WHERE run_id = ? ORDER BY created_at, id", (run_id,)).fetchall()
        return [{**dict(row), "arguments": json.loads(row["arguments_json"] or "{}"), "result": json.loads(row["result_json"]) if row["result_json"] else None} for row in rows]

    def get_tool_call(self, call_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_tool_calls WHERE id = ?",
                (call_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Agent tool call not found: {call_id}")
        return {
            **dict(row),
            "arguments": json.loads(row["arguments_json"] or "{}"),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
        }

    def add_event(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO agent_events(run_id, event_type, data_json, created_at) VALUES (?, ?, ?, ?)",
                (run_id, event_type, json.dumps(data, ensure_ascii=False), _now()),
            )

    def list_events(self, run_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT * FROM agent_events WHERE run_id = ? AND id > ? ORDER BY id", (run_id, after_id)).fetchall()
        return [{**dict(row), "data": json.loads(row["data_json"] or "{}")} for row in rows]
