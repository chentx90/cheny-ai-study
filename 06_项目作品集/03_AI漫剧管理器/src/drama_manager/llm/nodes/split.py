"""
split 节点: 长篇小说交互式分集。

流程 (全文喂 LLM，需长上下文模型):
  1. generate_outline(text)              -> 全文喂，生成大纲
  2. generate_proposal(outline, text)    -> 全文喂，提分集方案 (交互)
  3. adjust_proposal(...)                -> 按用户反馈调整方案
  4. execute_split(outline, proposal, text) -> 全文喂，输出切割点，Python 切

字数硬上限由 CLI 控制 (默认 30 万)，超过中止，不在此分块。
"""
import json
import re
from drama_manager.llm.client import get_llm
from drama_manager.llm.state import DramaState
from drama_manager.llm.prompt_loader import load_for_project

CHAR_THRESHOLD = 100000
NL = chr(10)


async def generate_outline(text, project_id=None):
    """全文喂 LLM 生成全篇大纲 (信息不遗漏)。"""
    P = load_for_project(project_id)
    llm = get_llm(temperature=0.3, json_mode=False)
    resp = await llm.ainvoke([
        {"role": "system", "content": P.OUTLINE_SYSTEM},
        {"role": "user", "content": P.OUTLINE_USER.format(text=text)},
    ])
    return resp.content.strip()


async def generate_proposal(outline, char_count, project_id=None):
    P = load_for_project(project_id)
    llm = get_llm(temperature=0.3, json_mode=False)
    resp = await llm.ainvoke([
        {"role": "system", "content": P.SPLIT_DISCUSS_SYSTEM},
        {"role": "user", "content": P.SPLIT_DISCUSS_USER.format(char_count=char_count, outline=outline)},
    ])
    return resp.content.strip()


async def adjust_proposal(outline, previous_proposal, user_feedback, project_id=None):
    P = load_for_project(project_id)
    llm = get_llm(temperature=0.3, json_mode=False)
    resp = await llm.ainvoke([
        {"role": "system", "content": P.SPLIT_INTERACTIVE_SYSTEM},
        {"role": "user", "content": P.SPLIT_INTERACTIVE_USER.format(
            outline=outline, previous_proposal=previous_proposal, user_feedback=user_feedback
        )},
    ])
    return resp.content.strip()


async def execute_split(outline, proposal, text, project_id=None):
    P = load_for_project(project_id)
    llm = get_llm(temperature=0.3, json_mode=False)
    resp = await llm.ainvoke([
        {"role": "system", "content": P.SPLIT_EXECUTE_SYSTEM},
        {"role": "user", "content": P.SPLIT_EXECUTE_USER.format(
            plan=proposal, outline=outline,
            char_count=len(text), text=text
        )},
    ])
    markers = _parse_episodes(resp.content)
    episodes = _apply_ratios(markers, text)
    for ep in episodes:
        ep["char_count"] = len(ep.get("content", ""))
    return episodes


def _apply_ratios(markers: list[dict], text: str) -> list[dict]:
    """比例粗定位 + boundary_hint 精确落点，退回换行对齐。"""
    if not markers:
        return []

    total = len(text)
    # 搜索窗口：比例位置前后各 10%
    window = max(int(total * 0.10), 2000)

    positions = []
    for m in markers:
        ratio = max(0.0, min(1.0, float(m.get("split_ratio", 0.0))))
        approx = int(total * ratio)
        hint = m.get("boundary_hint", "").strip()

        pos = None
        if hint:
            # 在窗口内精确查找
            lo = max(0, approx - window)
            hi = min(total, approx + window)
            idx = text.find(hint, lo, hi)
            if idx != -1:
                pos = idx
        if pos is None:
            # 退回：从比例位置向后找最近换行
            nl = text.find("\n", approx)
            pos = nl + 1 if nl != -1 else approx

        positions.append(pos)

    # 第一段强制从头开始
    positions[0] = 0

    episodes = []
    for i, m in enumerate(markers):
        start = positions[i]
        end = positions[i + 1] if i + 1 < len(positions) else None
        content = text[start:end].strip() if end is not None else text[start:].strip()
        episodes.append({
            "index": m.get("index", i),
            "title": m.get("title", f"第{i+1}段"),
            "summary": m.get("summary", ""),
            "content": content,
        })
    return episodes


async def generate_append_proposal(outline, existing_episodes, new_char_count, new_preview, project_id=None):
    P = load_for_project(project_id)
    llm = get_llm(temperature=0.3, json_mode=False)
    summary = NL.join("- " + e.get("title","") + ": " + e.get("summary","") for e in existing_episodes) or "none"
    resp = await llm.ainvoke([
        {"role": "system", "content": P.APPEND_SPLIT_DISCUSS_SYSTEM},
        {"role": "user", "content": P.APPEND_SPLIT_DISCUSS_USER.format(
            existing_outline=outline, existing_episodes_summary=summary,
            split_rules="沿用已有分段方式", new_char_count=new_char_count, new_text_preview=new_preview
        )},
    ])
    return resp.content.strip()


async def execute_append_split(outline, existing_episodes, new_text, project_id=None):
    P = load_for_project(project_id)
    llm = get_llm(temperature=0.3, json_mode=False)
    summary = NL.join("- " + e.get("title","") + ": " + e.get("summary","") for e in existing_episodes) or "none"
    resp = await llm.ainvoke([
        {"role": "system", "content": P.APPEND_SPLIT_EXECUTE_SYSTEM},
        {"role": "user", "content": P.APPEND_SPLIT_EXECUTE_USER.format(
            existing_outline=outline, existing_episodes_summary=summary,
            split_rules="沿用已有分段方式",
            char_count=len(new_text), text=new_text
        )},
    ])
    markers = _parse_episodes(resp.content)
    new_eps = _apply_ratios(markers, new_text)
    for ep in new_eps:
        ep["char_count"] = len(ep.get("content", ""))
    all_eps = list(existing_episodes)
    for ep in new_eps:
        ep["index"] = len(all_eps)
        all_eps.append(ep)
    return all_eps


async def split_novel_node(state):
    pid = state.get("project_id")
    raw_text = state.get("raw_text", "")
    if len(raw_text) < CHAR_THRESHOLD:
        return {"outline": "", "episodes": [], "current_episode_index": 0, "error": None}
    is_append = state.get("is_append", False)
    if is_append:
        P = load_for_project(pid)
        outline = state.get("existing_outline", "")
        existing = state.get("existing_episodes", [])
        all_eps = await execute_append_split(outline, existing, raw_text, pid)
        llm = get_llm(temperature=0.3, json_mode=False)
        resp = await llm.ainvoke([
            {"role": "system", "content": P.OUTLINE_MERGE_SYSTEM},
            {"role": "user", "content": P.OUTLINE_MERGE_USER.format(existing_outline=outline, new_summary=str(len(all_eps)) + " episodes")},
        ])
        return {"outline": resp.content.strip(), "episodes": all_eps, "current_episode_index": len(existing), "error": None}
    else:
        outline = await generate_outline(raw_text, pid)
        proposal = await generate_proposal(outline, len(raw_text), pid)
        episodes = await execute_split(outline, proposal, raw_text, pid)
        return {"outline": outline, "episodes": episodes, "current_episode_index": 0, "error": None}


def _parse_episodes(raw):
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split(NL)
        text = NL.join(lines[1:-1])
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
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
            if isinstance(obj, dict) and ("content" in obj or "title" in obj):
                objects.append(obj)
        except json.JSONDecodeError:
            continue
    return objects
