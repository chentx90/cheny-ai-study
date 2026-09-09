from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ai_video_manager.domain import Episode, EpisodeStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductionRepository:
    def __init__(self, store: Any) -> None:
        self.store = store

    def list_episodes(self, project_id: str) -> list[Episode]:
        self.store.get_project(project_id)
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE project_id = ? ORDER BY order_index, id",
                (project_id,),
            ).fetchall()
        return [self._episode(row) for row in rows]

    def get_episode(self, project_id: str, episode_id: str) -> Episode:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM episodes WHERE project_id = ? AND id = ?",
                (project_id, episode_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Episode not found: {episode_id}")
        return self._episode(row)

    def find_project_id_for_episode(self, episode_id: str) -> str | None:
        with self.store.connect() as conn:
            row = conn.execute("SELECT project_id FROM episodes WHERE id = ?", (episode_id,)).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT project_id FROM project_segments WHERE id = ?", (episode_id,)
                ).fetchone()
        return str(row[0]) if row is not None else None

    def save_episode(self, episode: Episode, *, expected_revision: int | None = None) -> Episode:
        self.store.get_project(episode.project_id)
        with self.store.connect() as conn:
            if expected_revision is not None:
                current = conn.execute(
                    "SELECT revision FROM episodes WHERE project_id = ? AND id = ?",
                    (episode.project_id, episode.id),
                ).fetchone()
                if current is None:
                    raise KeyError(f"Episode not found: {episode.id}")
                if int(current[0]) != expected_revision:
                    raise ValueError(
                        f"Episode revision conflict: expected {expected_revision}, current {current[0]}"
                    )
            conn.execute(
                """
                INSERT INTO episodes
                (id, project_id, document_id, order_index, title, source_text, script_text,
                 metadata, script_validation, source_start, source_end, status, revision,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    order_index=excluded.order_index,
                    title=excluded.title,
                    source_text=excluded.source_text,
                    script_text=excluded.script_text,
                    metadata=excluded.metadata,
                    script_validation=excluded.script_validation,
                    source_start=excluded.source_start,
                    source_end=excluded.source_end,
                    status=excluded.status,
                    revision=excluded.revision,
                    updated_at=excluded.updated_at
                """,
                (
                    episode.id,
                    episode.project_id,
                    episode.document_id,
                    episode.order,
                    episode.title,
                    episode.source_text,
                    episode.script_text,
                    json.dumps(episode.metadata, ensure_ascii=False),
                    json.dumps(episode.script_validation, ensure_ascii=False),
                    episode.source_start,
                    episode.source_end or len(episode.source_text),
                    episode.status.value,
                    episode.revision,
                    episode.created_at.isoformat(),
                    episode.updated_at.isoformat(),
                ),
            )
        return self.get_episode(episode.project_id, episode.id)

    def reorder_episodes(self, project_id: str, episode_ids: list[str]) -> None:
        existing = {item.id for item in self.list_episodes(project_id)}
        if existing != set(episode_ids):
            raise ValueError("episode_ids must include every episode in the project exactly once")
        with self.store.connect() as conn:
            for index, episode_id in enumerate(episode_ids, start=1):
                conn.execute(
                    "UPDATE episodes SET order_index = ? WHERE project_id = ? AND id = ?",
                    (-index, project_id, episode_id),
                )
            for index, episode_id in enumerate(episode_ids, start=1):
                conn.execute(
                    "UPDATE episodes SET order_index = ?, revision = revision + 1, updated_at = ? "
                    "WHERE project_id = ? AND id = ?",
                    (index, _now(), project_id, episode_id),
                )

    def delete_episode(self, project_id: str, episode_id: str) -> None:
        with self.store.connect() as conn:
            refs = conn.execute(
                "SELECT count(*) FROM prompt_cards WHERE project_id = ? AND episode_id = ?",
                (project_id, episode_id),
            ).fetchone()[0]
            if refs:
                raise ValueError(f"Episode is referenced by {refs} prompt cards")
            cursor = conn.execute(
                "DELETE FROM episodes WHERE project_id = ? AND id = ?",
                (project_id, episode_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Episode not found: {episode_id}")

    def start_ai_run(self, **values: Any) -> str:
        run_id = f"airun_{uuid4().hex[:12]}"
        now = _now()
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_runs
                (id, use_case, project_id, episode_id, prompt_card_id, provider_profile_id,
                 model, template_id, template_version, input_snapshot, output_snapshot,
                 status, started_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 'running', ?, ?)
                """,
                (
                    run_id,
                    values["use_case"],
                    values["project_id"],
                    values.get("episode_id"),
                    values.get("prompt_card_id"),
                    values.get("provider_profile_id"),
                    values.get("model", ""),
                    values.get("template_id"),
                    values.get("template_version"),
                    json.dumps(values.get("input_snapshot", {}), ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return run_id

    def succeed_ai_run(self, run_id: str, output_snapshot: dict[str, Any]) -> None:
        self._finish_ai_run(run_id, "succeeded", output_snapshot=output_snapshot)

    def fail_ai_run(self, run_id: str, *, error_code: str, message: str) -> None:
        self._finish_ai_run(run_id, "failed", error_code=error_code, error_message=message)

    def _finish_ai_run(
        self,
        run_id: str,
        status: str,
        *,
        output_snapshot: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        finished = datetime.now(timezone.utc)
        with self.store.connect() as conn:
            row = conn.execute("SELECT started_at FROM ai_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"AI run not found: {run_id}")
            started = datetime.fromisoformat(row[0]) if row[0] else finished
            conn.execute(
                """
                UPDATE ai_runs SET output_snapshot = ?, status = ?, error_code = ?,
                    error_message = ?, finished_at = ?, duration_ms = ? WHERE id = ?
                """,
                (
                    json.dumps(output_snapshot or {}, ensure_ascii=False),
                    status,
                    error_code,
                    error_message,
                    finished.isoformat(),
                    max(0, int((finished - started).total_seconds() * 1000)),
                    run_id,
                ),
            )

    def list_ai_runs(self, project_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, use_case, project_id, episode_id, prompt_card_id,
                       provider_profile_id, model, template_id, template_version,
                       status, error_code, error_message, started_at, finished_at,
                       duration_ms, created_at
                FROM ai_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?
                """,
                (project_id, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_ai_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ai_runs WHERE project_id = ? AND id = ?", (project_id, run_id)
            ).fetchone()
        if row is None:
            raise KeyError(f"AI run not found: {run_id}")
        result = dict(row)
        result["input_snapshot"] = json.loads(result["input_snapshot"] or "{}")
        result["output_snapshot"] = json.loads(result["output_snapshot"] or "{}")
        return result

    @staticmethod
    def _episode(row: sqlite3.Row) -> Episode:
        return Episode(
            id=row["id"],
            project_id=row["project_id"],
            document_id=row["document_id"],
            order=int(row["order_index"]),
            title=row["title"],
            source_text=row["source_text"],
            script_text=row["script_text"],
            metadata=json.loads(row["metadata"] or "{}"),
            script_validation=json.loads(row["script_validation"] or "{}"),
            source_start=int(row["source_start"]),
            source_end=int(row["source_end"]),
            status=EpisodeStatus(row["status"]),
            revision=int(row["revision"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
