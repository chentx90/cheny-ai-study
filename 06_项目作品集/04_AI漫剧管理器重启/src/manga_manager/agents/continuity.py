"""S5 Continuity/绑定 Agent。

职责边界（设计原则）：
  - 纯确定性匹配：把 Shot.characters 中的角色称呼 → entity_id + variant_label
  - 不做 LLM 调用（保持成本/延迟可预测；必要时未来扩展 LLM 辅助）
  - 通过 WorkIndex（entity_name_to_id / alias_to_id）解析角色称呼
  - 对 character 类型实体，尝试从 scene.time 提取年龄，匹配 variant

核心算法：
  1. 对每个 Scene 的 Shot.characters 遍历
  2. character_key → (entity_id, variant_label)
     - entity_id: index.entity_name_to_id 或 alias_to_id 查找
     - variant_label: 从 scene.time 提取年龄数字 → 匹配 variant.time_desc
  3. 生成 ShotEntityBinding 列表
  4. 生成 BindingFile（shot_id → [BindingItem]）
  5. 跨场景一致性检查：收集每个 entity_id 的所有 variant_label，若 >1 个不同值报 issue

输出：
  - 更新 Shot.matched_entities
  - 写 binding/{scene_id}.json
  - 汇总 issues 给 Critic/L3
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from manga_manager.models import (
    BindingFile,
    BindingItem,
    Entity,
    Scene,
    Shot,
    ShotEntityBinding,
    WorkIndex,
)

# 年龄匹配正则：10岁，十五岁，15-20岁
_AGE_RE = re.compile(r"(\d+|[一二三四五六七八九十百]+)\s*岁")

# 中数 → 数字映射
_CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "二十": 20, "三十": 30, "四十": 40, "五十": 50,
    "六十": 60, "七十": 70, "八十": 80, "九十": 90, "百": 100,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19,
    "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24, "二十五": 25,
    "二十六": 26, "二十七": 27, "二十八": 28, "二十九": 29,
    "三十一": 31, "三十二": 32, "三十三": 33, "三十四": 34, "三十五": 35,
    "三十六": 36, "三十七": 37, "三十八": 38, "三十九": 39,
}


def extract_ages(scene_time: str) -> list[int]:
    """从 scene.time 提取年龄数字。"""
    if not scene_time:
        return []
    ages: list[int] = []
    for m in _AGE_RE.finditer(scene_time):
        s = m.group(1)
        if s.isdigit():
            ages.append(int(s))
        elif s in _CN_NUM:
            ages.append(_CN_NUM[s])
        elif "十" in s:
            # 处理如"三十"
            parts = s.split("十")
            if len(parts) == 2:
                tens = _CN_NUM.get(parts[0], 0) if parts[0] else 1
                ones = _CN_NUM.get(parts[1], 0) if parts[1] else 0
                ages.append(tens * 10 + ones)
    return ages


def match_variant_for_age(
    entity: Entity, age: int | None = None
) -> tuple[str, float]:
    """匹配 variant_label，返回 (label, confidence)。

    优先级：
      1. age 不为空时，优先匹配 variant.time_desc 中含 age 数字的
      2. 兜底：返回 entity 第一个 variant 或 ("", 0)
    """
    if not entity.variants:
        return "", 0.0

    if age is not None:
        for v in entity.variants:
            # 从 time_desc 提取数字
            nums = re.findall(r"\d+", v.time_desc)
            if nums:
                # 如果 time_desc 是区间如 "10-20岁"，年龄是否在区间内
                if len(nums) == 2:
                    low, high = int(nums[0]), int(nums[1])
                    if low <= age <= high:
                        return v.label, 1.0
                else:
                    if int(nums[0]) == age:
                        return v.label, 1.0

    # 兜底返回第一个 variant
    return entity.variants[0].label, 0.3


def resolve_character_key(
    character_key: str, index: WorkIndex
) -> str | None:
    """把 Shot.characters 中的称呼解析为 entity_id。"""
    key = character_key.strip()
    if not key:
        return None
    found = index.entity_name_to_id.get(key)
    if found:
        return found
    return index.alias_to_id.get(key)


def resolve_character_key_with_variant(
    character_key: str,
    index: WorkIndex,
    entities_by_id: dict[str, Entity],
) -> tuple[str | None, str]:
    """解析角色称呼，并保留精确 variant_label。"""
    key = character_key.strip()
    entity_id = resolve_character_key(key, index)
    variant_label = ""

    if entity_id:
        entity = entities_by_id.get(entity_id)
        if entity and any(v.label == key for v in entity.variants):
            variant_label = key
        return entity_id, variant_label

    for entity in entities_by_id.values():
        for variant in entity.variants:
            if variant.label == key:
                return entity.id, variant.label

    return None, ""


def build_appearance_snapshot(entity: Entity, variant_label: str = "") -> str:
    """生成实体+变体的外观快照字符串（供 prompt 使用）。"""
    parts: list[str] = []
    for attr in entity.attrs:
        if attr.key in ("appearance", "hair", "clothes", "build"):
            parts.append(attr.value)
    for v in entity.variants:
        if v.label == variant_label and v.appearance:
            parts.insert(0, f"[{v.label}] {v.appearance}")
            break
    return "；".join(parts)


@dataclass
class ContinueResult:
    """单场景绑定结果。"""
    scene_id: str
    bindings: dict[str, list[BindingItem]]
    updated_shots: list[Shot]
    issues: list[str] = field(default_factory=list)


def bind_scene(
    scene: Scene,
    shots: list[Shot],
    entities: list[Entity],
    index: WorkIndex,
) -> ContinueResult:
    """为单个场景做角色绑定。"""

    entities_by_id = {e.id: e for e in entities}
    scene_ages = extract_ages(scene.time)
    binding_map: dict[str, list[BindingItem]] = {}
    updated_shots: list[Shot] = []
    issues: list[str] = []

    for shot in shots:
        if shot.scene_id != scene.id:
            continue

        shot_bindings: list[BindingItem] = []
        matched: list[ShotEntityBinding] = []

        seen_entity_ids: set[str] = set()
        for key in shot.characters:
            entity_id, variant_label_override = resolve_character_key_with_variant(
                key, index, entities_by_id
            )
            if not entity_id:
                issues.append(f"shot {shot.id}: 无法解析角色'{key}'")
                continue
            if entity_id in seen_entity_ids:
                continue
            seen_entity_ids.add(entity_id)

            entity = entities_by_id.get(entity_id)
            if not entity:
                issues.append(f"shot {shot.id}: 实体{entity_id}不存在")
                continue

            variant_label = variant_label_override
            confidence = 1.0 if variant_label_override else 0.0
            if entity.type == "character" and not variant_label:
                age = scene_ages[0] if scene_ages else None
                variant_label, confidence = match_variant_for_age(entity, age)

            appearance = build_appearance_snapshot(entity, variant_label)
            shot_bindings.append(
                BindingItem(
                    entity_id=entity_id,
                    role="present",
                    variant_label=variant_label,
                    appearance_snapshot=appearance,
                    confidence=confidence,
                )
            )
            matched.append(
                ShotEntityBinding(
                    character_key=key,
                    entity_id=entity_id,
                    variant_label=variant_label,
                    confidence=confidence,
                )
            )

        binding_map[shot.id] = shot_bindings

        # 更新 shot
        model_dump = shot.model_dump()
        model_dump["matched_entities"] = [m.model_dump() for m in matched]
        updated_shots.append(Shot.model_validate(model_dump))

    return ContinueResult(
        scene_id=scene.id,
        bindings=binding_map,
        updated_shots=updated_shots,
        issues=issues,
    )


def check_cross_scene_consistency(
    scene_bindings: list[ContinueResult],
) -> list[str]:
    """跨场景一致性检查。

    检查同一 entity_id 在不同场景中是否绑定了多个不同的 variant_label。
    """
    entity_to_variants: dict[str, dict[str, list[str]]] = {}
    for res in scene_bindings:
        for shot_id, items in res.bindings.items():
            for item in items:
                if item.variant_label:
                    entity_to_variants.setdefault(item.entity_id, {})
                    entity_to_variants[item.entity_id].setdefault(item.variant_label, [])
                    entity_to_variants[item.entity_id][item.variant_label].append(
                        f"{res.scene_id}/{shot_id}"
                    )

    issues: list[str] = []
    for entity_id, variant_map in entity_to_variants.items():
        if len(variant_map) > 1:
            # 同一实体用了多个 variant
            details = " | ".join(
                f"{v}({len(locs)}镜头)" for v, locs in variant_map.items()
            )
            issues.append(f"实体{entity_id}出现多个变体: {details}")

    return issues
