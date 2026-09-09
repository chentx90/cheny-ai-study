"""
JSON 文件存储层。

替代 SQLite，每个项目一个文件夹，数据以 JSON 文件存储。
优势: 人可读、git diff 友好、零依赖、调试方便。

目录结构:
  data/
  ├── projects/
  │   ├── {project_id}/
  │   │   ├── project.json      # 项目元数据 (id/name/style/created_at)
  │   │   ├── episodes.json     # 分集列表 (index=0 为大纲)
  │   │   ├── panels.json       # 分镜列表
  │   │   ├── entities.json     # 实体列表 (人物/场景/道具)
  │   │   ├── bindings.json     # 分镜-实体绑定关系
  │   │   └── variables.json    # 变量配置
  └── templates/
      ├── builtin/              # 内置模板 (随代码分发)
      └── custom/               # 用户自定义模板
"""
import json
import uuid
from pathlib import Path
from datetime import datetime


# ══════════════════════════════════════════════════
# 路径工具
# ══════════════════════════════════════════════════

def _data_root() -> Path:
    """数据根目录: 项目根目录/data/"""
    from drama_manager.config import get_data_dir
    return get_data_dir()


def _projects_dir() -> Path:
    """项目仓库根目录: data/projects/"""
    d = _data_root() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _project_dir(project_id: str) -> Path:
    """单个项目目录: data/projects/{project_id}/"""
    d = _projects_dir() / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ══════════════════════════════════════════════════
# 通用 JSON 读写
# ══════════════════════════════════════════════════

def _read_json(path: Path, default=None):
    """读取 JSON 文件，不存在返回 default"""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default if default is not None else {}


def _write_json(path: Path, data):
    """写入 JSON 文件 (原子写入: 先写 .tmp 再 rename)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _new_id() -> str:
    """生成 8 位短 ID"""
    return uuid.uuid4().hex[:8]


# ══════════════════════════════════════════════════
# Project 操作
# ══════════════════════════════════════════════════

def create_project(name: str, style: str = "电影感动画") -> dict:
    """
    创建新项目。

    创建内容:
    - data/projects/{id}/project.json
    - data/projects/{id}/episodes.json (空列表)
    - data/projects/{id}/panels.json (空列表)
    - data/projects/{id}/entities.json (空列表)
    - data/projects/{id}/bindings.json (空字典)
    - data/projects/{id}/variables.json (空列表)
    - data/projects/{id}/media/ 目录

    注: 大纲不存于此，统一放在 episodes.json 的 index=0 项。

    Args:
        name:  项目名称
        style: 全局画风

    Returns:
        项目字典 {id, name, source_text, style, created_at}
    """
    project_id = _new_id()
    project = {
        "id": project_id,
        "name": name,
        "source_text": "",
        "style": style,
        "created_at": datetime.now().isoformat(),
    }
    d = _project_dir(project_id)
    _write_json(d / "project.json", project)
    _write_json(d / "episodes.json", [])
    _write_json(d / "panels.json", [])
    _write_json(d / "entities.json", [])
    _write_json(d / "bindings.json", {})
    _write_json(d / "variables.json", [])
    (d / "media").mkdir(exist_ok=True)
    # 复制一份提示词模板到项目目录，供用户按项目特化修改 (不影响初始模板)
    _copy_prompt_template(d)
    return project


def _copy_prompt_template(project_dir: Path):
    """把默认提示词模板 prompts.py 复制到项目目录，作为该项目的可编辑副本。"""
    import shutil
    from drama_manager.llm.prompt_loader import default_template_path
    src = default_template_path()
    if src.exists():
        shutil.copy(src, project_dir / "prompts.py")


def get_project(project_id: str) -> dict | None:
    """读取项目元数据"""
    p = _project_dir(project_id) / "project.json"
    return _read_json(p) if p.exists() else None


def list_projects() -> list[dict]:
    """列出所有项目 (按创建时间倒序)"""
    projects = []
    for d in _projects_dir().iterdir():
        if d.is_dir():
            p = get_project(d.name)
            if p:
                projects.append(p)
    projects.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return projects


def save_project(project: dict):
    """保存项目元数据"""
    _write_json(_project_dir(project["id"]) / "project.json", project)


# ══════════════════════════════════════════════════
# 当前活动项目 (跨进程持久化)
# ══════════════════════════════════════════════════
#
# CLI 每次命令是独立进程，进程内全局变量无法记住"当前项目"。
# 因此把当前项目 id 持久化到 data/.active 纯文本文件，
# 各命令启动时读取，drama use <id> 命令写入。

def _active_file() -> Path:
    """当前活动项目记录文件: data/.active"""
    return _data_root() / ".active"


def get_active_project_id() -> str | None:
    """读取当前活动项目 id，不存在返回 None"""
    f = _active_file()
    if f.exists():
        pid = f.read_text(encoding="utf-8").strip()
        # 校验项目目录仍存在，避免指向已删除项目
        if pid and (_projects_dir() / pid).exists():
            return pid
    return None


def set_active_project_id(project_id: str):
    """设置当前活动项目 id"""
    _active_file().write_text(project_id, encoding="utf-8")


# ══════════════════════════════════════════════════
# 统一操作日志 (operations.jsonl)
# ══════════════════════════════════════════════════
#
# 每个项目一个 operations.jsonl (JSON Lines, 每行一条记录)。
# 所有写操作 (init/import/split/convert/extract/bind/infer/edit...)
# 追加一条 {time, command, detail}，替代原先零散的 split_log.json。
# JSONL 格式便于追加和逐行读取，无需每次重写整个文件。

def log_operation(project_id: str, command: str, detail: str = ""):
    """
    追加一条操作日志到 operations.jsonl。

    Args:
        project_id: 项目 id
        command:    操作命令名 (如 "convert" / "extract" / "bind")
        detail:     操作详情 (如 "107分镜" / "+45实体")
    """
    from datetime import datetime
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "command": command,
        "detail": detail,
    }
    log_path = _project_dir(project_id) / "operations.jsonl"
    line = json.dumps(record, ensure_ascii=False)
    # 追加模式写入，避免重写整个文件
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_operations(project_id: str, limit: int = 50) -> list[dict]:
    """
    读取操作日志 (最近 limit 条，按时间倒序)。

    Args:
        project_id: 项目 id
        limit:      最多返回条数

    Returns:
        日志记录列表，最新的在前
    """
    log_path = _project_dir(project_id) / "operations.jsonl"
    if not log_path.exists():
        return []
    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    # 倒序返回最近 limit 条
    return records[::-1][:limit]


# ══════════════════════════════════════════════════
# Episode 操作 (分集)
# ══════════════════════════════════════════════════

def load_episodes(project_id: str) -> list[dict]:
    """读取分集列表"""
    return _read_json(_project_dir(project_id) / "episodes.json", [])


def save_episodes(project_id: str, episodes: list[dict]):
    """保存分集列表"""
    _write_json(_project_dir(project_id) / "episodes.json", episodes)


# ══════════════════════════════════════════════════
# Panel 操作
# ══════════════════════════════════════════════════

def load_panels(project_id: str) -> list[dict]:
    """读取项目的所有分镜"""
    return _read_json(_project_dir(project_id) / "panels.json", [])


def save_panels(project_id: str, panels: list[dict]):
    """保存分镜列表"""
    _write_json(_project_dir(project_id) / "panels.json", panels)


def add_panel(project_id: str, panel: dict) -> dict:
    """添加单个分镜"""
    panels = load_panels(project_id)
    panel.setdefault("id", _new_id())
    panels.append(panel)
    save_panels(project_id, panels)
    return panel


def add_panels_batch(project_id: str, panels: list[dict]) -> list[dict]:
    """批量添加分镜"""
    existing = load_panels(project_id)
    for p in panels:
        p.setdefault("id", _new_id())
    existing.extend(panels)
    save_panels(project_id, existing)
    return panels


def update_panel(project_id: str, panel_id: str, updates: dict):
    """更新单个分镜的指定字段"""
    panels = load_panels(project_id)
    for p in panels:
        if p.get("id") == panel_id:
            p.update(updates)
            break
    save_panels(project_id, panels)


def delete_panel(project_id: str, panel_id: str):
    """删除单个分镜"""
    panels = load_panels(project_id)
    panels = [p for p in panels if p.get("id") != panel_id]
    save_panels(project_id, panels)


# ══════════════════════════════════════════════════
# Entity 操作
# ══════════════════════════════════════════════════

def load_entities(project_id: str, entity_type: str = None) -> list[dict]:
    """读取实体列表，可按类型筛选"""
    entities = _read_json(_project_dir(project_id) / "entities.json", [])
    if entity_type:
        entities = [e for e in entities if e.get("entity_type") == entity_type]
    return entities


def save_entities(project_id: str, entities: list[dict]):
    """保存实体列表"""
    _write_json(_project_dir(project_id) / "entities.json", entities)


def add_entities_batch(project_id: str, entities: list[dict]) -> list[dict]:
    """批量添加实体"""
    existing = load_entities(project_id)
    for e in entities:
        e.setdefault("id", _new_id())
    existing.extend(entities)
    save_entities(project_id, existing)
    return entities


def find_entity_by_name(project_id: str, name: str) -> dict | None:
    """根据名称精确查找实体"""
    for e in load_entities(project_id):
        if e.get("name") == name:
            return e
    return None


# ══════════════════════════════════════════════════
# Binding 操作 (分镜-实体绑定)
# ══════════════════════════════════════════════════

def load_bindings(project_id: str) -> dict:
    """读取绑定关系 {panel_id: [entity_id, ...]}"""
    return _read_json(_project_dir(project_id) / "bindings.json", {})


def save_bindings(project_id: str, bindings: dict):
    """保存绑定关系"""
    _write_json(_project_dir(project_id) / "bindings.json", bindings)


def get_panel_entities(project_id: str, panel_id: str) -> list[dict]:
    """获取分镜绑定的所有实体"""
    bindings = load_bindings(project_id)
    entity_ids = bindings.get(panel_id, [])
    all_entities = load_entities(project_id)
    entity_map = {e["id"]: e for e in all_entities}
    return [entity_map[eid] for eid in entity_ids if eid in entity_map]


def get_entity_panels(project_id: str, entity_id: str) -> list[dict]:
    """获取实体出现过的所有分镜"""
    bindings = load_bindings(project_id)
    all_panels = load_panels(project_id)
    panel_map = {p["id"]: p for p in all_panels}
    panel_ids = [pid for pid, eids in bindings.items() if entity_id in eids]
    return [panel_map[pid] for pid in panel_ids if pid in panel_map]


# ══════════════════════════════════════════════════
# Variable 操作
# ══════════════════════════════════════════════════

def load_variables(project_id: str, category: str = None) -> list[dict]:
    """读取变量列表，可按分类筛选"""
    variables = _read_json(_project_dir(project_id) / "variables.json", [])
    if category:
        variables = [v for v in variables if v.get("category") == category]
    return variables


def set_variable(project_id: str, category: str, key: str, value: str):
    """设置变量 (存在则更新，不存在则创建)"""
    variables = load_variables(project_id)
    for v in variables:
        if v.get("category") == category and v.get("key") == key:
            v["value"] = value
            _write_json(_project_dir(project_id) / "variables.json", variables)
            return
    variables.append({
        "id": _new_id(),
        "category": category,
        "key": key,
        "value": value,
    })
    _write_json(_project_dir(project_id) / "variables.json", variables)
