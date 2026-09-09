"""S3 Summarizer Agent。

职责边界（设计原则）：
  - 为每集生成 episode_summary（从场景原文压缩）。
  - 把 episode_summary 与上一集的 rolling_summary 合并，产出新的 rolling_summary。
  - rolling_summary 是"截至本集"的前情提要，让下游 S4/S5/S6 不需要全部历史。
  - LLM 输出受 schema 约束；Python 侧做 token 估算和字数校验。

核心数据结构（SummarizerResult）：
  episode_summary : str - 本集摘要（~800 字）
  rolling_summary : str - 截至本集的滚动摘要（~1500 字 max）
  token_estimate    : int - rolling_summary 的 token 估算
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from manga_manager.context import estimate_tokens
from manga_manager.llm.client import get_llm
from manga_manager.models import Episode, Scene, StrictModel

_EPISODE_SUMMARY_MAX_CHARS = 1200
_ROLLING_SUMMARY_MAX_CHARS = 2000
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _strip_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw).strip()


class SummarizerResult(StrictModel):
    episode_summary: str = Field(
        description=f"本集摘要，最多 {_EPISODE_SUMMARY_MAX_CHARS} 字",
    )
    rolling_summary: str = Field(
        description=f"截至本集的滚动摘要（前情提要），包含历史 + 本集；最多 {_ROLLING_SUMMARY_MAX_CHARS} 字",
    )


class SummarizerError(RuntimeError):
    pass


def format_scene_text(
    scenes: list[Scene],
    source: str,
    max_chars_per_scene: int = 8000,
) -> str:
    """把一集所有场景的原文拼成 LLM 输入。

    单场景超过 max_chars_per_scene 时截断（避免爆 token）。
    """
    parts: list[str] = []
    for scene in scenes:
        text = source[scene.raw_span.start:scene.raw_span.end]
        if len(text) > max_chars_per_scene:
            text = text[:max_chars_per_scene] + "\n[…… 截断 ……]"
        meta_bits = [f"id={scene.id}", f"idx={scene.idx}"]
        if scene.time:
            meta_bits.append(f"time={scene.time}")
        if scene.location:
            meta_bits.append(f"location={scene.location}")
        if scene.pov:
            meta_bits.append(f"pov={scene.pov}")
        header = f"[场景 {scene.idx} / {'/'.join(meta_bits)}]"
        parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)


_SYSTEM_TEMPLATE = """\
你是「滚动摘要 Agent」（Summarizer）。
你的职责：
  1. 为一集的场景原文生成 episode_summary（本集摘要）。
  2. 把上一集的 rolling_summary（前情提要）和本集合并，产出新的 rolling_summary。

滚动摘要的用途：作为剧本 / 分镜 / 提示词 Agent 的"前情提要"，\
让他们在不读全部历史的情况下能理解当前剧情与角色状态。

## 输出要求

1. episode_summary（本集摘要）：
   - 字数：约 300 ~ {_EPISODE_SUMMARY_MAX_CHARS} 字
   - 包含：本集主要事件、关键转折、人物动作、情绪走向
   - 使用叙述体中文，不要写解释说明（如"本集讲述了"）

2. rolling_summary（滚动摘要）：
   - 字数：约 500 ~ {_ROLLING_SUMMARY_MAX_CHARS} 字
   - 包含：前面所有集的剧情要点 + 本集要点
   - 必须保留：
     * 主要角色关系演变（感情、身份、立场变化）
     * 重要事件（转折、冲突、承诺、决定）
     * 关键地点 / 道具 / 时间节点
   - 可以删减：
     * 过于细节的对话
     * 未推动剧情的描写
     * 已被前次 rolling_summary 覆盖的冗余信息

3. 只输出 JSON，不输出任何解释文字。

输出 schema:
{{
  "episode_summary": "本集摘要…",
  "rolling_summary": "截至本集的前情提要…"
}}
"""


def call_summarizer(
    episode: Episode,
    scenes_text: str,
    *,
    previous_rolling_summary: str = "",
    llm: Any | None = None,
) -> SummarizerResult:
    """调用 LLM 生成 episode_summary + rolling_summary。"""

    _llm = llm or get_llm(json_mode=True)
    system = _SYSTEM_TEMPLATE.format(
        _EPISODE_SUMMARY_MAX_CHARS=_EPISODE_SUMMARY_MAX_CHARS,
        _ROLLING_SUMMARY_MAX_CHARS=_ROLLING_SUMMARY_MAX_CHARS,
    )
    rolling_section = ""
    if previous_rolling_summary:
        rolling_section = (
            f"\n\n## 前一集的滚动摘要（作为历史上下文）\n{previous_rolling_summary}\n"
        )
    user = (
        f"第 {episode.idx} 集：{episode.title}\n"
        f"场景数：{len(episode.scenes)}\n"
        f"{rolling_section}\n"
        f"## 本集场景原文（共 {len(scenes_text)} 字）\n{scenes_text}"
    )
    response = _llm.invoke(
        [SystemMessage(content=system), HumanMessage(content=user)]
    )
    raw = response.content if hasattr(response, "content") else str(response)
    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
        return SummarizerResult.model_validate(data)
    except Exception as exc:
        snippet = raw[:300].replace("\n", " ")
        raise SummarizerError(
            f"Summarizer JSON parse failed: {exc} | raw_prefix: {snippet}"
        ) from exc


def build_result_with_estimate(raw: SummarizerResult) -> tuple[SummarizerResult, int]:
    """估算 rolling_summary 的 token 数并返回 (result, token_estimate)。"""
    token_est = estimate_tokens(raw.rolling_summary)
    return raw, token_est
