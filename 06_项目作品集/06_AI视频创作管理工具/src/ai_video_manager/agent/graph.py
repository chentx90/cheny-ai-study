from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class WorkflowAgentState(TypedDict, total=False):
    run_id: str
    thread_id: str
    project_id: str
    user_id: str | None
    user_request: str
    current_view: str
    active_context: dict[str, Any]
    approval_mode: str
    conversation_context: dict[str, Any]
    context_budget: dict[str, Any]
    project_context: dict[str, Any]
    message: str
    commands: list[dict[str, Any]]
    command_history: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    step: int
    react_mode: bool
    done: bool
    requires_confirmation: bool
    status: str
    results: list[dict[str, Any]]


def build_agent_graph(service):
    graph = StateGraph(WorkflowAgentState)
    graph.add_node("load_context", service.load_context_node)
    graph.add_node("plan", service.plan_node)
    graph.add_node("execute", service.execute_node)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "plan")
    graph.add_conditional_edges(
        "plan",
        lambda state: "wait" if state.get("requires_confirmation") or state.get("done") else "execute",
        {"wait": END, "execute": "execute"},
    )
    graph.add_conditional_edges(
        "execute",
        lambda state: "plan" if state.get("react_mode") else "done",
        {"plan": "plan", "done": END},
    )
    return graph.compile()
