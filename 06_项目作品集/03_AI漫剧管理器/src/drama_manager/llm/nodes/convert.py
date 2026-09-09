"""
convert 节点: 小说原文 -> 按视频时长切分的分镜片段列表。

支持两种调用方式:
  1. 带上下文 (outline + prev_summary + next_summary): 分集模式
  2. 纯文本: 短篇直接切分

处理流程:
  1. 按自然段落分 chunk (避免超过 LLM 上下文)
  2. 每 chunk 调用 LLM，按"画面视频时长"(4-15秒/段)切分原文
  3. 合并所有 chunk 的片段，重新编号 sort_order

性能:
  - 多个 chunk 通过 asyncio.gather 并发调用 LLM，Semaphore 限流到 CONCURRENCY；
    gather 结果保序，片段先后顺序不会乱。

输出:
  state["panels"] = [
    {"sort_order":1, "duration":8, "source_text":"本段原文",
     "scene_info":"中景|晴|黄昏|山路", "characters":[], "items":[]}, ...
  ]
  characters / items 留空，由后续 extract/bind 步骤填充。
"""
import json
import re
import asyncio
from drama_manager.llm.client import get_llm
from drama_manager.llm.state import DramaState
from drama_manager.llm.prompt_loader import load_for_project

# 并发上限: 同时在途的 LLM 请求数
CONCURRENCY = 8


def _split_text(text: str, chunk_size: int = 5000) -> list[str]:
    paragraphs = text.split("\n")
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) > chunk_size and current:
            chunks.append(current.strip())
            current = ""
        current += para + "\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


def _parse_panels(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except json.JSONDecodeError:
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
    objects = []
    for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text):
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict) and ("source_text" in obj or "duration" in obj):
                objects.append(obj)
        except json.JSONDecodeError:
            continue
    return objects


async def _convert_chunk(chunk: str, outline: str, prev_summary: str,
                         next_summary: str, llm,
                         sem: asyncio.Semaphore,
                         sys_tpl: str, user_tpl: str) -> list[dict]:
    """
    把单个文本 chunk 按视频时长切分为分镜片段 (并发单元)。

    用 semaphore 限流，保证同时在途请求不超过 CONCURRENCY。

    Args:
        chunk:        文本片段
        outline:      全篇大纲 (上下文参考)
        prev_summary: 上一集梗概
        next_summary: 下一集梗概
        llm:          共享 LLM 客户端
        sem:          并发信号量
        sys_tpl:      system 提示词模板
        user_tpl:     user 提示词模板

    Returns:
        本 chunk 切出的分镜片段列表
    """
    user_msg = user_tpl.format(
        outline=outline or "（无）",
        prev_summary=prev_summary or "（无，本集为开篇）",
        next_summary=next_summary or "（无，本集为结尾）",
        text=chunk,
    )
    async with sem:
        response = await llm.ainvoke([
            {"role": "system", "content": sys_tpl},
            {"role": "user", "content": user_msg},
        ])
    return _parse_panels(response.content)


async def convert_novel_node(state: DramaState) -> dict:
    llm = get_llm(json_mode=False)
    raw_text = state.get("raw_text", "")
    if not raw_text:
        return {"error": "没有输入文本"}

    # 加载项目专属提示词 (无副本时回退默认模板)
    P = load_for_project(state.get("project_id"))

    outline = state.get("outline", "") or ""
    prev_summary = state.get("prev_summary", "") or ""
    next_summary = state.get("next_summary", "") or ""

    # 按自然段落分 chunk
    chunks = _split_text(raw_text)

    # 并发切分所有 chunk，gather 保序 (片段先后不乱)
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [
        _convert_chunk(chunk, outline, prev_summary, next_summary, llm, sem,
                       P.CONVERT_SYSTEM, P.CONVERT_USER)
        for chunk in chunks
    ]
    chunk_results = await asyncio.gather(*tasks)

    # 按 chunk 顺序合并片段
    all_panels: list[dict] = []
    for panels in chunk_results:
        all_panels.extend(panels)

    # 全局重新编号 + 补齐空字段 (characters/items 后续实体绑定填)
    for idx, panel in enumerate(all_panels):
        panel["sort_order"] = idx + 1
        panel.setdefault("characters", [])
        panel.setdefault("items", [])

    return {"panels": all_panels, "error": None}
