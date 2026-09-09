"""S4 Screenwriter Agent。

职责边界（设计原则）：
  - 从场景原文生成有序 Shot 列表（叙事层：景别/动作/情绪/对话）。
  - 只写"画面发生什么"，不写运镜/光影/画风术语（留给 PromptComposer）。
  - 每个 Shot 包含：景别、动作描述、情绪、对话、预计时长。
  - 支持反思环（generate → critique → revise，上限 2 轮）。

核心数据结构：
  - ExtractedShot：LLM 输出的单镜头 schema
  - ScreenwritingResult：最终产物（shots + critique_issues）
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from manga_manager.llm.client import get_llm
from manga_manager.models import Entity, StrictModel

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.MULTILINE)
MAX_REVISIONS = 2


def _strip_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw).strip()


VALID_SHOT_TYPES = [
    "wide",
    "full",
    "medium",
    "close-up",
    "extreme-close-up",
    "over-shoulder",
    "pov",
    "insert",
    "two-shot",
    "group",
]


class ExtractedShot(StrictModel):
    """LLM 输出的单镜头。"""

    shot_type: str = Field(
        description=f"景别，可选：{', '.join(VALID_SHOT_TYPES)}",
    )
    action: str = Field(description="动作/画面描述，不写光影/镜头运动")
    emotion: str = Field(default="", description="情绪基调，如'紧张''温馨''孤独'")
    dialogue: str = Field(default="", description="本镜头的对话（如有）")
    duration: float = Field(default=4.0, ge=0, description="预计时长秒数")
    characters: list[str] = Field(
        default_factory=list,
        description="本镜头出现的角色称呼（用于 S5 绑定）"
    )


class ScreenwritingCritique(StrictModel):
    """反思环批评结果。"""

    issues: list[str] = Field(default_factory=list, description="问题列表")
    ok: bool = Field(description="是否通过校验")
    severity: str = Field(default="none", description="none / minor / major")


class ScreenwritingResult(StrictModel):
    """场景剧本生成结果。"""

    shots: list[ExtractedShot] = Field(default_factory=list)
    revisions: int = Field(default=0, description="反思修订次数")
    critique_summary: str = Field(default="", description="反思环总结")


class ScreenwriterError(RuntimeError):
    pass


def format_scene_meta(scene_idx: int, scene_id: str, time: str, location: str, pov: str) -> str:
    parts = [f"场景{scene_idx}（id={scene_id}）"]
    if time:
        parts.append(f"时间：{time}")
    if location:
        parts.append(f"地点：{location}")
    if pov:
        parts.append(f"视角：{pov}")
    return " / ".join(parts)


def format_relevant_entities(entities: list[Entity], max_display: int = 10) -> str:
    """格式化在场实体给 LLM。"""
    if not entities:
        return "本场景无已知实体。"
    shown = entities[:max_display]
    lines = []
    for ent in shown:
        aliases_str = ", ".join(ent.aliases[:2]) if ent.aliases else "—"
        appearance = ""
        for attr in ent.attrs:
            if attr.key == "appearance":
                appearance = attr.value[:60]
                break
        variant_labels = ", ".join(v.label for v in ent.variants[:3]) if ent.variants else ""
        parts = [ent.name]
        if aliases_str != "—":
            parts.append(f"别名=[{aliases_str}]")
        if appearance:
            parts.append(f"外观='{appearance}'")
        if variant_labels:
            parts.append(f"变体=[{variant_labels}]")
        lines.append(f"- {ent.id} | {' | '.join(parts)}")
    return "\n".join(lines)


_SYSTEM_TEMPLATE = """\
你是「编剧 Agent」（Screenwriter）。
你的职责：从场景原文生成有序 Shot 列表（叙事层）。

## 规则

1. 每个 Shot 代表一个画面，必须包含：
   - shot_type: 景别（{shot_types}）
   - action: 动作/画面描述（**只写"发生什么"，不写运镜/光影/画风**）
   - duration: 预估时长（秒，2~10之间）
2. 可选字段：
   - emotion: 情绪基调（如"紧张""温柔""孤独"）
   - dialogue: 本镜头的对话（如有）
   - characters: 本镜头出现的角色称呼列表
3. Shot 必须按原文顺序，保持时间线连续。
4. 不遗漏重要情节，不添加原文没有的内容。
5. 角色称呼使用原文中的称呼。

## 已知实体（本场景涉及）

{relevant_entities}

## 前情提要

{rolling_summary}

## 叙事风格

{style_guide}

只输出 JSON，不输出说明文字。

## JSON 格式要求（严格遵守）

- 所有字符串值内禁止出现原始换行符、制表符等控制字符；如需换行请改写为一句话。
- 不得在 JSON 字符串中使用反斜杠转义（如 \\n \\t），直接用空格或句号代替。
- 输出必须可被 json.loads() 直接解析，不得有尾随逗号、注释或多余字符。

输出 schema:
{{
  "shots": [
    {{
      "shot_type": "medium",
      "action": "哥哥坐在书桌前，手里拿着笔，目光呆滞地看着窗外",
      "emotion": "迷茫",
      "dialogue": "",
      "duration": 4.0,
      "characters": ["哥哥"]
    }}
  ]
}}
"""


_CRITIQUE_SYSTEM_TEMPLATE = """\
你是「反思环审查员」（Critic）。
你的职责：检查编剧 Agent 生成的 Shot 列表是否符合要求。

## 检查项

1. 完整性：是否遗漏场景中的重要情节？
2. 准确性：Shot 顺序是否与原文一致？有无时间线混乱？
3. 景别合理性：景别选择是否符合画面内容？
4. 对话归属：dialogue 的角色是否正确绑定到 characters？
5. 风格合规：是否有运镜/光影/画风用语？（不应该有）

## 已知实体

{relevant_entities}

## 场景原文

{scene_text}

## 生成的 Shot 列表

{shots_json}

## 输出规则

- 只检查，不修改 Shot 内容。
- 如果没有问题，severity="none"，issues=[]。
- 如果有小问题（不影响主线），severity="minor"，issues 描述问题。
- 如果有大问题（遗漏关键情节、时间线混乱等），severity="major"，issues 描述问题。
- 只输出 JSON。

输出 schema:
{{
  "ok": true|false,
  "severity": "none"|"minor"|"major",
  "issues": ["问题1", "问题2"]
}}
"""


class ScreenwriterAgent:
    """S4 编剧 Agent 核心逻辑。

    调用链：
      generate_shots → critique → (revise if needed) → 返回结果
    """

    def __init__(self, llm: Any | None = None):
        self._llm = llm or get_llm(json_mode=True)
        self._critic_llm = self._llm

    def generate_shots(
        self,
        scene_text: str,
        *,
        scene_meta: str,
        relevant_entities: list[Entity],
        rolling_summary: str,
        style_guide: str = "",
    ) -> ScreenwritingResult:
        """生成场景的 Shot 列表，带反思环。"""
        entities_text = format_relevant_entities(relevant_entities)
        system = _SYSTEM_TEMPLATE.format(
            shot_types=", ".join(VALID_SHOT_TYPES),
            relevant_entities=entities_text,
            rolling_summary=rolling_summary or "（无前情提要）",
            style_guide=style_guide or "节奏清晰，镜头语言服务情绪，不额外扩写情节",
        )
        user = f"{scene_meta}\n\n场景原文（{len(scene_text)} 字）：\n{scene_text}"

        current_result = self._call_llm(system, user)
        revisions = 0

        for _ in range(MAX_REVISIONS):
            critique = self._critique_shots(
                scene_text, current_result, entities_text
            )
            if critique.severity == "none":
                break
            if critique.severity == "major":
                revisions += 1
                current_result = self._revise_with_feedback(
                    current_result, critique, system, user, entities_text
                )
            elif critique.severity == "minor" and revisions < MAX_REVISIONS:
                revisions += 1
                current_result = self._revise_with_feedback(
                    current_result, critique, system, user, entities_text
                )

        return ScreenwritingResult(
            shots=current_result,
            revisions=revisions,
            critique_summary=critique.issues[0] if critique.issues else "",
        )

    def _call_llm(self, system: str, user: str) -> list[ExtractedShot]:
        response = self._llm.invoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
        raw = response.content if hasattr(response, "content") else str(response)
        raw = _strip_fences(raw)
        # 清除所有非法控制字符（包括未转义的换行 \n \r，JSON 字符串值内它们是非法的）
        raw = re.sub(r"[\x00-\x1f\x7f]", lambda m: " " if m.group() in "\n\r" else "", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # fallback：用 json-repair 修复后再解析
            try:
                from json_repair import repair_json
                data = json.loads(repair_json(raw))
            except Exception as exc2:
                snippet = raw[:300]
                raise ScreenwriterError(
                    f"Screenwriter JSON parse failed (even after repair): {exc2} | raw: {snippet}"
                ) from exc2
        try:
            if not isinstance(data, dict) or "shots" not in data:
                snippet = raw[:300]
                raise ScreenwriterError(f"Screenwriter JSON missing shots field: {snippet}")
            shots_data = data.get("shots", [])
            return [ExtractedShot.model_validate(s) for s in shots_data]

        except Exception as exc:
            snippet = raw[:300]
            raise ScreenwriterError(
                f"Screenwriter JSON parse failed: {exc} | raw: {snippet}"
            ) from exc

    def _critique_shots(
        self,
        scene_text: str,
        shots: list[ExtractedShot],
        entities_text: str,
    ) -> ScreenwritingCritique:
        shots_json = json.dumps([s.model_dump() for s in shots], ensure_ascii=False, indent=2)
        system = _CRITIQUE_SYSTEM_TEMPLATE.format(
            relevant_entities=entities_text,
            scene_text=scene_text[:2000],
            shots_json=shots_json,
        )
        response = self._critic_llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content="请检查上述 Shot 列表。"),
        ])
        raw = response.content if hasattr(response, "content") else str(response)
        raw = _strip_fences(raw)
        raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw)
        try:
            data = json.loads(raw)
            return ScreenwritingCritique.model_validate(data)
        except Exception:
            return ScreenwritingCritique(ok=True, severity="none", issues=[])

    def _revise_with_feedback(
        self,
        current_shots: list[ExtractedShot],
        critique: ScreenwritingCritique,
        system: str,
        user: str,
        entities_text: str,
    ) -> list[ExtractedShot]:
        revision_system = f"{system}\n\n## 反思意见（必须修正）\n" + "\n".join(critique.issues)
        return self._call_llm(revision_system, user)


def call_screenwriter(
    scene_text: str,
    *,
    scene_idx: int,
    scene_id: str,
    time: str = "",
    location: str = "",
    pov: str = "",
    relevant_entities: list[Entity] | None = None,
    rolling_summary: str = "",
    style_guide: str = "",
    llm: Any | None = None,
) -> ScreenwritingResult:
    """顶层 API：调用 Screenwriter。"""
    agent = ScreenwriterAgent(llm=llm)
    scene_meta = format_scene_meta(scene_idx, scene_id, time, location, pov)
    return agent.generate_shots(
        scene_text,
        scene_meta=scene_meta,
        relevant_entities=relevant_entities or [],
        rolling_summary=rolling_summary,
        style_guide=style_guide,
    )
