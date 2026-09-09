"""
配置管理模块。

职责:
  1. 定义项目内的标准路径 (数据目录、数据库、项目仓库)
  2. 读取 config.toml 配置文件
  3. 提供 LLM 配置 (优先环境变量，其次配置文件)

配置优先级: 环境变量 > config.toml > 默认值
"""
import os
import tomllib
from pathlib import Path

# ── 路径常量 ──

# config.toml 的绝对路径: 项目根目录/config.toml
CONFIG_PATH = Path(__file__).parent.parent.parent / "config.toml"

# 数据根目录: 项目根目录/data/ (所有运行时数据存储于此)
DATA_DIR = Path(__file__).parent.parent.parent / "data"


def get_data_dir() -> Path:
    """
    获取数据根目录，不存在则自动创建。

    目录结构:
      data/
      └── projects/             # 各项目目录
          ├── {project_id}/
          │   ├── project.json
          │   ├── panels.json
          │   └── ...

    Returns:
        Path: 数据根目录的绝对路径
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def get_db_path() -> Path:
    """
    获取 SQLite 数据库文件路径。

    所有项目共用一个数据库文件 (data/drama_manager.db)，
    通过 project_id 字段区分不同项目的数据。

    Returns:
        Path: 数据库文件的绝对路径
    """
    return get_data_dir() / "drama_manager.db"


def get_projects_dir() -> Path:
    """
    获取项目仓库根目录。

    每个项目在此目录下有一个子目录，子目录同时是:
    - git 仓库 (用于版本管理)
    - 媒体文件存储目录 (images/, audio/, video/)

    Returns:
        Path: 项目仓库根目录的绝对路径
    """
    d = get_data_dir() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_config() -> dict:
    """
    加载 config.toml 配置文件。

    配置文件格式 (TOML):
        [llm]
        provider = "openai"
        model = "gpt-4o"
        api_key = "sk-xxx"

        [project]
        default_style = "电影感动画"

    如果配置文件不存在，返回空字典。

    Returns:
        dict: 解析后的配置字典，结构与 TOML 文件一致
    """
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


def get_llm_config() -> dict:
    """
    获取 LLM 调用配置 (统一通过 NewAPI 中转)。

    NewAPI 是 OpenAI 兼容的中转服务，负责路由到不同底层模型。
    只需配置三个值: model / api_key / base_url。

    配置来源优先级:
    1. 环境变量 (适合 CI/临时切换)
    2. config.toml 配置文件 (适合持久化配置)
    3. 默认值

    环境变量:
    - LLM_MODEL:   模型名称 (如 "gpt-4o", "claude-sonnet-4-20250514", "qwen-plus")
    - LLM_API_KEY: NewAPI 的 API Key
    - LLM_BASE_URL: NewAPI 地址 (如 "https://api.newapi.com/v1")

    Returns:
        dict: LLM 配置字典
            {
                "model": str,      # 模型名称 (NewAPI 后台配置的名字)
                "api_key": str,    # NewAPI 的 API Key
                "base_url": str,   # NewAPI 的接口地址
            }
    """
    cfg = load_config().get("llm", {})
    return {
        "model": os.getenv("LLM_MODEL", cfg.get("model", "gpt-4o")),
        "api_key": os.getenv("LLM_API_KEY", cfg.get("api_key", "")),
        "base_url": os.getenv("LLM_BASE_URL", cfg.get("base_url", "")),
    }
