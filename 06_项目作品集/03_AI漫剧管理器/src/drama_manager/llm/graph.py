"""
LangGraph work flow.
"""
from langgraph.graph import StateGraph, END
from drama_manager.llm.state import DramaState
from drama_manager.llm.nodes.split import split_novel_node
from drama_manager.llm.nodes.convert import convert_novel_node
from drama_manager.llm.nodes.extract import extract_entities_node
from drama_manager.llm.nodes.bind import bind_entities_node
from drama_manager.llm.nodes.infer import infer_prompts_node


async def split_or_convert(state: DramaState) -> dict:
    episodes = state.get("episodes", [])
    outline = state.get("outline", "")
    is_append = state.get("is_append", False)
    start_idx = state.get("current_episode_index", 0) if is_append else 0

    if not episodes:
        return await convert_novel_node(state)

    all_panels = list(state.get("panels", [])) if is_append else []
    episode_panel_map = dict(state.get("episode_panel_map", {})) if is_append else {}
    NL = chr(10)

    # Only process new episodes (start_idx onwards)
    new_episodes = episodes[start_idx:]

    for i_offset, ep in enumerate(new_episodes):
        i = start_idx + i_offset
        prev_ep = episodes[i-1] if i > 0 else None
        next_ep = episodes[i+1] if i < len(episodes) - 1 else None
        prev_summary = prev_ep.get("summary", "") if prev_ep else ""
        next_summary = next_ep.get("summary", "") if next_ep else ""

        ep_state = {
            **state,
            "raw_text": ep.get("content", ""),
            "outline": outline,
            "prev_summary": prev_summary,
            "next_summary": next_summary,
            "panels": [],
        }
        result = await convert_novel_node(ep_state)
        ep_panels = result.get("panels", [])
        for p in ep_panels:
            p["episode_index"] = i
            p["episode_title"] = ep.get("title", "")
        episode_panel_map[i] = ep_panels
        all_panels.extend(ep_panels)

    # Re-index all panels globally
    for idx, panel in enumerate(all_panels):
        panel["sort_order"] = idx + 1

    return {"panels": all_panels, "episode_panel_map": episode_panel_map, "error": None}


def build_drama_graph():
    graph = StateGraph(DramaState)
    graph.add_node("split", split_novel_node)
    graph.add_node("convert", split_or_convert)
    graph.add_node("extract", extract_entities_node)
    graph.add_node("bind", bind_entities_node)
    graph.add_node("infer", infer_prompts_node)
    graph.set_entry_point("split")
    graph.add_edge("split", "convert")
    graph.add_edge("convert", "extract")
    graph.add_edge("extract", "bind")
    graph.add_edge("bind", "infer")
    graph.add_edge("infer", END)
    return graph.compile()
