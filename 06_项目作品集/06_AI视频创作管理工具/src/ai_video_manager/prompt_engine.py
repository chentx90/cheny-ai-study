from __future__ import annotations

import json
import os
import re
from pathlib import Path
from string import Template
from typing import Any

from .models import PromptCategory, PromptTemplate


def resolve_default_template_path() -> Path:
    env_path = str(os.environ.get("AVM_DEFAULT_TEMPLATES_PATH") or "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()

    module_file = Path(__file__).resolve()
    candidates = [
        Path("/app/config/default_prompt_templates.json"),
        module_file.parents[2] / "config" / "default_prompt_templates.json",
        Path.cwd() / "config" / "default_prompt_templates.json",
    ]
    try:
        from .runtime_paths import resolve_workspace_root

        candidates.append(resolve_workspace_root() / "config" / "default_prompt_templates.json")
    except Exception:
        pass

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[1]


DEFAULT_TEMPLATE_PATH = resolve_default_template_path()
REQUIRED_TEMPLATE_VARIABLES: dict[PromptCategory, set[str]] = {
    PromptCategory.SPLIT_PLANNING: {"minutes", "content"},
    PromptCategory.SCRIPT_CONVERT: {"content_type", "content"},
    PromptCategory.ENTITY_EXTRACT: {"episode_title", "episode_order", "episode_script"},
    PromptCategory.ENTITY_CONSOLIDATE: {"extraction_catalog"},
    PromptCategory.ENTITY_SETTING: {"entity_profile"},
    PromptCategory.CHARACTER_ASSET_PROMPT: {
        "entity_name", "entity_setting", "variant_setting", "project_style_prompt",
        "project_negative_prompt", "type_prompt", "type_negative_prompt", "reference_summary", "view_type",
    },
    PromptCategory.SCENE_ASSET_PROMPT: {
        "entity_name", "entity_setting", "variant_setting", "project_style_prompt",
        "project_negative_prompt", "type_prompt", "type_negative_prompt", "reference_summary", "view_type",
    },
    PromptCategory.PROP_ASSET_PROMPT: {
        "entity_name", "entity_setting", "variant_setting", "project_style_prompt",
        "project_negative_prompt", "type_prompt", "type_negative_prompt", "reference_summary", "view_type",
    },
    PromptCategory.SUBJECT_MATCH: {"prompt_card", "entity_catalog"},
    PromptCategory.PROMPT_SPLIT: {
        "script",
        "entity_catalog",
        "max_duration_seconds",
        "expected_total_duration_seconds",
    },
    PromptCategory.VIDEO_GENERATE: {
        "script_excerpt",
        "entity_catalog",
        "max_duration_seconds",
        "neighbor_context",
    },
    PromptCategory.PROMPT_RERUN: {
        "script_excerpt",
        "entity_catalog",
        "max_duration_seconds",
        "target_card",
        "generated_context",
    },
    PromptCategory.VIDEO_AGENT: {"segment", "prompt"},
    PromptCategory.WORKFLOW_AGENT: {
        "user_request", "project_context", "current_view", "active_context", "command_catalog",
        "observations", "step", "conversation_context",
    },
}


class PromptTemplateError(ValueError):
    pass


def load_default_templates(path: Path = DEFAULT_TEMPLATE_PATH) -> list[PromptTemplate]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PromptTemplateError(f"Default prompt template file is not valid JSON: {path}") from exc
    if not isinstance(payload, list):
        raise PromptTemplateError(f"Default prompt template file must contain a JSON array: {path}")
    templates: list[PromptTemplate] = []
    for item in payload:
        if not isinstance(item, dict):
            raise PromptTemplateError("Each default prompt template must be an object")
        templates.append(
            PromptTemplate(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                category=PromptCategory(str(item.get("category") or "")),
                template=str(item.get("template") or ""),
                variables=[str(value) for value in item.get("variables", [])],
                is_default=bool(item.get("is_default", True)),
                version=int(item.get("version") or 1),
            )
        )
    return templates


class PromptEngine:
    variable_pattern = re.compile(
        r"""
        \$(?:
            (?P<braced>[A-Za-z_][A-Za-z0-9_]*)
            |
            \{(?P<named>[A-Za-z_][A-Za-z0-9_]*)\}
        )
        """,
        re.VERBOSE,
    )
    legacy_variable_pattern = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

    def __init__(self, templates: list[PromptTemplate] | None = None) -> None:
        source_templates = load_default_templates() if templates is None else templates
        self._templates = {template.id: template for template in source_templates}

    def list_templates(self) -> list[PromptTemplate]:
        return list(self._templates.values())

    def load_template(self, name_or_id: str) -> PromptTemplate:
        for template in self._templates.values():
            if template.id == name_or_id or template.name == name_or_id:
                return template
        raise KeyError(f"Prompt template not found: {name_or_id}")

    def add_template(self, template: PromptTemplate) -> PromptTemplate:
        prepared = self.prepare_template(template)
        self.validate_template(prepared)
        self._templates[prepared.id] = prepared
        return prepared

    def load_template_record(self, template: PromptTemplate) -> PromptTemplate:
        prepared = self.prepare_template(template)
        self._templates[prepared.id] = prepared
        return prepared

    def delete_template(self, template_id: str) -> None:
        if template_id not in self._templates:
            raise KeyError(f"Prompt template not found: {template_id}")
        del self._templates[template_id]

    def validate_template(self, template: PromptTemplate) -> None:
        declared = set(template.variables)
        parsed = self.extract_variables(template.template)
        if parsed != declared:
            raise PromptTemplateError(
                "Template variables mismatch: "
                f"declared={sorted(declared)}, parsed={sorted(parsed)}"
            )
        required = REQUIRED_TEMPLATE_VARIABLES.get(template.category, set())
        missing_required = required - parsed
        if missing_required:
            raise PromptTemplateError(
                f"{template.category.value} template must include variables: "
                f"{', '.join(f'${name}' for name in sorted(missing_required))}"
            )

    def prepare_template(self, template: PromptTemplate) -> PromptTemplate:
        normalized_body = self.normalize_template_syntax(template.template)
        variables = sorted(self.extract_variables(normalized_body))
        return PromptTemplate(
            id=template.id,
            name=template.name,
            category=template.category,
            template=normalized_body,
            variables=variables,
            examples=template.examples,
            is_default=template.is_default,
            version=template.version,
        )

    def normalize_template_syntax(self, template: str) -> str:
        return self.legacy_variable_pattern.sub(lambda match: f"${match.group(1)}", template)

    def extract_variables(self, template: str) -> set[str]:
        return {
            match.group("braced") or match.group("named")
            for match in self.variable_pattern.finditer(template)
        }

    def render_prompt(self, template: PromptTemplate, context: dict[str, object]) -> str:
        missing = set(template.variables) - set(context)
        if missing:
            raise KeyError(f"Missing template variables: {', '.join(sorted(missing))}")
        return Template(template.template).safe_substitute({key: str(value) for key, value in context.items()})

    def recommend_style(self, content: str) -> list[PromptTemplate]:
        ancient_tokens = ("剑", "客栈", "江湖", "皇", "仙", "古代", "少侠")
        modern_tokens = ("电脑", "手机", "办公室", "城市", "地铁", "程序", "直播")
        if any(token in content for token in ancient_tokens):
            return [template for template in self._templates.values() if "古风" in template.name]
        if any(token in content for token in modern_tokens):
            return [template for template in self._templates.values() if "现代" in template.name]
        return [template for template in self._templates.values() if template.category == PromptCategory.VIDEO_GENERATE]


def template_context(template: PromptTemplate, values: dict[str, Any]) -> dict[str, object]:
    return {variable: values.get(variable, "") for variable in template.variables}


def template_for_category(prompt_engine: PromptEngine, category: str) -> PromptTemplate:
    templates = [template for template in prompt_engine.list_templates() if template.category.value == category]
    if not templates:
        raise KeyError(f"No prompt template for category: {category}")
    ordered = [template for template in templates if template.is_default] + [
        template for template in templates if not template.is_default
    ]
    last_error: Exception | None = None
    for template in ordered:
        try:
            prompt_engine.validate_template(template)
            return template
        except PromptTemplateError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return ordered[0]


def request_template_for_category(
    prompt_engine: PromptEngine,
    category: str,
    template_name_or_id: str | None,
) -> PromptTemplate:
    if template_name_or_id:
        try:
            template = prompt_engine.load_template(template_name_or_id)
            if template.category.value != category:
                raise ValueError(
                    f"Prompt template {template.id} belongs to {template.category.value}, expected {category}"
                )
            prompt_engine.validate_template(template)
            return template
        except (KeyError, PromptTemplateError, ValueError):
            pass
    template = template_for_category(prompt_engine, category)
    prompt_engine.validate_template(template)
    return template
