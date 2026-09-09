from __future__ import annotations

from pathlib import Path

from ai_video_manager.llm import parse_json_array
from ai_video_manager.prompt_engine import PromptEngine, load_default_templates
from ai_video_manager.storage import SQLiteStore

OBSOLETE_DEFAULT_PROMPT_TEMPLATE_IDS = {
    "tpl_default_split_planning",
    "tpl_default_script_convert",
    "tpl_default_entity_extract",
    "tpl_default_image_prompt",
    "tpl_default_subject_match",
    "tpl_default_prompt_split",
    "tpl_default_video_generate",
    "tpl_default_video_ancient",
    "tpl_default_video_modern",
    "tpl_default_prompt_rerun",
    "tpl_default_video_agent",
}


class TemplateBackedDurationSplitClient:
    def __init__(
        self,
        *,
        llm_client: object,
        prompt_engine: PromptEngine,
        template: object,
        temperature: float,
        max_tokens: int,
        project_style_prompt: str = "",
    ) -> None:
        self.llm_client = llm_client
        self.prompt_engine = prompt_engine
        self.template = template
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.project_style_prompt = project_style_prompt

    def suggest_duration_splits(self, content: str, minutes: float) -> list[str]:
        prompt = self.prompt_engine.render_prompt(
            self.template,
            {
                variable: {
                    "content": content,
                    "minutes": minutes,
                    "project_style_prompt": self.project_style_prompt,
                }.get(variable, "")
                for variable in self.template.variables
            },
        )
        raw = self.llm_client.complete(
            prompt,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        segments = parse_json_array(raw)
        clean_segments = [segment.strip() for segment in segments if isinstance(segment, str) and segment.strip()]
        if not clean_segments:
            raise RuntimeError("LLM 未返回有效切分片段")
        return clean_segments


def sync_default_prompt_templates(store: SQLiteStore, prompt_engine: PromptEngine) -> None:
    seed_templates = load_default_templates()
    seed_ids = {template.id for template in seed_templates}
    stored_ids = {template.id for template in store.list_prompt_templates()}
    for current in list(prompt_engine.list_templates()):
        if current.id in OBSOLETE_DEFAULT_PROMPT_TEMPLATE_IDS and current.id not in seed_ids:
            prompt_engine.delete_template(current.id)
            try:
                store.delete_prompt_template(current.id)
            except KeyError:
                pass
    for default_template in seed_templates:
        try:
            current = prompt_engine.load_template(default_template.id)
        except KeyError:
            current = None
        default_changed = current is None or (
            current.name != default_template.name
            or current.category != default_template.category
            or current.template != default_template.template
            or set(current.variables) != set(default_template.variables)
            or current.is_default != default_template.is_default
        )
        if not default_changed and default_template.id in stored_ids:
            continue
        refreshed = prompt_engine.add_template(default_template)
        store.save_prompt_template(refreshed)


def normalize_script_format_decision(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    script_values = {"script", "is_script", "script_format", "剧本", "已是剧本", "true", "yes"}
    source_values = {"source_text", "source", "text", "non_script", "needs_conversion", "普通文本", "非剧本", "false", "no"}
    if text in script_values:
        return "script"
    if text in source_values:
        return "source_text"
    if "source" in text or "convert" in text or "非剧本" in text or "普通文本" in text:
        return "source_text"
    if "script" in text or "剧本" in text:
        return "script"
    raise ValueError(f"未知剧本格式判定：{value}")


def resolve_asset_file(store: SQLiteStore, project_id: str, asset_path: str) -> Path:
    normalized = asset_path.replace("\\", "/").lstrip("/")
    if not normalized.startswith("assets/"):
        raise ValueError(f"Asset path must be inside assets/: {asset_path}")
    return store.resolve_project_file(project_id, normalized)
