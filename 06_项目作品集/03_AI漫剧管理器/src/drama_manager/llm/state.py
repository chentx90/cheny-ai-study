"""
DramaState - workflow global state.
"""
from typing import TypedDict, Annotated
from langgraph.graph import add_messages


class DramaState(TypedDict):
    """
    Global state for the workflow.

    New project:  raw_text -> split -> convert -> extract -> bind -> infer
    Append mode:  raw_text + existing data -> split(append) -> convert(new only) -> extract(merge) -> bind -> infer
    """
    # Input
    project_id: str
    raw_text: str
    char_threshold: int
    style: str

    # Append mode fields
    is_append: bool
    existing_outline: str
    existing_episodes: list[dict]
    split_rules: str

    # Split output
    outline: str
    episodes: list[dict]
    current_episode_index: int

    # Convert context (injected per-episode)
    prev_summary: str
    next_summary: str

    # Convert output
    panels: list[dict]
    episode_panel_map: dict

    # Later nodes
    entities: list[dict]
    panel_entity_bindings: dict
    variables: dict
    messages: Annotated[list, add_messages]
    error: str | None
