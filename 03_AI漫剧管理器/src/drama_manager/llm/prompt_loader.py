"""
提示词加载器: 实现「项目专属提示词」机制。

设计:
  - 默认模板:   src/drama_manager/llm/prompts.py (随代码分发, 也是兜底)
  - 项目副本:   data/projects/{id}/prompts.py (init 时复制, 用户可自由修改)

加载优先级:
  1. 项目目录存在 prompts.py  → 动态加载该文件 (用户特化版)
  2. 否则                      → 用代码内置的默认 prompts 模块

这样每个项目初始化后都有一份独立的提示词副本，
用户可按项目特点修改自己的 prompts.py，互不影响、也不污染初始模板。

用法 (节点内):
    from drama_manager.llm.prompt_loader import load_for_project
    P = load_for_project(state.get("project_id"))
    system = P.CONVERT_SYSTEM
"""
import importlib.util
from pathlib import Path

# 内置默认模板模块 (兜底)
from drama_manager.llm import prompts as _default_prompts


def default_template_path() -> Path:
    """默认模板 prompts.py 的源文件路径 (用于 init 时复制)。"""
    return Path(_default_prompts.__file__)


def load_for_project(project_id: str | None):
    """
    加载项目专属提示词模块，回退到默认模板。

    Args:
        project_id: 项目 id；为 None 或项目无副本时返回默认模块

    Returns:
        一个模块对象，可通过属性访问提示词常量 (如 P.CONVERT_SYSTEM)
    """
    if not project_id:
        return _default_prompts

    from drama_manager.config import get_projects_dir
    proj_file = get_projects_dir() / project_id / "prompts.py"
    if not proj_file.exists():
        # 项目还没有副本 (老项目或未复制)，用默认模板
        return _default_prompts

    # 从文件路径动态加载项目的 prompts.py
    spec = importlib.util.spec_from_file_location(
        f"_project_prompts_{project_id}", proj_file
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
