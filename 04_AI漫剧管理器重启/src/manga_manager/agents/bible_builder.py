"""S2 BibleBuilder Agent。

职责边界（设计原则）：
  - 只提取反复出现或对剧情有重要价值的实体（人物/地点/道具）。
  - 一次性提及的背景物品、路人角色不提取。
  - 人物角色按年龄阶段生成 variant（外观变体），用于后续视频生成的一致性。
  - LLM 输出 schema 化的 ExtractedEntity 列表，不直接操作存储。
  - 去重合并、index 维护由 pipeline/s2_bible.py 的 Python 逻辑负责。

核心数据结构（BibleExtraction）：
  entities: list[ExtractedEntity]
    每个 ExtractedEntity 含:
      - existing_id: str | None
          - 非空 = 该实体在已知库中存在，后续 Python 合并属性至该 id
          - None = 全新实体，后续 Python 创建新 Entity 记录
      - name / aliases / type / importance / attrs
      - variants: list[ExtractedVariant]  # 角色年龄变体
  relations: list[ExtractedRelation]
    用文本中的称呼（subject_name / object_name），Python 负责映射为 entity_id。
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


def _strip_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw).strip()


class ExtractedVariant(StrictModel):
    label: str = Field(description="变体标签，如'幼年哥哥'或'成年妹妹'")
    time_desc: str = Field(default="", description="生效时间描述，如'0-10岁''第5集后'")
    appearance: str = Field(description="外观描述：发型、服装、体型、气质，用于视频生成绑定")


class ExtractedAttr(StrictModel):
    key: str
    value: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ExtractedEntity(StrictModel):
    existing_id: str | None = Field(
        default=None,
        description="已知实体的 id（若为本场景中出现的已知实体别名）；新实体则为 null",
    )
    name: str = Field(description="本场景中该实体的主要称呼")
    type: str = Field(description="character | location | prop")
    importance: str = Field(default="minor", description="major | minor")
    aliases: list[str] = Field(default_factory=list, description="本场景中出现的该实体其他称呼")
    attrs: list[ExtractedAttr] = Field(default_factory=list, description="从文本读取的属性")
    variants: list[ExtractedVariant] = Field(
        default_factory=list,
        description="仅 character 类型需要：当角色有不同年龄/状态时，描述各变体外观",
    )
    appeared_before: bool = Field(
        default=False,
        description="该实体之前是否出现过（对已知库中已存在的为 true，全新实体为 false）",
    )


class ExtractedRelation(StrictModel):
    subject_name: str = Field(description="关系主体在本场景中的称呼")
    object_name: str = Field(description="关系客体在本场景中的称呼")
    relation: str = Field(description="关系描述，如'兄妹'、'师生'、'同事'")


class BibleExtraction(StrictModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


class BibleBuilderError(RuntimeError):
    pass


def format_known_entities(entities: list[Entity], max_display: int = 100) -> str:
    """格式化已知实体摘要给 LLM，major 优先，含变体信息。"""
    if not entities:
        return "（库为空，尚无已知实体）"

    major_first = sorted(entities, key=lambda e: (e.importance != "major", e.name))
    shown = major_first[:max_display]
    lines = []
    for ent in shown:
        aliases_str = ", ".join(ent.aliases[:3]) if ent.aliases else "—"
        variants_str = ""
        if ent.variants:
            vnames = ", ".join(v.label for v in ent.variants[:3])
            variants_str = f" | variants=[{vnames}]"
        lines.append(
            f"  {ent.id} | {ent.type} | {ent.name} "
            f"| aliases=[{aliases_str}] | {ent.importance}{variants_str}"
        )
    if len(entities) > max_display:
        lines.append(f"  ...（共 {len(entities)} 个，仅展示前 {max_display} 个，major 优先）")
    return "\n".join(lines)


_BIBLE_SYSTEM_TEMPLATE = """\
你是「设定库 Agent」（BibleBuilder）。
你的职责：从场景文本中只提取**反复出现**的实体（人物/地点/道具）和角色关系。

提取目的是做视频生成时的外观绑定，保证角色/场景/重要道具的一致性。

已知实体库（id / type / name / aliases / importance）：
{known_entities}

提取规则（严格遵守）：
1. 只提取以下实体：
   - character: 有名字的角色（主角、配角），跨场景反复出现
   - location: 反复出现的主要地点（如"家"、"学校"、"阳台"）
   - prop: 对剧情有重要意义且反复出现的道具（如"绘图日记"）。
   不要提取：一次性物品、路人、背景中的物品、只在对话中提一嘴的人或物。
2. 如果实体已在已知库中，输出对应 existing_id；否则 null。
3. 对 character 类型，判断本场景是否有年龄/外貌变化：
   - 如果有年龄变化（如"3岁哥哥"、"大学生妹妹"），在 variants 中描述该状态外观
   - 外观描述应包含：发型、服装、体型、气质，用于视频生成
   - 如果没有年龄变化，variants 可为空
4. importance：
   - "major" = 主角或关键配角（反复出现、影响主线）
   - "minor" = 重要地点、重要道具、次要配角
5. attrs 只提取外观和稳定属性，不要提取情绪或状态信息。
6. relations 只提 character↔character，用本场景中的称呼。
7. 如果本场景没有值得提取的实体，返回空列表。

只输出 JSON，不输出任何解释文字。

输出 schema:
{{
  "entities": [
    {{
      "existing_id": null,
      "name": "妹妹",
      "type": "character",
      "importance": "major",
      "aliases": ["阿月"],
      "attrs": [{{"key": "hair", "value": "黑色长发", "confidence": 0.9}}],
      "variants": [
        {{
          "label": "幼年妹妹",
          "time_desc": "0-10岁",
          "appearance": "短发的小女孩，穿幼儿园制服，圆脸"
        }}
      ],
      "appeared_before": false
    }}
  ],
  "relations": [
    {{"subject_name": "哥哥", "object_name": "妹妹", "relation": "兄妹"}}
  ]
}}"""


def _build_prompt(
    scene_text: str,
    scene_meta: dict[str, str],
    entities: list[Entity],
) -> tuple[str, str]:
    known = format_known_entities(entities)
    system = _BIBLE_SYSTEM_TEMPLATE.format(known_entities=known)
    meta_parts = [f"{k}={v}" for k, v in scene_meta.items() if v]
    meta_str = " / ".join(meta_parts) or "—"
    user = (
        f"场景信息：{meta_str}\n"
        f"场景原文（{len(scene_text)} 字）：\n{scene_text}"
    )
    return system, user


def call_bible_builder(
    scene_text: str,
    *,
    scene_meta: dict[str, str],
    existing_entities: list[Entity],
    llm: Any | None = None,
) -> BibleExtraction:
    _llm = llm or get_llm(json_mode=True)
    system, user = _build_prompt(scene_text, scene_meta, existing_entities)
    response = _llm.invoke(
        [SystemMessage(content=system), HumanMessage(content=user)]
    )
    raw = response.content if hasattr(response, "content") else str(response)
    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
        return BibleExtraction.model_validate(data)
    except Exception as exc:
        snippet = raw[:300].replace("\n", " ")
        raise BibleBuilderError(
            f"BibleBuilder JSON parse failed: {exc} | raw_prefix: {snippet}"
        ) from exc
