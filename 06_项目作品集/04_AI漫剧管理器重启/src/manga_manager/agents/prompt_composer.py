"""M6 视频提示词生成 Agent (PromptComposer)。

职责边界：
  - 输入：场景元数据 + 该场景原文片段 + shots（含 matched_entities）+ 实体库 + style_contract
  - 输出：符合三段式格式的视频提示词文本（≤15s/段）
  - 每个场景拆成多张"卡片"（segment），卡片间用 --- 分隔

输出格式（每张卡片）：
  {scene_id}_{N:02d}

  {第一行：声音/运镜基调，动态生成}
  {第二行：场景定制视觉风格，动态生成}

  [声音角色物品场景锚定]|参考人物【角色名·变体】: @锚定名｜...

  [0.0-X.Xs]|切画面：
  【机位】...
  【场景】...
  【光影】...
  【动作链】先 @锚定名 ...，随后 ...，最后 ...
  【运镜】...
  【台词】角色名——"台词" 或 无（环境音——具体声音）

  {negative_prompt 直接拼接}

调节点：
  系统提示词模板：本文件 _SYSTEM_PROMPT_TEMPLATE
  风格背景+违禁词：config.toml [video_prompt] style_contract（注入系统提示词，不进入输出）
  直接拼接后缀：style_guide.json negative_prompt 字段（每张卡片末尾追加）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from manga_manager.config import load_config
from manga_manager.llm.client import get_llm
from manga_manager.models import Entity, Scene, Shot

# ────────────────────────────────────────────────────────────────────────────
# 系统提示词模板（{style_contract} 运行时注入）
# ────────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT_TEMPLATE = """\
你是「即梦2.0视频提示词专家」，将场景分镜数据转写为结构化视频生成提示词。

## 项目风格背景（只读参考，不直接输出原文，须体现在你生成的两行风格描述中）

{style_contract}

========================================

## 原文参考规则

- 输入中的 `source_text` 是该场景对应的原文片段，是角色称呼、人物关系、动作顺序和台词的最高优先级参考。
- 必须保留原文中的精确称呼，例如“幼年妹妹”“幼年妹”“国中生妹妹”“高中生妹妹”等，不得自行合并、改写、替换成泛称。
- 如果 `scene_meta`、`segments.characters` 与 `source_text` 不一致，以 `source_text` 为准修正理解，但输出仍使用结构化格式。
- `source_text` 只用于理解和锚定，不要整段复制到输出中。

========================================

## 输出格式（严格遵守，不添加任何额外标题、序号或解释文字）

多个镜头段（segment）之间用单独一行 --- 分隔。每段格式如下：

{{第一行}}一至两句话，概括本段的声音设计、运镜基调、语言（例：动画风格，有音效，无乐（极弱极简钢琴单音可作空气底色），无字幕，运镜克制丝滑，人物动作内敛写实，讲中文。）——须贴合本段情绪动态生成，不照搬示例。
{{第二行}}一至两句话，描述本段视觉风格与空间氛围（例：胶片纪实风极简主义动漫画风：中低饱和度复古胶片色调，画面带细腻微粒感。本段为……）——须结合本段具体场景、时段情绪动态生成。

【声音角色物品场景锚定】参考人物【角色名·变体】: @锚定名 ； 参考场景【地点名】: @地点名

【0.0-X.Xs】切画面：
【机位】景别（参考：大特写，特写，中景，全景，远景），拍摄角度（参考：地板仰拍，某人物过肩角度，高处45度俯拍等），光影光学补充（参考：大光圈浅景深，伦勃朗侧逆光等）
【场景】地点、天气、时间；人物朝向与相对位置
【光影】光源、色温、颗粒感、整体氛围
【动作链】先 锚定名 动作A，随后 动作B，最后 动作C
【运镜】默认固定镜头；有充分理由才用缓推/缓拉，极克制
【台词】角色名——"台词原文"（无对话写：无（环境音——{{具体声音描述}}））

【X.X-Y.Ys]】切画面：
（格式同上，时间接续上一镜）

========================================

## 时间规则

- 每段（卡片）时间从 0.0 开始，格式 [0.0-6.0s]，单位秒
- 时长数值由输入分镜数据决定，直接使用，不自行修改
- 不同段之间时间独立，每段重置为 0.0

## 其他规则

- 每段必须有 [声音角色物品场景锚定] 行；无实体时写"（无绑定实体）"
- 动作链三步递进：先→随后→最后，必须用 锚定名 引用角色/场景
- 台词写原文；无对话必须写环境音具体描述，不能只写"无"
- 动作链只描述画面中发生的事，不写运镜/光影/画风
- 只输出卡片正文，不输出序号、场景编号、解释或空白卡片
"""

# ────────────────────────────────────────────────────────────────────────────
# 数据结构
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class ShotSegment:
    """一段 ≤15s 的镜头组。"""
    start_time: float
    end_time: float
    shots: list[Shot] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class ScenePromptResult:
    """单场景的视频提示词生成结果。"""
    scene_id: str
    prompt_text: str       # 完整提示词（含所有卡片，卡片间 --- 分隔）
    segment_count: int     # 实际卡片数
    total_duration: float  # 场景总时长


# ────────────────────────────────────────────────────────────────────────────
# 分段逻辑（纯 Python，无 LLM）
# ────────────────────────────────────────────────────────────────────────────

def pack_shots_into_segments(
    shots: list[Shot], max_seconds: float = 15.0
) -> list[ShotSegment]:
    """将 shots 按 duration 贪心打包成 ≤max_seconds 的段。"""
    if not shots:
        return []
    segments: list[ShotSegment] = []
    cur_start = 0.0
    cur_shots: list[Shot] = []
    cur_dur = 0.0

    for shot in shots:
        d = max(shot.duration, 1.0)
        if cur_shots and cur_dur + d > max_seconds:
            segments.append(ShotSegment(cur_start, cur_start + cur_dur, cur_shots))
            cur_start += cur_dur
            cur_shots = []
            cur_dur = 0.0
        cur_shots.append(shot)
        cur_dur += d

    if cur_shots:
        segments.append(ShotSegment(cur_start, cur_start + cur_dur, cur_shots))

    return segments


# ────────────────────────────────────────────────────────────────────────────
# 实体锚定格式化
# ────────────────────────────────────────────────────────────────────────────

def build_entity_anchors(
    shots: list[Shot], entities_by_id: dict[str, Entity]
) -> dict[str, dict[str, str]]:
    """收集场景中出现的所有实体，返回 {entity_id: {anchor_name, appearance, ...}}。"""
    seen: dict[str, dict[str, str]] = {}
    for shot in shots:
        for me in shot.matched_entities:
            eid = me.entity_id
            if eid in seen:
                continue
            ent = entities_by_id.get(eid)
            if not ent:
                continue
            anchor_name = f"{ent.name}·{me.variant_label}" if me.variant_label else ent.name
            appearance = ""
            for v in ent.variants:
                if v.label == me.variant_label:
                    appearance = v.appearance
                    break
            if not appearance:
                for attr in ent.attrs:
                    if attr.key == "appearance":
                        appearance = attr.value
                        break
            seen[eid] = {
                "anchor_name": anchor_name,
                "appearance": appearance,
                "entity_type": ent.type,
                "name": ent.name,
                "variant_label": me.variant_label,
            }
    return seen


def format_anchor_block(entity_anchors: dict[str, dict[str, str]]) -> str:
    """格式化实体锚定行。"""
    chars = [v for v in entity_anchors.values() if v["entity_type"] == "character"]
    locs  = [v for v in entity_anchors.values() if v["entity_type"] == "location"]
    props = [v for v in entity_anchors.values() if v["entity_type"] == "prop"]

    parts: list[str] = []
    for c in chars:
        label = f"【{c['name']}·{c['variant_label']}】" if c["variant_label"] else f"【{c['name']}】"
        parts.append(f"参考人物{label}: @{c['anchor_name']}")
    for l in locs:
        parts.append(f"参考场景【{l['name']}】: @{l['name']}")
    for p in props:
        parts.append(f"参考道具【{p['name']}】: @{p['name']}")

    return "｜".join(parts) if parts else "（无绑定实体）"


# ────────────────────────────────────────────────────────────────────────────
# LLM 调用
# ────────────────────────────────────────────────────────────────────────────

def call_prompt_composer(
    scene: Scene,
    shots: list[Shot],
    entities_by_id: dict[str, Entity],
    *,
    style_contract: str,
    max_segment_duration: float = 15.0,
    negative_prompt: str = "",
    source_text: str = "",
    llm: Any | None = None,
) -> ScenePromptResult:
    """为一个场景生成完整视频提示词。"""
    _llm = llm or get_llm(json_mode=False, temperature=0.3)

    # 分段
    segments = pack_shots_into_segments(shots, max_seconds=max_segment_duration)
    total_dur = sum(s.duration for s in segments)

    # 实体锚定
    entity_anchors = build_entity_anchors(shots, entities_by_id)
    anchor_block = format_anchor_block(entity_anchors)

    # 构建系统提示词（注入 style_contract）
    system = _SYSTEM_PROMPT_TEMPLATE.format(style_contract=style_contract)

    # 构建用户消息：场景元数据 + 该场景原文片段 + 各段分镜数据（时间从0重置）
    seg_data = []
    for seg in segments:
        cur_time = 0.0
        shot_list = []
        for s in seg.shots:
            d = max(s.duration, 1.0)
            end_time = cur_time + d
            shot_list.append({
                "time_range": f"{cur_time:.1f}-{end_time:.1f}s",
                "shot_type": s.shot_type,
                "action": s.action,
                "emotion": s.emotion,
                "dialogue": s.dialogue,
                "characters": [
                    entity_anchors.get(me.entity_id, {}).get("anchor_name", me.character_key)
                    for me in s.matched_entities
                ],
            })
            cur_time = end_time
        seg_data.append({
            "total_duration_seconds": round(seg.duration, 1),
            "shots": shot_list,
        })

    user_msg = json.dumps(
        {
            "scene_meta": {
                "time": scene.time,
                "location": scene.location,
                "pov": scene.pov,
                "summary": scene.summary,
            },
            "source_text": source_text,
            "source_span": {
                "start": scene.raw_span.start,
                "end": scene.raw_span.end,
                "chars": len(source_text),
            },
            "entity_anchors": {
                v["anchor_name"]: {
                    "type": v["entity_type"],
                    "appearance": v["appearance"],
                }
                for v in entity_anchors.values()
            },
            "anchor_block": anchor_block,
            "segments": seg_data,
        },
        ensure_ascii=False,
        indent=2,
    )

    response = _llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=user_msg),
    ])
    raw = response.content if hasattr(response, "content") else str(response)
    raw = raw.strip()

    # 后处理：按 --- 分割卡片，加 scene_id 编号，追加 negative_prompt
    raw_cards = re.split(r"\n[ \t]*---[ \t]*\n", raw)
    cards: list[str] = []
    for idx, part in enumerate(raw_cards, 1):
        part = part.strip()
        if not part:
            continue
        header = f"{scene.id}_{idx:02d}"
        card = f"{header}\n\n{part}"
        if negative_prompt:
            card = f"{card}\n\n{negative_prompt}"
        cards.append(card)

    # 若 LLM 未产生分隔符（整体作为一张卡片）
    if not cards:
        card = f"{scene.id}_01\n\n{raw}"
        if negative_prompt:
            card = f"{card}\n\n{negative_prompt}"
        cards = [card]

    prompt_text = "\n\n---\n\n".join(cards)

    return ScenePromptResult(
        scene_id=scene.id,
        prompt_text=prompt_text,
        segment_count=len(cards),
        total_duration=total_dur,
    )


# ────────────────────────────────────────────────────────────────────────────
# 配置读取
# ────────────────────────────────────────────────────────────────────────────

def get_video_prompt_config() -> tuple[str, float]:
    """从 config.toml 读取 style_contract 和 max_segment_duration。"""
    cfg = load_config().get("video_prompt", {})
    style = cfg.get(
        "style_contract",
        "胶片纪实风极简主义动漫，中低饱和度复古胶片色调，固定长镜头，克制运镜，极简主义钢琴氛围音乐。",
    )
    max_dur = float(cfg.get("max_segment_duration", 15.0))
    return style, max_dur
