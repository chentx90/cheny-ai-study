"""Chunk 内容的 LLM 富化：按需调用大模型生成摘要 / 预设问题。

配置复用隔壁项目的 NewAPI 环境变量（OpenAI 兼容中转）：
  - LLM_API_KEY:  NewAPI 密钥
  - LLM_BASE_URL: NewAPI 地址（默认 http://localhost:3000/v1）
  - LLM_MODEL:    模型名（默认 gpt-4o-mini）

设计要点：
  - 摘要 / 预设问题都是「可选」，由调用方传入开关；默认不生成。
  - 无 key 或 langchain 不可用时 is_available() 返回 False，调用方应跳过而非阻断入库。
  - 失败降级：单个 chunk LLM 调用异常时该 chunk 保持空摘要/空问题，不影响整体。
"""
import json
import asyncio
from typing import List, Tuple

from ..config import settings


def _llm_config() -> dict:
    return {
        "model": settings.llm_model,
        "api_key": settings.llm_api_key,
        "base_url": settings.llm_base_url,
    }


def is_available() -> bool:
    """是否具备调用 LLM 的条件（有 key 且 langchain 可导入）。"""
    if not _llm_config()["api_key"]:
        return False
    try:
        import langchain_openai  # noqa: F401
        return True
    except Exception:
        return False


def _build_llm():
    from langchain_openai import ChatOpenAI

    cfg = _llm_config()
    return ChatOpenAI(
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        temperature=0.3,
        max_retries=2,
        timeout=60,
        model_kwargs={"response_format": {"type": "json_object"}},
    )


_PROMPT = (
    "你是知识库构建助手。基于给定的文本片段，{tasks}。"
    "只输出 JSON，格式：{{{fields}}}。不要输出多余文字。\n\n文本片段：\n{content}"
)


async def _enrich_one(llm, content: str, gen_summary: bool, gen_questions: bool, sem: asyncio.Semaphore) -> Tuple[str, List[str]]:
    tasks = []
    fields = []
    if gen_summary:
        tasks.append("用一句话概括其核心内容作为摘要")
        fields.append('"summary": "..."')
    if gen_questions:
        tasks.append("生成 2-4 个用户可能用来检索到该片段的预设问题")
        fields.append('"questions": ["...", "..."]')
    prompt = _PROMPT.format(
        tasks="；".join(tasks),
        fields=", ".join(fields),
        content=content[:2000],
    )
    try:
        async with sem:
            resp = await llm.ainvoke(prompt)
        data = json.loads(resp.content)
        summary = str(data.get("summary", "")) if gen_summary else ""
        questions = data.get("questions", []) if gen_questions else []
        if not isinstance(questions, list):
            questions = []
        return summary, [str(q) for q in questions][:5]
    except Exception:
        # 单条降级：不阻断整体入库
        return "", []


async def extract_title(text: str) -> str:
    """用 LLM 从正文提炼一个简洁中文标题；不可用或失败返回空串。"""
    if not is_available() or not (text or "").strip():
        return ""
    try:
        llm = _build_llm()
        prompt = (
            "为下面的文档正文起一个简洁、准确的中文标题（不超过30字）。"
            '只输出 JSON：{"title": "..."}。\n\n正文：\n' + text[:2000]
        )
        resp = await llm.ainvoke(prompt)
        data = json.loads(resp.content)
        return str(data.get("title", "")).strip()[:80]
    except Exception:
        return ""


async def enrich_chunks(
    chunks: List[dict],
    gen_summary: bool = False,
    gen_questions: bool = False,
    concurrency: int = 4,
) -> List[dict]:
    """对 chunk dict 列表按需填充 summary / preset_questions。原地更新并返回。

    chunks: 每项含 'content'，可选已有 'summary'/'preset_questions'。
    """
    if not (gen_summary or gen_questions) or not chunks or not is_available():
        return chunks

    llm = _build_llm()
    sem = asyncio.Semaphore(max(1, concurrency))
    results = await asyncio.gather(
        *[_enrich_one(llm, c.get("content", ""), gen_summary, gen_questions, sem) for c in chunks]
    )
    for c, (summary, questions) in zip(chunks, results):
        if gen_summary and summary:
            c["summary"] = summary
        if gen_questions:
            c["preset_questions"] = questions
    return chunks
