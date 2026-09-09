from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ai_video_manager.models import new_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


class AssetProductionRepository:
    """Persistence boundary for entity analysis and native image production."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def start_extraction_run(self, project_id: str, episode_revisions: dict[str, int]) -> dict[str, Any]:
        self.store.get_project(project_id)
        run_id = new_id("erun")
        now = _now()
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO entity_extraction_runs "
                "(id, project_id, episode_revisions, status, created_at) VALUES (?, ?, ?, 'running', ?)",
                (run_id, project_id, _json(episode_revisions), now),
            )
        return self.get_extraction_run(project_id, run_id)

    def finish_extraction_run(self, project_id: str, run_id: str, *, error: str | None = None) -> dict[str, Any]:
        with self.store.connect() as conn:
            cursor = conn.execute(
                "UPDATE entity_extraction_runs SET status = ?, error_message = ?, finished_at = ? "
                "WHERE project_id = ? AND id = ?",
                ("failed" if error else "succeeded", error, _now(), project_id, run_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Entity extraction run not found: {run_id}")
        return self.get_extraction_run(project_id, run_id)

    def get_extraction_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM entity_extraction_runs WHERE project_id = ? AND id = ?",
                (project_id, run_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Entity extraction run not found: {run_id}")
        return self._run(row)

    def list_extraction_runs(self, project_id: str) -> list[dict[str, Any]]:
        self.store.get_project(project_id)
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entity_extraction_runs WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._run(row) for row in rows]

    def recover_interrupted_runs(self) -> int:
        with self.store.connect() as conn:
            cursor = conn.execute(
                "UPDATE entity_extraction_runs SET status = 'failed', error_message = ?, finished_at = ? "
                "WHERE status = 'running'",
                ("服务重启时任务仍未完成", _now()),
            )
        return int(cursor.rowcount)

    def upsert_profile(self, project_id: str, values: dict[str, Any]) -> dict[str, Any]:
        self.store.get_project(project_id)
        name = str(values.get("canonical_name") or "").strip()
        entity_type = str(values.get("type") or "").strip()
        if not name or entity_type not in {"character", "scene", "prop"}:
            raise ValueError("Entity profile requires canonical_name and character|scene|prop type")
        now = _now()
        with self.store.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM entity_profiles WHERE project_id = ? AND canonical_name = ? AND type = ?",
                (project_id, name, entity_type),
            ).fetchone()
            if existing is None:
                incoming_aliases = {str(item).strip() for item in values.get("aliases") or [] if str(item).strip()}
                for candidate in conn.execute(
                    "SELECT * FROM entity_profiles WHERE project_id = ? AND type = ?",
                    (project_id, entity_type),
                ).fetchall():
                    candidate_aliases = set(json.loads(candidate["aliases"] or "[]"))
                    if name in candidate_aliases or str(candidate["canonical_name"]) in incoming_aliases:
                        existing = candidate
                        break
            if existing is None:
                profile_id = str(values.get("id") or new_id("eprof"))
                conn.execute(
                    """
                    INSERT INTO entity_profiles
                    (id, project_id, canonical_name, type, aliases, role, importance,
                     mention_count, scene_count, episode_ids, first_episode, last_episode,
                     setting, status, manual_fields, linked_entity_card_id, revision,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        profile_id, project_id, name, entity_type,
                        _json(values.get("aliases") or []), str(values.get("role") or ""),
                        str(values.get("importance") or "C"), int(values.get("mention_count") or 0),
                        int(values.get("scene_count") or 0), _json(values.get("episode_ids") or []),
                        values.get("first_episode"), values.get("last_episode"),
                        str(values.get("setting") or ""), str(values.get("status") or "draft"),
                        _json(values.get("manual_fields") or []), values.get("linked_entity_card_id"),
                        now, now,
                    ),
                )
            else:
                profile_id = str(existing["id"])
                manual_fields = set(json.loads(existing["manual_fields"] or "[]"))
                preserved = {field: existing[field] for field in manual_fields if field in existing.keys()}
                merged = {**values, **preserved}
                conn.execute(
                    """
                    UPDATE entity_profiles SET aliases = ?, role = ?, importance = ?,
                        mention_count = ?, scene_count = ?, episode_ids = ?, first_episode = ?,
                        last_episode = ?, setting = ?, status = ?, linked_entity_card_id = ?,
                        revision = revision + 1, updated_at = ?
                    WHERE project_id = ? AND id = ?
                    """,
                    (
                        _json(merged.get("aliases") or []), str(merged.get("role") or ""),
                        str(merged.get("importance") or "C"), int(values.get("mention_count") or 0),
                        int(values.get("scene_count") or 0), _json(values.get("episode_ids") or []),
                        values.get("first_episode"), values.get("last_episode"),
                        str(merged.get("setting") or ""), str(merged.get("status") or existing["status"]),
                        merged.get("linked_entity_card_id") or existing["linked_entity_card_id"],
                        now, project_id, profile_id,
                    ),
                )
        return self.get_profile(project_id, profile_id)

    def update_profile(self, project_id: str, profile_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_profile(project_id, profile_id)
        allowed = {"canonical_name", "type", "aliases", "role", "importance", "setting", "status"}
        updates = {key: value for key, value in patch.items() if key in allowed}
        if "canonical_name" in updates and updates["canonical_name"] != current["canonical_name"] and "aliases" not in updates:
            updates["aliases"] = list(dict.fromkeys([*current["aliases"], current["canonical_name"]]))
        if not updates:
            return current
        manual_fields = set(current["manual_fields"])
        manual_fields.update(updates)
        values: list[Any] = []
        assignments: list[str] = []
        for key, value in updates.items():
            assignments.append(f"{key} = ?")
            values.append(_json(value) if key == "aliases" else value)
        assignments.extend(["manual_fields = ?", "revision = revision + 1", "updated_at = ?"])
        values.extend([_json(sorted(manual_fields)), _now(), project_id, profile_id])
        with self.store.connect() as conn:
            try:
                cursor = conn.execute(
                    f"UPDATE entity_profiles SET {', '.join(assignments)} WHERE project_id = ? AND id = ?",
                    values,
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise ValueError("同项目中已存在同名同类型实体") from exc
            if cursor.rowcount == 0:
                raise KeyError(f"Entity profile not found: {profile_id}")
        return self.get_profile(project_id, profile_id)

    def get_profile(self, project_id: str, profile_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM entity_profiles WHERE project_id = ? AND id = ?", (project_id, profile_id)
            ).fetchone()
        if row is None:
            raise KeyError(f"Entity profile not found: {profile_id}")
        profile = self._profile(row)
        profile["mentions"] = self.list_mentions(project_id, profile_id)
        profile["variants"] = self.list_variants(project_id, profile_id)
        return profile

    def list_profiles(self, project_id: str) -> list[dict[str, Any]]:
        self.store.get_project(project_id)
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entity_profiles WHERE project_id = ? "
                "ORDER BY CASE importance WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END, type, canonical_name",
                (project_id,),
            ).fetchall()
        return [self.get_profile(project_id, str(row["id"])) for row in rows]

    def delete_profile(self, project_id: str, profile_id: str) -> None:
        self.get_profile(project_id, profile_id)
        with self.store.connect() as conn:
            conn.execute("DELETE FROM entity_mentions WHERE project_id = ? AND profile_id = ?", (project_id, profile_id))
            conn.execute("DELETE FROM entity_variants WHERE project_id = ? AND profile_id = ?", (project_id, profile_id))
            conn.execute("DELETE FROM entity_asset_prompts WHERE project_id = ? AND profile_id = ?", (project_id, profile_id))
            conn.execute("DELETE FROM entity_profiles WHERE project_id = ? AND id = ?", (project_id, profile_id))
        self.store.refresh_entity_workflow_flags(project_id)

    def replace_mentions(self, project_id: str, run_id: str, profile_id: str, mentions: list[dict[str, Any]]) -> None:
        now = _now()
        with self.store.connect() as conn:
            conn.execute(
                "DELETE FROM entity_mentions WHERE project_id = ? AND profile_id = ?", (project_id, profile_id)
            )
            for item in mentions:
                conn.execute(
                    """
                    INSERT INTO entity_mentions
                    (id, run_id, project_id, profile_id, episode_id, episode_order, alias,
                     evidence, mention_count, scene_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("emention"), run_id, project_id, profile_id, item["episode_id"],
                        int(item["episode_order"]), str(item.get("alias") or ""),
                        str(item.get("evidence") or ""), int(item.get("mention_count") or 0),
                        int(item.get("scene_count") or 1), now,
                    ),
                )

    def list_mentions(self, project_id: str, profile_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entity_mentions WHERE project_id = ? AND profile_id = ? ORDER BY episode_order, created_at",
                (project_id, profile_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_variants(self, project_id: str, profile_id: str, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = _now()
        with self.store.connect() as conn:
            for index, item in enumerate(variants):
                name = str(item.get("name") or item.get("state") or "默认").strip() or "默认"
                conn.execute(
                    """
                    INSERT INTO entity_variants
                    (id, project_id, profile_id, name, setting, episode_ids, is_default, revision, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    ON CONFLICT(profile_id, name) DO UPDATE SET setting = excluded.setting,
                        episode_ids = excluded.episode_ids, is_default = excluded.is_default,
                        revision = entity_variants.revision + 1, updated_at = excluded.updated_at
                    """,
                    (
                        new_id("evar"), project_id, profile_id, name, str(item.get("setting") or ""),
                        _json(item.get("episode_ids") or []), int(bool(item.get("is_default", index == 0))), now, now,
                    ),
                )
        return self.list_variants(project_id, profile_id)

    def list_variants(self, project_id: str, profile_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entity_variants WHERE project_id = ? AND profile_id = ? ORDER BY is_default DESC, created_at",
                (project_id, profile_id),
            ).fetchall()
        return [self._variant(row) for row in rows]

    def save_visual_style(self, project_id: str, values: dict[str, Any], style_id: str | None = None) -> dict[str, Any]:
        self.store.get_project(project_id)
        now = _now()
        with self.store.connect() as conn:
            if values.get("is_active"):
                conn.execute("UPDATE project_visual_styles SET is_active = 0 WHERE project_id = ?", (project_id,))
            if style_id:
                current = conn.execute(
                    "SELECT * FROM project_visual_styles WHERE project_id = ? AND id = ?",
                    (project_id, style_id),
                ).fetchone()
                if current is None:
                    raise KeyError(f"Visual style not found: {style_id}")
                new_style_id = new_id("vstyle")
                conn.execute(
                    """
                    INSERT INTO project_visual_styles
                    (id, project_id, name, prompt, negative_prompt, reference_asset_ids,
                     is_active, version, revision, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        new_style_id, project_id, values["name"], values.get("prompt", ""), values.get("negative_prompt", ""),
                        _json(values.get("reference_asset_ids") or []), int(bool(values.get("is_active"))),
                        int(current["version"]) + 1, now, now,
                    ),
                )
                style_id = new_style_id
            else:
                style_id = new_id("vstyle")
                conn.execute(
                    """
                    INSERT INTO project_visual_styles
                    (id, project_id, name, prompt, negative_prompt, reference_asset_ids,
                     is_active, version, revision, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
                    """,
                    (
                        style_id, project_id, values["name"], values.get("prompt", ""),
                        values.get("negative_prompt", ""), _json(values.get("reference_asset_ids") or []),
                        int(bool(values.get("is_active"))), now, now,
                    ),
                )
        return self.get_visual_style(project_id, style_id)

    def get_visual_style(self, project_id: str, style_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_visual_styles WHERE project_id = ? AND id = ?", (project_id, style_id)
            ).fetchone()
        if row is None:
            raise KeyError(f"Visual style not found: {style_id}")
        return self._style(row)

    def list_visual_styles(self, project_id: str) -> list[dict[str, Any]]:
        self.store.get_project(project_id)
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM project_visual_styles WHERE project_id = ? ORDER BY is_active DESC, updated_at DESC",
                (project_id,),
            ).fetchall()
        return [self._style(row) for row in rows]

    def delete_visual_style(self, project_id: str, style_id: str) -> None:
        with self.store.connect() as conn:
            refs = conn.execute(
                "SELECT count(*) FROM entity_asset_prompts WHERE project_id = ? AND style_id = ?",
                (project_id, style_id),
            ).fetchone()[0]
            if refs:
                raise ValueError(f"视觉风格已被 {refs} 条资产提示词引用，不能删除")
            cursor = conn.execute(
                "DELETE FROM project_visual_styles WHERE project_id = ? AND id = ?", (project_id, style_id)
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Visual style not found: {style_id}")

    def save_preset(self, project_id: str, entity_type: str, values: dict[str, Any]) -> dict[str, Any]:
        if entity_type not in {"character", "scene", "prop"}:
            raise ValueError("Unknown entity type")
        self.store.get_project(project_id)
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO asset_generation_presets
                (project_id, entity_type, provider, model, size, aspect_ratio, output_count,
                 view_types, type_prompt, type_negative_prompt, auto_adopt, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, entity_type) DO UPDATE SET provider = excluded.provider,
                    model = excluded.model, size = excluded.size, aspect_ratio = excluded.aspect_ratio,
                    output_count = excluded.output_count, view_types = excluded.view_types,
                    type_prompt = excluded.type_prompt, type_negative_prompt = excluded.type_negative_prompt,
                    auto_adopt = excluded.auto_adopt, updated_at = excluded.updated_at
                """,
                (
                    project_id, entity_type, str(values.get("provider") or "openai"),
                    str(values.get("model") or ""), str(values.get("size") or "1024x1024"),
                    str(values.get("aspect_ratio") or "1:1"), max(1, min(int(values.get("output_count") or 1), 8)),
                    _json(values.get("view_types") or []), str(values.get("type_prompt") or ""),
                    str(values.get("type_negative_prompt") or ""), int(bool(values.get("auto_adopt"))), _now(),
                ),
            )
        return self.get_preset(project_id, entity_type)

    def get_preset(self, project_id: str, entity_type: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM asset_generation_presets WHERE project_id = ? AND entity_type = ?",
                (project_id, entity_type),
            ).fetchone()
        if row is None:
            defaults = {
                "character": {"size": "1024x1536", "aspect_ratio": "2:3", "view_types": ["全身"]},
                "scene": {"size": "1536x1024", "aspect_ratio": "3:2", "view_types": ["全景"]},
                "prop": {"size": "1024x1024", "aspect_ratio": "1:1", "view_types": ["单体"]},
            }[entity_type]
            return self.save_preset(project_id, entity_type, defaults)
        result = dict(row)
        result["view_types"] = json.loads(result["view_types"] or "[]")
        result["auto_adopt"] = bool(result["auto_adopt"])
        return result

    def list_presets(self, project_id: str) -> list[dict[str, Any]]:
        return [self.get_preset(project_id, entity_type) for entity_type in ("character", "scene", "prop")]

    def save_asset_prompt(self, project_id: str, values: dict[str, Any]) -> dict[str, Any]:
        prompt_id = str(values.get("id") or new_id("aprompt"))
        now = _now()
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO entity_asset_prompts
                (id, project_id, profile_id, variant_id, style_id, style_version, view_type,
                 prompt_text, negative_prompt, template_id, template_version, revision, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(id) DO UPDATE SET view_type = excluded.view_type,
                    prompt_text = excluded.prompt_text, negative_prompt = excluded.negative_prompt,
                    revision = entity_asset_prompts.revision + 1, updated_at = excluded.updated_at
                """,
                (
                    prompt_id, project_id, values["profile_id"], values.get("variant_id"),
                    values.get("style_id"), values.get("style_version"), str(values.get("view_type") or ""),
                    str(values.get("prompt_text") or ""), str(values.get("negative_prompt") or ""),
                    values.get("template_id"), values.get("template_version"), now, now,
                ),
            )
        return self.get_asset_prompt(project_id, prompt_id)

    def get_asset_prompt(self, project_id: str, prompt_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM entity_asset_prompts WHERE project_id = ? AND id = ?", (project_id, prompt_id)
            ).fetchone()
        if row is None:
            raise KeyError(f"Asset prompt not found: {prompt_id}")
        return dict(row)

    def list_asset_prompts(self, project_id: str, profile_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM entity_asset_prompts WHERE project_id = ?"
        params: list[Any] = [project_id]
        if profile_id:
            query += " AND profile_id = ?"
            params.append(profile_id)
        query += " ORDER BY updated_at DESC"
        with self.store.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def create_image_task(self, project_id: str, values: dict[str, Any]) -> dict[str, Any]:
        task_id = new_id("itask")
        now = _now()
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO image_generation_tasks
                (id, project_id, profile_id, asset_prompt_id, status, request_snapshot, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (task_id, project_id, values.get("profile_id"), values.get("asset_prompt_id"), _json(values), now, now),
            )
        return self.get_image_task(project_id, task_id)

    def update_image_task(self, project_id: str, task_id: str, status: str, error: str | None = None) -> dict[str, Any]:
        with self.store.connect() as conn:
            cursor = conn.execute(
                "UPDATE image_generation_tasks SET status = ?, error_message = ?, updated_at = ? "
                "WHERE project_id = ? AND id = ?",
                (status, error, _now(), project_id, task_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Image task not found: {task_id}")
        return self.get_image_task(project_id, task_id)

    def get_image_task(self, project_id: str, task_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM image_generation_tasks WHERE project_id = ? AND id = ?", (project_id, task_id)
            ).fetchone()
        if row is None:
            raise KeyError(f"Image task not found: {task_id}")
        result = dict(row)
        result["request_snapshot"] = json.loads(result["request_snapshot"] or "{}")
        result["outputs"] = self.list_image_outputs(project_id, task_id)
        return result

    def list_image_tasks(self, project_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM image_generation_tasks WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        return [self.get_image_task(project_id, str(row["id"])) for row in rows]

    def add_image_output(self, project_id: str, task_id: str, asset: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        output_id = new_id("iout")
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO image_outputs
                (id, project_id, image_task_id, project_asset_id, storage_path, adopted, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (output_id, project_id, task_id, asset["id"], asset["path"], _json(metadata), _now()),
            )
            row = conn.execute(
                "SELECT id FROM image_outputs WHERE project_id = ? AND image_task_id = ? AND project_asset_id = ?",
                (project_id, task_id, asset["id"]),
            ).fetchone()
        return self.get_image_output(project_id, str(row["id"]))

    def get_image_output(self, project_id: str, output_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM image_outputs WHERE project_id = ? AND id = ?", (project_id, output_id)
            ).fetchone()
        if row is None:
            raise KeyError(f"Image output not found: {output_id}")
        return self._output(row)

    def list_image_outputs(self, project_id: str, task_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM image_outputs WHERE project_id = ? AND image_task_id = ? ORDER BY created_at",
                (project_id, task_id),
            ).fetchall()
        return [self._output(row) for row in rows]

    def adopt_image_output(self, project_id: str, output_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            cursor = conn.execute(
                "UPDATE image_outputs SET adopted = 1 WHERE project_id = ? AND id = ?", (project_id, output_id)
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Image output not found: {output_id}")
        return self.get_image_output(project_id, output_id)

    @staticmethod
    def _run(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["episode_revisions"] = json.loads(result["episode_revisions"] or "{}")
        return result

    @staticmethod
    def _profile(row: Any) -> dict[str, Any]:
        result = dict(row)
        for key in ("aliases", "episode_ids", "manual_fields"):
            result[key] = json.loads(result[key] or "[]")
        return result

    @staticmethod
    def _variant(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["episode_ids"] = json.loads(result["episode_ids"] or "[]")
        result["is_default"] = bool(result["is_default"])
        return result

    @staticmethod
    def _style(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["reference_asset_ids"] = json.loads(result["reference_asset_ids"] or "[]")
        result["is_active"] = bool(result["is_active"])
        return result

    @staticmethod
    def _output(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json.loads(result["metadata"] or "{}")
        result["adopted"] = bool(result["adopted"])
        return result
