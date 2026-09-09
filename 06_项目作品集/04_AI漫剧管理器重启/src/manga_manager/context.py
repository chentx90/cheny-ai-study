"""上下文装配器：按预算组装单次 LLM 输入。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from manga_manager.config import get_context_budget
from manga_manager.models import Entity, StyleGuide


class ContextSection(BaseModel):
    name: str
    content: str
    estimated_tokens: int


class ContextBundle(BaseModel):
    sections: list[ContextSection]
    estimated_tokens: int
    max_tokens: int
    warnings: list[str] = Field(default_factory=list)

    def as_prompt(self) -> str:
        return "\n\n".join(f"## {s.name}\n{s.content}" for s in self.sections if s.content.strip())


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _section(name: str, content: str) -> ContextSection:
    return ContextSection(name=name, content=content, estimated_tokens=estimate_tokens(content))


def assemble_context(
    *,
    role_instruction: str,
    style_guide: StyleGuide,
    task_input: str,
    schema_instruction: str,
    entities: list[Entity] | None = None,
    rolling_summary: str = "",
    max_tokens: int | None = None,
) -> ContextBundle:
    budget = max_tokens or get_context_budget()
    warnings: list[str] = []
    entity_lines = []
    for entity in entities or []:
        attrs = "; ".join(f"{attr.key}: {attr.value}" for attr in entity.attrs[:8])
        entity_lines.append(
            f"- {entity.id} | {entity.type} | {entity.name} | importance={entity.importance} | {attrs}"
        )
    sections = [
        _section("Role", role_instruction),
        _section("Style Contract", style_guide.model_dump_json(indent=2)),
        _section("Task Input", task_input),
        _section("Relevant Entities", "\n".join(entity_lines)),
        _section("Rolling Summary", rolling_summary),
        _section("Output Schema", schema_instruction),
    ]
    total = sum(s.estimated_tokens for s in sections)
    if total <= budget:
        return ContextBundle(sections=sections, estimated_tokens=total, max_tokens=budget)

    warnings.append("context exceeded budget; trimming entity attrs and rolling summary")
    trimmed_entities = []
    for entity in entities or []:
        anchor = next((a.value for a in entity.attrs if a.key == "appearance"), "")
        trimmed_entities.append(f"- {entity.id} | {entity.type} | {entity.name} | {anchor}")
    rolling_limit = max(0, budget * 4 // 10)
    sections[3] = _section("Relevant Entities", "\n".join(trimmed_entities))
    sections[4] = _section("Rolling Summary", rolling_summary[:rolling_limit])
    total = sum(s.estimated_tokens for s in sections)
    if total > budget:
        warnings.append("context still exceeds budget; split the input into smaller units")
    return ContextBundle(sections=sections, estimated_tokens=total, max_tokens=budget, warnings=warnings)
