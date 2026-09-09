"""
infer 节点: 为每个分镜推理图片提示词和视频提示词。

工作流中的第四个 (最后一个) 节点。

处理流程:
  1. 遍历每个分镜
  2. 组装上下文: 分镜文案 + 绑定实体(含重要性/描述/参考图标记) + 风格
  3. 调用 LLM 生成双字段输出: 图片提示词 + 视频提示词
  4. 解析 === 分隔的双字段，写回分镜

锚定策略:
  - major 实体: 注入完整描述，提示词需保持外观一致；有 image_path 时标注[参考图]
  - minor 实体: 仅提示存在，用泛称，不精确还原

性能:
  - 多个分镜的 LLM 调用通过 asyncio.Semaphore 限流并发 (默认 8)，
    避免 107 个分镜串行等待，同时防止瞬时打爆 API 限速。
"""
import asyncio
from drama_manager.llm.client import get_llm
from drama_manager.llm.state import DramaState
from drama_manager.llm.prompt_loader import load_for_project

# 并发上限: 同时在途的 LLM 请求数，平衡速度与 API 限速
CONCURRENCY = 8


def _build_entities_block(bound_entities: list[dict]) -> str:
    """
    把绑定到当前分镜的实体列表，组装成带「锚定标记」的文本块，注入 LLM prompt。

    锚定标记规则:
    - [核心]   : importance == "major"，需要在提示词中保持外观一致性
    - [核心][参考图] : major 且配置了 image_path，提示 LLM 追加 <ref:名称> 占位符
    - [次要]   : importance == "minor"，用泛称即可，不必精确还原

    实体描述注入策略:
    - major: 附带完整 description (年龄/发色/服装/场景特征等)，保证一致性
    - minor: 不注入 description，只给名称，避免污染画面、节省 token

    Args:
        bound_entities: 当前分镜绑定的实体字典列表

    Returns:
        多行文本块，每行一个实体；无绑定时返回兜底提示
    """
    if not bound_entities:
        return "（无绑定实体，依分镜文案自行判断画面）"

    # 实体类型的中文标签
    type_label = {"character": "人物", "location": "场景", "item": "道具"}

    lines = []
    for e in bound_entities:
        importance = e.get("importance", "major")
        # 核心实体打 [核心] 标记，次要实体打 [次要]
        tags = "[核心]" if importance == "major" else "[次要]"
        # 核心实体且有参考图时，额外追加 [参考图] 标记
        if importance == "major" and e.get("image_path"):
            tags += "[参考图]"

        tl = type_label.get(e.get("entity_type", ""), "其他")
        # 仅核心实体注入描述，次要实体留空
        desc = e.get("description", "") if importance == "major" else ""

        line = f"- {tags}（{tl}）{e.get('name','')}"
        if desc:
            line += f"：{desc}"
        lines.append(line)
    return "\n".join(lines)


async def _infer_one(panel: dict, entity_map: dict, bindings: dict,
                     style: str, llm, sem: asyncio.Semaphore,
                     sys_tpl: str, user_tpl: str) -> dict:
    """
    为单个分镜推理图片/视频提示词 (并发单元)。

    用 semaphore 限流，保证同时在途的请求数不超过 CONCURRENCY。

    Args:
        panel:      单个分镜字典
        entity_map: 字符串下标 → 实体字典 的索引
        bindings:   分镜绑定关系 {panel_id: [entity_index, ...]}
        style:      画风约束
        llm:        共享的 LLM 客户端
        sem:        并发信号量

    Returns:
        更新后的分镜副本 (含 prompt / video_prompt)
    """
    panel_id = str(panel.get("sort_order", 0))

    # 查找该分镜绑定的实体下标，取出实体对象
    bound_indices = bindings.get(panel_id, [])
    bound_entities = [entity_map[i] for i in bound_indices if i in entity_map]

    # 组装带锚定标记的实体文本块
    entities_block = _build_entities_block(bound_entities)

    # 优先用 paperwork 字段，回退到 scene + action 拼接 (兼容旧格式)
    paperwork = panel.get("paperwork", "")
    if not paperwork:
        paperwork = f"{panel.get('scene', '')}\n{panel.get('action', '')}"

    prompt_text = user_tpl.format(
        paperwork=paperwork,
        entities_block=entities_block,
        style=style,
    )

    # 限流并发: 同时在途请求不超过 CONCURRENCY 个
    async with sem:
        response = await llm.ainvoke([
            {"role": "system", "content": sys_tpl},
            {"role": "user", "content": prompt_text},
        ])

    # 解析双字段输出 (用 === 分隔图片提示词和视频提示词)
    content = response.content.strip()
    parts = content.split("===")
    prompt = parts[0].strip() if len(parts) > 0 else ""
    video_prompt = parts[1].strip() if len(parts) > 1 else ""

    # LLM 未按 === 格式输出时告警 (video_prompt 缺失)，便于排查
    if len(parts) < 2:
        print(f"  [warn] 分镜 #{panel_id} 输出缺少 === 分隔，video_prompt 为空")

    # 构建更新后的分镜副本，写回两个提示词字段
    updated_panel = panel.copy()
    updated_panel["prompt"] = prompt
    updated_panel["video_prompt"] = video_prompt
    return updated_panel


async def infer_prompts_node(state: DramaState) -> dict:
    """
    infer 节点: 批量为分镜生成图片/视频提示词 (并发)。

    读取 state["panels"], state["entities"], state["panel_entity_bindings"],
    更新 state["panels"] 中每个分镜的 prompt 和 video_prompt 字段。

    处理逻辑:
    1. 构建实体索引 (字符串下标 → 实体字典)
    2. 为每个分镜创建一个 _infer_one 协程
    3. 用 asyncio.gather 并发执行 (Semaphore 限流到 CONCURRENCY)
    4. 保持原分镜顺序返回 (gather 结果有序)

    注: 此处 bindings 的 value 是「entities 列表的字符串下标」，
        而非 entity_id。下标在单次调用内有效 (CLI 层已据当前 entities 重建)。

    Args:
        state: 工作流全局状态，必须包含 panels, entities,
               panel_entity_bindings, variables 字段

    Returns:
        dict: 要合并到状态的更新字段 {"panels": [更新后的分镜列表]}
    """
    llm = get_llm(json_mode=False)
    panels = state.get("panels", [])
    entities = state.get("entities", [])
    bindings = state.get("panel_entity_bindings", {})
    variables = state.get("variables", {})

    if not panels:
        return {"panels": [], "error": "没有分镜数据"}

    # 加载项目专属提示词 (无副本时回退默认模板)
    P = load_for_project(state.get("project_id"))

    # 画风优先用 state.variables 显式传入，否则用项目 prompts.py 的 STYLE
    style = variables.get("style") or getattr(P, "STYLE", "电影感动画")

    # 构建实体索引: 字符串下标 → 实体字典
    entity_map = {str(i): e for i, e in enumerate(entities)}

    # 并发信号量: 限制同时在途的 LLM 请求数
    sem = asyncio.Semaphore(CONCURRENCY)

    # 为每个分镜创建协程，gather 并发执行 (结果顺序与输入一致)
    tasks = [
        _infer_one(panel, entity_map, bindings, style, llm, sem,
                   P.INFER_SYSTEM, P.INFER_USER)
        for panel in panels
    ]
    updated_panels = await asyncio.gather(*tasks)

    return {"panels": list(updated_panels), "error": None}



