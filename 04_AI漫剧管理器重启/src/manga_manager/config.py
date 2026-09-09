"""项目配置与路径管理。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    return {}


def get_data_dir() -> Path:
    configured = os.getenv("MANGA_DATA_DIR")
    root = Path(configured) if configured else PROJECT_ROOT / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_works_dir() -> Path:
    works = get_data_dir() / "works"
    works.mkdir(parents=True, exist_ok=True)
    return works


def get_context_budget() -> int:
    cfg = load_config().get("context", {})
    return int(os.getenv("MANGA_CONTEXT_MAX_TOKENS", cfg.get("max_tokens", 80000)))


def get_llm_config() -> dict[str, Any]:
    cfg = load_config().get("llm", {})
    return {
        "provider": os.getenv("LLM_PROVIDER", cfg.get("provider", "")),
        "model": os.getenv("LLM_MODEL", cfg.get("model", "gpt-4o")),
        "api_key": os.getenv("LLM_API_KEY", cfg.get("api_key", "")),
        "base_url": os.getenv("LLM_BASE_URL", cfg.get("base_url", "")),
    }


def get_default_style() -> dict[str, str]:
    cfg = load_config().get("project", {})
    return {
        "narrative_style": cfg.get(
            "default_narrative_style", "节奏清晰，镜头语言服务情绪，不额外扩写情节"
        ),
        "visual_style": cfg.get(
            "default_visual_style", "cinematic anime, expressive lighting, consistent character design"
        ),
    }
