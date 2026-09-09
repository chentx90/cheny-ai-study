"""LangChain LLM 客户端封装。"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from manga_manager.config import get_llm_config


def get_llm(model: str | None = None, temperature: float = 0.2, json_mode: bool = True) -> ChatOpenAI:
    cfg = get_llm_config()
    kwargs = {
        "model": model or cfg["model"],
        "api_key": cfg["api_key"],
        "base_url": cfg["base_url"],
        "temperature": temperature,
        "max_retries": 3,
        "timeout": 300,
    }
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatOpenAI(**kwargs)
