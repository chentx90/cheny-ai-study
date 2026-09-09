"""S1 Segmenter Agent。

职责边界（设计原则）：
  - LLM 只产出「段落编号」（整数索引），绝不输出原文文字。
  - Python 负责从段落偏移表解析字符偏移并执行精确切分（治坑③）。
  - 本模块只做切分，不理解内容语义（单一职责）。

原方案修正说明（anchor 字符串 → para_label 整数）：
  旧方案要求 LLM 逐字复制原文作为 anchor，在无章节标记的长文中 LLM
  会"转述"而非"引用"，导致 anchor 无法命中。
  新方案：Python 先把原文抽成带序号的段落采样表，LLM 只从表中选编号，
  彻底消除幻觉来源。
"""

from __future__ import annotations

import json
import re
import uuid
import warnings
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from manga_manager.llm.client import get_llm
from manga_manager.models import Episode, RawSpan, Scene, StrictModel


# ---------------------------------------------------------------------------
# Fence stripping（部分 provider 仍在 json_mode 下包裹 markdown）
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.MULTILINE)
_HTML_ANCHOR_ONLY_RE = re.compile(r'^(<a\s[^>]*></a>\s*)+$', re.IGNORECASE)


def _strip_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw).strip()


# ---------------------------------------------------------------------------
# 段落采样表：핵심 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ParaSample:
    """段落采样条目，label 是 LLM 可用的整数编号。"""

    label: int       # LLM 可引用的序号（0-based，连续）
    char_offset: int # 在原文（或子文本）中的字符偏移
    preview: str     # 展示给 LLM 的前 ~45 字预览


def _is_meaningful_line(line: str) -> bool:
    """过滤空行与纯 HTML anchor 行（如 <a name="epubfile5"></a>）。"""
    stripped = line.strip()
    if not stripped:
        return False
    if _HTML_ANCHOR_ONLY_RE.match(stripped):
        return False
    return True


def extract_para_samples(
    text: str,
    max_shown: int = 400,
    offset_base: int = 0,
    preview_chars: int = 45,
) -> list[ParaSample]:
    """从 text 中提取段落采样表。

    Args:
        text:         源文本（可以是全文或某一集的子文本）
        max_shown:    最多采样多少个段落展示给 LLM
        offset_base:  text 在全文中的起始偏移（用于场景级调用）
        preview_chars: 每条预览截取字符数

    Returns:
        list[ParaSample]，label 从 0 连续编号，char_offset 为绝对偏移。
    """
    # Step 1: 收集所有有意义段落的 (raw_offset, first_N_chars)
    all_paras: list[tuple[int, str]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        if _is_meaningful_line(line):
            clean = line.strip()
            # 去掉行内 HTML 标签后取预览
            clean_no_html = re.sub(r'<[^>]+>', '', clean)
            all_paras.append((pos, clean_no_html[:preview_chars]))
        pos += len(line)

    if not all_paras:
        return []

    # Step 2: 均匀采样
    n = len(all_paras)
    if n <= max_shown:
        indices = list(range(n))
    else:
        # 均匀步长，确保始终包含第 0 和最后一个
        step = (n - 1) / (max_shown - 1)
        indices = sorted(set(
            [0] + [round(i * step) for i in range(1, max_shown - 1)] + [n - 1]
        ))
        indices = indices[:max_shown]

    samples: list[ParaSample] = []
    for label, full_idx in enumerate(indices):
        raw_off, preview = all_paras[full_idx]
        samples.append(ParaSample(
            label=label,
            char_offset=offset_base + raw_off,
            preview=preview,
        ))
    return samples


def format_para_list(samples: list[ParaSample], title: str = "段落采样表") -> str:
    """格式化段落表为 LLM prompt 片段。"""
    lines = [f"{title}（共 {len(samples)} 条，编号 0–{len(samples)-1}）："]
    for s in samples:
        lines.append(f"  {s.label:4d}: {s.preview}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 内部 schema：LLM 输出的切点描述（仅含整数编号）
# ---------------------------------------------------------------------------


class EpisodeCut(StrictModel):
    idx: int = Field(ge=0, description="0-based episode index")
    title: str = Field(description="集标题，例如「第1集 - 幼年」")
    para_label: int = Field(ge=0, description="该集在段落采样表中的起始编号")


class EpisodeCuts(StrictModel):
    episodes: list[EpisodeCut] = Field(min_length=1)


class SceneCut(StrictModel):
    idx: int = Field(ge=0, description="0-based scene index within episode")
    para_label: int = Field(ge=0, description="该场景在集内段落采样表中的起始编号")
    time: str = Field(default="", description="时间（如「黄昏」）")
    location: str = Field(default="", description="地点（如「山路」）")
    pov: str = Field(default="", description="视点角色")
    summary: str = Field(default="", description="一句话场景摘要，不超过 50 字")


class SceneCuts(StrictModel):
    scenes: list[SceneCut] = Field(min_length=1)


# ---------------------------------------------------------------------------
# 错误类型
# ---------------------------------------------------------------------------


class SegmenterError(RuntimeError):
    """切分失败：para_label 越界、LLM 解析失败等。"""


# ---------------------------------------------------------------------------
# 工具函数（保留，用于 s1_segment 外部校验及测试）
# ---------------------------------------------------------------------------


def resolve_anchors_to_spans(
    text: str,
    anchors: list[str],
    text_start_offset: int = 0,
) -> list[tuple[int, int]]:
    """将有序锚定串列表解析为 (start, end) 绝对偏移列表（保留供外部/测试用）。

    搜索策略：单调扫描，每个 anchor 从上一个命中位置之后开始查找。
    """
    offsets: list[int] = []
    search_from = 0
    for anchor in anchors:
        idx = text.find(anchor, search_from)
        if idx == -1:
            raise SegmenterError(
                f"Anchor not found in source (search_from={search_from}): {anchor!r}"
            )
        offsets.append(idx)
        search_from = idx + len(anchor)

    spans: list[tuple[int, int]] = []
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(text)
        spans.append((text_start_offset + start, text_start_offset + end))
    return spans


def resolve_para_labels_to_spans(
    samples: list[ParaSample],
    labels: list[int],
    text_end_offset: int,
) -> list[tuple[int, int]]:
    """将有序段落编号列表解析为 (start, end) 绝对偏移 span 列表。

    Args:
        samples:         全部采样条目（按 label 有序）
        labels:          LLM 返回的 para_label 列表（有序，长度 = 切分段数）
        text_end_offset: 对应文本的结束绝对偏移（最后一段的 end）
    """
    by_label = {s.label: s for s in samples}
    for lbl in labels:
        if lbl not in by_label:
            raise SegmenterError(
                f"para_label {lbl} not in samples (valid range 0–{len(samples)-1})"
            )
    offsets = [by_label[lbl].char_offset for lbl in labels]
    spans: list[tuple[int, int]] = []
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else text_end_offset
        spans.append((start, end))
    return spans


# ---------------------------------------------------------------------------
# LLM 调用：集切点
# ---------------------------------------------------------------------------

_EPISODE_SYSTEM_PROMPT = """\
你是「切分 Agent」（Segmenter）。
你的唯一职责：根据段落采样表，识别原文中各集（Episode/章）的起始段落，以 JSON 格式输出编号。

严格规则：
1. 每集的 para_label 必须是段落采样表中实际存在的编号（整数）。
2. para_label 必须严格递增（后一集 > 前一集）。
3. 第 0 集的 para_label 必须为 0（从文本开头开始）。
4. idx 从 0 开始，连续无间隔。
5. 只输出 JSON，不输出任何解释文字。

输出 schema：
{
  "episodes": [
    {"idx": 0, "title": "集标题", "para_label": 0},
    {"idx": 1, "title": "集标题", "para_label": 12},
    ...
  ]
}"""


def _call_episode_segmenter(
    source: str,
    target_episodes: int,
    llm: Any,
    max_shown: int = 400,
) -> tuple[EpisodeCuts, list[ParaSample]]:
    """调用 LLM 识别集切点，返回 (EpisodeCuts, para_samples)。"""
    samples = extract_para_samples(source, max_shown=max_shown)
    if not samples:
        raise SegmenterError("Source text has no meaningful paragraphs")

    para_table = format_para_list(samples, "全文段落采样表")
    user_content = (
        f"请将以下原文切分为约 {target_episodes} 集（按叙事自然段落/情感阶段划分）。\n"
        f"原文总长度：{len(source)} 字，段落采样表共 {len(samples)} 条。\n\n"
        f"{para_table}\n\n"
        f"请根据上方段落采样表，选择各集起始段落编号（para_label），"
        f"第 0 集必须从 para_label=0 开始。"
    )

    response = llm.invoke(
        [SystemMessage(content=_EPISODE_SYSTEM_PROMPT), HumanMessage(content=user_content)]
    )
    raw = response.content if hasattr(response, "content") else str(response)
    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
        return EpisodeCuts.model_validate(data), samples
    except Exception as exc:
        snippet = raw[:300].replace("\n", " ")
        raise SegmenterError(
            f"Episode cuts JSON parse failed: {exc} | raw_prefix: {snippet}"
        ) from exc


# ---------------------------------------------------------------------------
# LLM 调用：场景切点（逐集）
# ---------------------------------------------------------------------------

_SCENE_SYSTEM_PROMPT = """\
你是「切分 Agent」（Segmenter）。
你的唯一职责：根据集内段落采样表，识别该集中各场景（Scene）的起始段落，以 JSON 格式输出编号。

场景边界信号：时间跳转、地点转换、视角切换、情绪断层、明显场景分隔。

严格规则：
1. 每个场景的 para_label 必须是集内段落采样表中实际存在的编号（整数）。
2. para_label 必须严格递增。
3. 第 0 个场景的 para_label 必须为 0（从集开头开始）。
4. idx 从 0 开始，连续无间隔。
5. 只输出 JSON，不输出任何解释文字。

输出 schema：
{
  "scenes": [
    {"idx": 0, "para_label": 0, "time": "时间", "location": "地点", "pov": "视点", "summary": "摘要（≤50字）"},
    ...
  ]
}"""


def _call_scene_segmenter(
    episode_text: str,
    episode_idx: int,
    ep_start: int,
    llm: Any,
    max_shown: int = 300,
) -> tuple[SceneCuts, list[ParaSample]]:
    """调用 LLM 识别单集内的场景切点，返回 (SceneCuts, ep_para_samples)。"""
    ep_samples = extract_para_samples(
        episode_text, max_shown=max_shown, offset_base=ep_start
    )
    if not ep_samples:
        raise SegmenterError(f"Episode {episode_idx} has no meaningful paragraphs")

    para_table = format_para_list(ep_samples, f"第{episode_idx}集段落采样表")
    user_content = (
        f"请将以下第 {episode_idx} 集文本切分场景（按叙事边界划分）。\n"
        f"集文本长度：{len(episode_text)} 字，段落采样表共 {len(ep_samples)} 条。\n\n"
        f"{para_table}\n\n"
        f"请根据上方段落采样表，选择各场景起始段落编号（para_label），"
        f"第 0 个场景必须从 para_label=0 开始。"
    )

    response = llm.invoke(
        [SystemMessage(content=_SCENE_SYSTEM_PROMPT), HumanMessage(content=user_content)]
    )
    raw = response.content if hasattr(response, "content") else str(response)
    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
        return SceneCuts.model_validate(data), ep_samples
    except Exception as exc:
        snippet = raw[:300].replace("\n", " ")
        raise SegmenterError(
            f"Scene cuts JSON parse failed (ep={episode_idx}): {exc} | raw_prefix: {snippet}"
        ) from exc


# ---------------------------------------------------------------------------
# 主入口：将原文切分为 Episode + Scene 列表
# ---------------------------------------------------------------------------


def segment_source(
    source: str,
    *,
    work_id: str = "",
    target_episodes: int = 12,
    llm: Any | None = None,
    max_shown_global: int = 400,
    max_shown_episode: int = 300,
) -> list[Episode]:
    """端到端切分：调用 LLM 获取段落编号，Python 查表解析偏移，返回 Episode 列表（附 scenes）。

    不写磁盘，只返回结构体。调用方（pipeline）决定是否落盘。
    """
    _llm = llm or get_llm(json_mode=True)

    # ── Step 1: 集切点 ──────────────────────────────────────────────────────
    ep_cuts, ep_samples = _call_episode_segmenter(
        source, target_episodes, _llm, max_shown=max_shown_global
    )

    ep_labels = [cut.para_label for cut in ep_cuts.episodes]

    # 校验 para_label 严格递增
    for i in range(1, len(ep_labels)):
        if ep_labels[i] <= ep_labels[i - 1]:
            raise SegmenterError(
                f"Episode para_labels not strictly increasing: "
                f"ep[{i-1}].para_label={ep_labels[i-1]}, ep[{i}].para_label={ep_labels[i]}"
            )

    ep_spans = resolve_para_labels_to_spans(ep_samples, ep_labels, len(source))

    # 边界对齐：强制首集从 0 开始、末集到 len(source) 结束
    # （源文件开头/末尾可能有空行，para_label=0 的 offset 可能是 2 而非 0）
    if ep_spans:
        ep_spans[0] = (0, ep_spans[0][1])
        ep_spans[-1] = (ep_spans[-1][0], len(source))

    # ── Step 2: 逐集场景切点 ─────────────────────────────────────────────────
    episodes: list[Episode] = []
    for cut, (ep_start, ep_end) in zip(ep_cuts.episodes, ep_spans):
        ep_text = source[ep_start:ep_end]

        sc_cuts, sc_samples = _call_scene_segmenter(
            ep_text, cut.idx, ep_start, _llm, max_shown=max_shown_episode
        )

        sc_labels = [sc.para_label for sc in sc_cuts.scenes]

        # 校验场景 para_label 严格递增
        for i in range(1, len(sc_labels)):
            if sc_labels[i] <= sc_labels[i - 1]:
                raise SegmenterError(
                    f"Scene para_labels (ep={cut.idx}) not strictly increasing: "
                    f"sc[{i-1}].para_label={sc_labels[i-1]}, sc[{i}].para_label={sc_labels[i]}"
                )

        sc_spans = resolve_para_labels_to_spans(sc_samples, sc_labels, ep_end)

        # 边界对齐：强制首场景从 ep_start 开始、末场景到 ep_end 结束
        if sc_spans:
            sc_spans[0] = (ep_start, sc_spans[0][1])
            sc_spans[-1] = (sc_spans[-1][0], ep_end)

        scenes: list[Scene] = []
        for sc_cut, (sc_start, sc_end) in zip(sc_cuts.scenes, sc_spans):
            scene_id = f"s{cut.idx:02d}{sc_cut.idx:03d}_{uuid.uuid4().hex[:4]}"
            scenes.append(
                Scene(
                    id=scene_id,
                    episode_idx=cut.idx,
                    idx=sc_cut.idx,
                    time=sc_cut.time,
                    location=sc_cut.location,
                    pov=sc_cut.pov,
                    summary=sc_cut.summary,
                    raw_span=RawSpan(start=sc_start, end=sc_end),
                )
            )

        ep_id = f"ep{cut.idx:04d}_{uuid.uuid4().hex[:4]}"
        episodes.append(
            Episode(
                id=ep_id,
                idx=cut.idx,
                title=cut.title,
                raw_span=RawSpan(start=ep_start, end=ep_end),
                scenes=scenes,
            )
        )

    return episodes
