"""Project session composition over normalized production resources."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai_video_manager.document_processor import DocumentProcessor
from ai_video_manager.models import Project, Segment, WorkflowState, new_id
from ai_video_manager.storage import SQLiteStore
from ai_video_manager.workflow import WorkflowEngine

EMPTY_WORKSPACE_DEFAULTS: dict[str, Any] = {
    "documentText": "",
    "splitStrategy": "chapter",
    "customSplitPattern": "",
    "durationMinutes": 2,
    "segments": [],
    "activeSegmentId": "",
    "contentType": "分集原文",
    "scriptConvertTemplateId": "",
    "projectStylePrompt": "",
    "scripts": {},
    "scriptValidation": {},
    "entities": [],
    "prompts": {},
    "expectedTotalDurationSeconds": None,
    "defaultAspectRatio": "9:16",
    "defaultVideoDuration": 5,
    "defaultVideoModel": "",
    "defaultResolution": "720p",
    "outputRoot": "",
    "sourceAssetsRoot": "",
    "dataRoot": "",
    "assetsConfirmed": False,
}

WORKFLOW_UI_STEPS = [
    {"id": "preprocess", "label": "预处理", "view": "preprocess"},
    {"id": "resources", "label": "资源", "view": "resources"},
    {"id": "video", "label": "视频", "view": "video"},
]

XYQ_MODELS = [
    {"value": "Seedance_2.0_mini_lite", "label": "Seedance 2.0 Mini Lite（普通用户）"},
    {"value": "Seedance_2.0_mini", "label": "Seedance 2.0 Mini（VIP）"},
    {"value": "seedance2.0_vision", "label": "Seedance 2.0 Vision（VIP）"},
    {"value": "seedance2.0_fast_vision", "label": "Seedance 2.0 Fast Vision（VIP）"},
    {"value": "__custom__", "label": "手动输入模型 ID"},
]

GATEWAY_MODELS = [
    {"value": "", "label": "服务默认"},
    {"value": "kling-v2.1", "label": "Kling v2.1"},
    {"value": "kling-v2.1-master", "label": "Kling v2.1 Master"},
    {"value": "seedance-v1-pro", "label": "Seedance v1 Pro"},
    {"value": "veo3-fast", "label": "Veo 3 Fast"},
    {"value": "wan2.1", "label": "Wan 2.1"},
    {"value": "__custom__", "label": "自定义模型 ID"},
]


class RevisionConflictError(ValueError):
    pass


@dataclass
class ProjectDomainService:
    store: SQLiteStore
    document_processor: DocumentProcessor | None = None

    def ensure_migrated(self, project_id: str) -> None:
        self.store.get_project(project_id)
        preprocess = self.store.get_preprocess(project_id)
        if preprocess and preprocess.get("migrated_from_blob"):
            return
        blob = self.store.get_workspace_blob(project_id)
        if blob:
            self._import_blob(project_id, blob, mark_migrated=True)
        elif not preprocess:
            self.store.upsert_preprocess(project_id, {})

    def get_workspace_view(self, project_id: str) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        preprocess = self.store.get_preprocess(project_id) or {}
        segments = self.store.list_project_segments(project_id)
        scripts = self.store.list_project_scripts(project_id)
        scripts_map = {item["segment_id"]: item["content"] for item in scripts}
        validation_map = {
            item["segment_id"]: item.get("validation") if isinstance(item.get("validation"), dict) else {}
            for item in scripts
        }
        view = {
            **EMPTY_WORKSPACE_DEFAULTS,
            "documentText": preprocess.get("document_text", ""),
            "splitStrategy": preprocess.get("split_strategy", "chapter"),
            "customSplitPattern": preprocess.get("custom_split_pattern", ""),
            "durationMinutes": preprocess.get("duration_minutes", 2),
            "activeSegmentId": preprocess.get("active_segment_id", ""),
            "contentType": preprocess.get("content_type", "分集原文"),
            "scriptConvertTemplateId": preprocess.get("script_convert_template_id", ""),
            "projectStylePrompt": preprocess.get("project_style_prompt", ""),
            "expectedTotalDurationSeconds": preprocess.get("expected_total_duration_seconds"),
            "defaultAspectRatio": preprocess.get("default_aspect_ratio", "9:16"),
            "defaultVideoDuration": preprocess.get("default_video_duration", 5),
            "defaultVideoModel": preprocess.get("default_video_model", ""),
            "defaultResolution": preprocess.get("default_resolution", "720p"),
            "outputRoot": preprocess.get("output_root", ""),
            "sourceAssetsRoot": preprocess.get("source_assets_root", ""),
            "dataRoot": preprocess.get("data_root", ""),
            "assetsConfirmed": bool(preprocess.get("assets_confirmed")),
            "segments": segments,
            "scripts": scripts_map,
            "scriptValidation": validation_map,
            "entities": [],
            "prompts": {},
            "revision": preprocess.get("revision", 0),
        }
        doc_file = preprocess.get("document_file")
        if isinstance(doc_file, dict) and doc_file:
            view["documentFile"] = doc_file
        return view

    def import_workspace_dict(self, project_id: str, data: dict[str, Any], *, revision: int | None = None) -> dict[str, Any]:
        self.store.get_project(project_id)
        current = self.store.get_preprocess(project_id) or {}
        if revision is not None and int(current.get("revision") or 0) != int(revision):
            raise RevisionConflictError("workspace revision mismatch")
        self._import_blob(project_id, data, mark_migrated=True)
        project = self.store.get_project(project_id)
        # Legacy import payloads may still carry prompts/entities/videoTasks used only for workflow flags.
        flag_source = {**self.get_workspace_view(project_id), **data}
        self.store._sync_project_flags_from_workspace(project, flag_source)
        now = datetime.now(timezone.utc).isoformat()
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE projects SET current_state = ?, updated_at = ?, flags = ? WHERE id = ?",
                (
                    project.current_state.value,
                    now,
                    json.dumps(self.store._project_flags(project), ensure_ascii=False),
                    project_id,
                ),
            )
        return self.get_workspace_view(project_id)

    def update_document(
        self,
        project_id: str,
        *,
        document_text: str | None = None,
        split_strategy: str | None = None,
        custom_split_pattern: str | None = None,
        duration_minutes: float | None = None,
        active_segment_id: str | None = None,
        content_type: str | None = None,
        script_convert_template_id: str | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        self._check_revision(project_id, revision)
        patch: dict[str, Any] = {}
        if document_text is not None:
            patch["document_text"] = document_text
        if split_strategy is not None:
            patch["split_strategy"] = split_strategy
        if custom_split_pattern is not None:
            patch["custom_split_pattern"] = custom_split_pattern
        if duration_minutes is not None:
            patch["duration_minutes"] = duration_minutes
        if active_segment_id is not None:
            patch["active_segment_id"] = active_segment_id
        if content_type is not None:
            patch["content_type"] = str(content_type).strip() or "分集原文"
        if script_convert_template_id is not None:
            patch["script_convert_template_id"] = str(script_convert_template_id).strip()
        self.store.upsert_preprocess(project_id, patch, bump_revision=True)
        self._sync_project_flags(project_id)
        return self.get_workspace_view(project_id)

    def update_settings(
        self,
        project_id: str,
        *,
        expected_total_duration_seconds: float | None = None,
        default_aspect_ratio: str | None = None,
        default_video_duration: int | None = None,
        default_video_model: str | None = None,
        default_resolution: str | None = None,
        project_style_prompt: str | None = None,
        output_root: str | None = None,
        source_assets_root: str | None = None,
        data_root: str | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        self._check_revision(project_id, revision)
        patch: dict[str, Any] = {}
        if expected_total_duration_seconds is not None:
            patch["expected_total_duration_seconds"] = expected_total_duration_seconds
        if default_aspect_ratio is not None:
            patch["default_aspect_ratio"] = default_aspect_ratio
        if default_video_duration is not None:
            patch["default_video_duration"] = int(default_video_duration)
        if default_video_model is not None:
            patch["default_video_model"] = default_video_model
        if default_resolution is not None:
            patch["default_resolution"] = default_resolution
        if project_style_prompt is not None:
            patch["project_style_prompt"] = str(project_style_prompt).strip()
        if output_root is not None:
            patch["output_root"] = str(output_root).strip()
        if source_assets_root is not None:
            patch["source_assets_root"] = str(source_assets_root).strip()
        if data_root is not None:
            from ai_video_manager.project_bundle import validate_data_root_path

            patch["data_root"] = validate_data_root_path(self.store, data_root)
        self.store.upsert_preprocess(project_id, patch, bump_revision=True)
        if data_root is not None:
            from ai_video_manager.project_bundle import ensure_bundle_layout, resolve_project_data_root

            ensure_bundle_layout(resolve_project_data_root(self.store, project_id))
        return self.get_workspace_view(project_id)

    def refresh_source_assets(self, project_id: str) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        preprocess = self.store.get_preprocess(project_id) or {}
        source_root = str(preprocess.get("source_assets_root") or "").strip()
        if not source_root:
            raise ValueError("请先在项目设置中填写原始素材导入位置")
        stats = self.store.import_assets_from_source_root(project_id, source_root)
        self.store.upsert_preprocess(project_id, {"assets_confirmed": False}, bump_revision=True)
        return {
            "imported": stats.get("imported", 0),
            "by_type": stats.get("by_type", {}),
            "assets": self.store.list_assets(project_id),
        }

    def replace_segments(
        self,
        project_id: str,
        segments: list[dict[str, Any]],
        *,
        clear_downstream: bool = False,
        active_segment_id: str | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        self._check_revision(project_id, revision)
        normalized = self._normalize_segments(segments)
        self.store.replace_project_segments(project_id, normalized)
        patch: dict[str, Any] = {}
        if active_segment_id is not None:
            patch["active_segment_id"] = active_segment_id
        elif normalized:
            patch["active_segment_id"] = normalized[0]["id"]
        if clear_downstream:
            self.store.clear_project_scripts(project_id)
            self.store.clear_project_prompt_cards(project_id)
            self.store.upsert_preprocess(project_id, {"assets_confirmed": False}, bump_revision=False)
        if patch:
            self.store.upsert_preprocess(project_id, patch, bump_revision=True)
        else:
            self.store.bump_preprocess_revision(project_id)
        self._sync_project_flags(project_id)
        return self.get_workspace_view(project_id)

    def save_segment_script(
        self,
        project_id: str,
        segment_id: str,
        *,
        content: str,
        validation: dict[str, Any] | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        self._check_revision(project_id, revision)
        segments = self.store.list_project_segments(project_id)
        if not any(item["id"] == segment_id for item in segments):
            raise KeyError(f"Segment not found: {segment_id}")
        self.store.upsert_project_script(project_id, segment_id, content, validation or {})
        self._sync_project_flags(project_id)
        return self.get_workspace_view(project_id)

    def replace_scripts(
        self,
        project_id: str,
        scripts: dict[str, str],
        *,
        script_validation: dict[str, dict[str, Any]] | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        self._check_revision(project_id, revision)
        validation_map = script_validation if isinstance(script_validation, dict) else {}
        segment_ids = {item["id"] for item in self.store.list_project_segments(project_id)}
        for segment_id, content in scripts.items():
            if segment_id not in segment_ids:
                raise KeyError(f"Segment not found: {segment_id}")
            validation = validation_map.get(segment_id)
            self.store.upsert_project_script(
                project_id,
                segment_id,
                str(content or ""),
                validation if isinstance(validation, dict) else {},
            )
        if scripts:
            self.store.bump_preprocess_revision(project_id)
        self._sync_project_flags(project_id)
        return self.get_workspace_view(project_id)

    def apply_split_persist(
        self,
        project_id: str,
        segments: list[Segment],
        *,
        split_strategy: str = "chapter",
        mark_orphaned_tasks: bool = True,
    ) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        segment_dicts = [
            {
                "id": segment.id,
                "order": segment.order,
                "title": f"第{segment.order}集",
                "content": segment.content,
            }
            for segment in segments
        ]
        orphaned_count = 0
        if mark_orphaned_tasks:
            orphaned_count = self.store.mark_video_tasks_orphaned(
                project_id,
                keep_segment_ids={segment.id for segment in segments},
            )
        self.replace_segments(
            project_id,
            segment_dicts,
            clear_downstream=True,
            active_segment_id=segment_dicts[0]["id"] if segment_dicts else "",
        )
        self.store.upsert_preprocess(
            project_id,
            {"split_strategy": split_strategy},
            bump_revision=False,
        )
        project = self.store.get_project(project_id)
        project.has_document = True
        project.has_segments = bool(segment_dicts)
        project.current_state = WorkflowState.DOCUMENT_SPLIT
        self.store.save_project(project)
        return {
            "workspace": self.get_workspace_view(project_id),
            "orphaned_task_count": orphaned_count,
        }

    def reset_on_document_upload(self, project_id: str, *, document_text: str, document_file: dict[str, Any]) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        self.store.replace_project_segments(project_id, [])
        self.store.clear_project_scripts(project_id)
        self.store.clear_project_prompt_cards(project_id)
        self.store.upsert_preprocess(
            project_id,
            {
                "document_text": document_text,
                "document_file": document_file,
                "active_segment_id": "",
                "assets_confirmed": False,
                "split_strategy": "chapter",
            },
            bump_revision=True,
        )
        self._sync_project_flags(project_id)
        return self.get_workspace_view(project_id)

    def confirm_assets(self, project_id: str, *, confirmed: bool = True) -> dict[str, Any]:
        self.ensure_migrated(project_id)
        self.store.upsert_preprocess(project_id, {"assets_confirmed": confirmed}, bump_revision=True)
        self._sync_project_flags(project_id)
        return self.get_workspace_view(project_id)

    def workflow_ui(self, project_id: str, checkpoint_manager: Any) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        engine = WorkflowEngine(project, checkpoint_manager)
        active_index = self._active_step_index(project)
        steps = []
        for index, step in enumerate(WORKFLOW_UI_STEPS):
            steps.append(
                {
                    **step,
                    "index": index,
                    "status": "done" if index < active_index else ("active" if index == active_index else "pending"),
                }
            )
        return {
            "project_id": project_id,
            "current_state": project.current_state.value,
            "active_step_index": active_index,
            "steps": steps,
            "states": {
                state.value: {
                    "can_jump": engine.can_jump_to(state),
                    "missing": engine.missing_prerequisites(state),
                }
                for state in WorkflowState
            },
        }

    def video_provider_catalog(self, provider: str) -> dict[str, Any]:
        from ai_video_manager.xyq_cli import is_xyq_provider

        is_xyq = is_xyq_provider(provider)
        duration_min, duration_max = 4, 15
        durations = [{"value": value, "label": f"{value} 秒"} for value in range(duration_min, duration_max + 1)]
        if is_xyq:
            return {
                "provider": provider,
                "models": XYQ_MODELS,
                "aspect_ratios": [
                    {"value": "9:16", "label": "9:16 竖屏"},
                    {"value": "16:9", "label": "16:9 横屏"},
                    {"value": "3:4", "label": "3:4 竖幅"},
                    {"value": "4:3", "label": "4:3 标准"},
                ],
                "resolutions": [
                    {"value": "720p", "label": "720p"},
                    {"value": "1080p", "label": "1080p"},
                ],
                "reference_modes": [
                    {"value": "none", "label": "无参考（纯提示词）"},
                    {"value": "omni", "label": "Omni 多模态"},
                ],
                "duration_min": duration_min,
                "duration_max": duration_max,
                "durations": durations,
                "defaults": {
                    "model": "Seedance_2.0_mini_lite",
                    "aspect_ratio": "9:16",
                    "resolution": "720p",
                    "duration": 5,
                    "reference_mode": "omni",
                    "generate_audio": True,
                },
            }
        return {
            "provider": provider,
            "models": GATEWAY_MODELS,
            "aspect_ratios": [
                {"value": "9:16", "label": "9:16 竖屏"},
                {"value": "16:9", "label": "16:9 横屏"},
                {"value": "1:1", "label": "1:1 方形"},
                {"value": "4:3", "label": "4:3 标准"},
                {"value": "3:4", "label": "3:4 竖幅"},
                {"value": "21:9", "label": "21:9 宽银幕"},
            ],
            "resolutions": [
                {"value": "720p", "label": "720p"},
                {"value": "1080p", "label": "1080p"},
                {"value": "2k", "label": "2K"},
                {"value": "4k", "label": "4K"},
            ],
            "reference_modes": [
                {"value": "none", "label": "无参考（纯提示词）"},
                {"value": "first_last", "label": "首尾帧 F/L"},
                {"value": "multi", "label": "多图 Multi"},
                {"value": "omni", "label": "Omni 多模态"},
            ],
            "duration_min": duration_min,
            "duration_max": duration_max,
            "durations": durations,
            "defaults": {
                "model": "",
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "duration": 5,
                "reference_mode": "omni",
                "generate_audio": True,
            },
        }

    def sanitize_video_request(
        self,
        provider: str,
        settings: dict[str, Any],
        *,
        project_defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        catalog = self.video_provider_catalog(provider)
        defaults = {**catalog["defaults"], **(project_defaults or {})}
        duration = int(settings.get("duration") or defaults.get("duration") or 5)
        duration = max(catalog["duration_min"], min(catalog["duration_max"], duration))

        def pick_allowed(value: str, options: list[dict[str, str]], fallback: str) -> str:
            clean = str(value or "").strip()
            if any(item["value"] == clean for item in options):
                return clean
            return fallback

        model = str(settings.get("model") or defaults.get("model") or "").strip()
        known_models = {item["value"] for item in catalog["models"] if item["value"] and item["value"] != "__custom__"}
        if model and model != "__custom__" and model not in known_models:
            model = str(defaults.get("model") or catalog["defaults"]["model"])

        aspect_ratio = pick_allowed(
            str(settings.get("aspect_ratio") or settings.get("aspectRatio") or defaults.get("aspect_ratio") or ""),
            catalog["aspect_ratios"],
            str(defaults.get("aspect_ratio") or catalog["defaults"]["aspect_ratio"]),
        )
        resolution = pick_allowed(
            str(settings.get("resolution") or defaults.get("resolution") or ""),
            catalog["resolutions"],
            str(defaults.get("resolution") or catalog["defaults"]["resolution"]),
        )
        reference_mode = pick_allowed(
            str(settings.get("reference_mode") or settings.get("referenceMode") or defaults.get("reference_mode") or ""),
            catalog["reference_modes"],
            str(defaults.get("reference_mode") or catalog["defaults"]["reference_mode"]),
        )

        def list_field(*keys: str) -> list[str]:
            for key in keys:
                value = settings.get(key)
                if isinstance(value, list):
                    return [str(item).strip() for item in value if str(item).strip()]
            return []

        return {
            "model": model,
            "custom_model": str(settings.get("custom_model") or settings.get("customModel") or "").strip(),
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "duration": duration,
            "reference_mode": reference_mode,
            "generate_audio": bool(
                settings.get("generate_audio")
                if settings.get("generate_audio") is not None
                else settings.get("generateAudio")
                if settings.get("generateAudio") is not None
                else defaults.get("generate_audio", True)
            ),
            "first_frame": str(settings.get("first_frame") or settings.get("firstFrame") or "").strip(),
            "last_frame": str(settings.get("last_frame") or settings.get("lastFrame") or "").strip(),
            "reference_images": list_field("reference_images", "referenceImages"),
            "reference_videos": list_field("reference_videos", "referenceVideos"),
            "reference_audios": list_field("reference_audios", "referenceAudios"),
        }

    def _import_blob(self, project_id: str, data: dict[str, Any], *, mark_migrated: bool) -> None:
        segments = data.get("segments") if isinstance(data.get("segments"), list) else []
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        script_validation = data.get("scriptValidation") if isinstance(data.get("scriptValidation"), dict) else {}
        doc_file = data.get("documentFile") if isinstance(data.get("documentFile"), dict) else {}
        self.store.upsert_preprocess(
            project_id,
            {
                "document_text": str(data.get("documentText") or ""),
                "split_strategy": str(data.get("splitStrategy") or "chapter"),
                "custom_split_pattern": str(data.get("customSplitPattern") or ""),
                "duration_minutes": float(data.get("durationMinutes") or 2),
                "document_file": doc_file,
                "active_segment_id": str(data.get("activeSegmentId") or ""),
                "content_type": str(data.get("contentType") or "分集原文"),
                "script_convert_template_id": str(data.get("scriptConvertTemplateId") or ""),
                "project_style_prompt": str(data.get("projectStylePrompt") or ""),
                "expected_total_duration_seconds": data.get("expectedTotalDurationSeconds"),
                "default_aspect_ratio": str(data.get("defaultAspectRatio") or "9:16"),
                "default_video_duration": int(data.get("defaultVideoDuration") or 5),
                "default_video_model": str(data.get("defaultVideoModel") or ""),
                "default_resolution": str(data.get("defaultResolution") or "720p"),
                "output_root": str(data.get("outputRoot") or ""),
                "source_assets_root": str(data.get("sourceAssetsRoot") or ""),
                "data_root": str(data.get("dataRoot") or ""),
                "assets_confirmed": bool(data.get("assetsConfirmed")),
                "migrated_from_blob": mark_migrated,
            },
            bump_revision=mark_migrated,
        )
        self.store.replace_project_segments(project_id, self._normalize_segments(segments))
        for segment in self._normalize_segments(segments):
            segment_id = segment["id"]
            content = str(scripts.get(segment_id) or "")
            validation = script_validation.get(segment_id) if isinstance(script_validation.get(segment_id), dict) else {}
            if content or validation:
                self.store.upsert_project_script(project_id, segment_id, content, validation)

        self.store.delete_workspace_blob(project_id)

    def _normalize_segments(self, segments: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            segment_id = str(segment.get("id") or new_id("seg"))
            order = int(segment.get("order") or index + 1)
            title = str(segment.get("title") or f"第{order}集")
            content = str(segment.get("content") or "")
            metadata = {key: value for key, value in segment.items() if key not in {"id", "order", "title", "content"}}
            normalized.append(
                {
                    "id": segment_id,
                    "order": order,
                    "title": title,
                    "content": content,
                    "metadata": metadata,
                }
            )
        normalized.sort(key=lambda item: item["order"])
        for index, segment in enumerate(normalized, start=1):
            segment["order"] = index
            if not segment.get("title") or re.fullmatch(r"第\d+集", str(segment.get("title"))):
                segment["title"] = f"第{index}集"
        return normalized

    def _check_revision(self, project_id: str, revision: int | None) -> None:
        if revision is None:
            return
        current = self.store.get_preprocess(project_id) or {}
        if int(current.get("revision") or 0) != int(revision):
            raise RevisionConflictError("workspace revision mismatch")

    def _sync_project_flags(self, project_id: str) -> None:
        view = self.get_workspace_view(project_id)
        project = self.store.get_project(project_id)
        self.store._sync_project_flags_from_workspace(project, view)
        now = datetime.now(timezone.utc).isoformat()
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE projects SET current_state = ?, updated_at = ?, flags = ? WHERE id = ?",
                (
                    project.current_state.value,
                    now,
                    json.dumps(self.store._project_flags(project), ensure_ascii=False),
                    project_id,
                ),
            )

    def _active_step_index(self, project: Project) -> int:
        state = project.current_state.value
        if state in {"initialized", "document_split", "script_converted"}:
            return 0
        if state in {"entities_extracted", "entities_bound"}:
            return 1
        return 2
