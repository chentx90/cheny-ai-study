"""
extract 节点: 从分镜列表中提取人物、场景、道具。

工作流中的第二个节点，负责分析所有分镜文本，
通过 LLM 提取出其中出现的人物角色、场景地点、重要道具。

输出格式:
  state["entities"] = [
      {"entity_type":"character", "name":"张小凡", "aliases":"小凡", "description":"18岁男性..."},
      {"entity_type":"location",  "name":"青云大殿", "aliases":"大殿", "description":"中式古代殿堂..."},
      {"entity_type":"item",      "name":"诛仙古剑", "aliases":"古剑", "description":"三尺青锋..."},
  ]

description 字段的用途:
  - 人物: 包含外貌/服装描述，用于后续生成人物立绘提示词
  - 场景: 包含环境/氛围描述，用于生成场景背景图提示词
  - 道具: 包含外观/材质描述，用于生成道具图片提示词
"""
import json
from drama_manager.llm.client import get_llm
from drama_manager.llm.state import DramaState
from drama_manager.llm.prompt_loader import load_for_project


def _parse_extract(raw: str) -> dict:
    """
    从 LLM 输出文本中解析提取结果 JSON。

    LLM 可能返回 {"characters":[...], "locations":[...], "items":[...]} 格式。
    解析策略与 _parse_panels 类似，支持容错。

    Args:
        raw: LLM 返回的原始文本

    Returns:
        提取结果字典，始终包含 characters/locations/items 三个键
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 提取 {...} 部分
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return {"characters": [], "locations": [], "items": []}


async def extract_entities_node(state: DramaState) -> dict:
    """
    extract 节点: 从分镜中提取人物/场景/道具。

    读取 state["panels"] (分镜列表)，输出 state["entities"] (实体列表)。

    处理逻辑:
    1. 将所有分镜的 scene/action/dialogue 拼接为文本
    2. 附上已有实体列表 (避免重复提取)
    3. 调用 LLM 提取，返回 JSON 格式的 characters/locations/items
    4. 扁平化为统一的 entity 列表 (每项带 entity_type 字段)

    Args:
        state: 工作流全局状态，必须包含 panels 字段

    Returns:
        dict: 要合并到状态的更新字段
            {"entities": [...], "error": None}
    """
    llm = get_llm()
    panels = state.get("panels", [])
    if not panels:
        return {"entities": [], "error": "没有分镜数据"}

    # 加载项目专属提示词 (无副本时回退默认模板)
    P = load_for_project(state.get("project_id"))

    # 拼接所有分镜文本 (带序号便于 LLM 定位)
    panels_text = "\n---\n".join(
        f"[分镜{p.get('sort_order', i+1)}] "
        f"场景: {p.get('scene','')}\n"
        f"动作: {p.get('action','')}\n"
        f"对话: {p.get('dialogue','')}"
        for i, p in enumerate(panels)
    )

    # 已有实体 (JSON 格式，告诉 LLM 不要重复提取)
    existing = json.dumps(state.get("entities", []), ensure_ascii=False, indent=2)

    # 调用 LLM
    prompt = P.EXTRACT_USER.format(panels_text=panels_text, existing=existing)
    response = await llm.ainvoke([
        {"role": "system", "content": P.EXTRACT_SYSTEM},
        {"role": "user", "content": prompt},
    ])

    # 解析结果
    extracted = _parse_extract(response.content)

    # 扁平化: 将 characters/locations/items 合并为一个列表
    # 每项添加 entity_type 字段标识类型
    entities = []
    for char in extracted.get("characters", []):
        char["entity_type"] = "character"
        entities.append(char)
    for loc in extracted.get("locations", []):
        loc["entity_type"] = "location"
        entities.append(loc)
    for item in extracted.get("items", []):
        item["entity_type"] = "item"
        entities.append(item)

    return {"entities": entities, "error": None}
