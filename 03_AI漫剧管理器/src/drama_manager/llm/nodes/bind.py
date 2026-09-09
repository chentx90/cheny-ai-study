"""
bind 节点: 将提取的实体绑定到分镜。

两种模式:
  llm  (默认): 把一批分镜 + 实体表一起传给 LLM，精确判断哪些实体真正出现
  text (fallback): 字符串匹配，速度快但误匹配多

CLI 调用时按集分批，每集调用一次 LLM，不是每个分镜调用一次。
"""
import json
from drama_manager.llm.state import DramaState
from drama_manager.llm.client import get_llm
from drama_manager.llm.prompt_loader import load_for_project


async def bind_entities_node(state: DramaState) -> dict:
    """字符串匹配模式（graph 自动流程用，快速）"""
    panels = state.get("panels", [])
    entities = state.get("entities", [])
    if not panels or not entities:
        return {"panel_entity_bindings": {}, "error": None}
    bindings = _text_bind(panels, entities)
    return {"panel_entity_bindings": bindings, "error": None}


async def bind_entities_llm(panels: list[dict], entities: list[dict],
                            project_id: str | None = None) -> dict:
    """LLM 精确绑定模式（CLI entity bind 用，按集调用）"""
    if not panels or not entities:
        return {}

    # 加载项目专属提示词 (无副本时回退默认模板)
    P = load_for_project(project_id)

    entities_text = "\n".join(
        f"[{i}] ({e.get('entity_type','')}) {e.get('name','')}：{e.get('description','')[:40]}"
        for i, e in enumerate(entities)
    )
    panels_text = "\n".join(
        f"[{p.get('sort_order')}] {p.get('paperwork','')[:80]} | 台词: {p.get('dialogue','')[:40]}"
        for p in panels
    )

    llm = get_llm(json_mode=True)
    resp = await llm.ainvoke([
        {"role": "system", "content": P.BIND_SYSTEM},
        {"role": "user", "content": P.BIND_USER.format(
            entities_text=entities_text,
            panels_text=panels_text,
        )},
    ])

    return _parse_bind_result(resp.content)


def _parse_bind_result(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            # 确保 value 都是 list[str]
            return {str(k): [str(x) for x in v] for k, v in result.items()}
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, dict):
                return {str(k): [str(x) for x in v] for k, v in result.items()}
        except json.JSONDecodeError:
            pass
    return {}


def _text_bind(panels: list[dict], entities: list[dict]) -> dict:
    """字符串匹配（快速，误匹配多，仅作 fallback）"""
    import re
    bindings: dict[str, list[str]] = {}
    for panel in panels:
        panel_id = str(panel.get("sort_order", 0))
        panel_text = " ".join(str(panel.get(k, "")) for k in [
            "scene", "action", "dialogue", "paperwork", "characters"
        ]).lower()
        bound: list[str] = []
        for idx, entity in enumerate(entities):
            name = entity.get("name", "")
            aliases = [a.strip() for a in entity.get("aliases", "").split(",") if a.strip()]
            for term in [name] + aliases:
                if not term or len(term) < 2:
                    continue
                pattern = f"(?<![\\u4e00-\\u9fff]){re.escape(term.lower())}(?![\\u4e00-\\u9fff])"
                if re.search(pattern, panel_text):
                    bound.append(str(idx))
                    break
        bindings[panel_id] = list(set(bound))
    return bindings
