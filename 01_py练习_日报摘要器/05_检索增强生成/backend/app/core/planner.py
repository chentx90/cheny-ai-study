from typing import List
from enum import Enum
from ..core.schemas import RetrievalPlan, RetrievalMode


class StrategyConfig:
    def __init__(self, name: str, capability: str, backend_id: str = "postgres_pgvector"):
        self.name = name
        self.capability = capability
        self.backend_id = backend_id


STRATEGY_CATALOG = {
    "simple_vector": StrategyConfig("simple_vector", "vector_search"),
    "parent_context": StrategyConfig("parent_context", "parent_expand"),
    "rerank": StrategyConfig("rerank", "rerank"),
    "image_context": StrategyConfig("image_context", "asset_fetch"),
    "data_asset": StrategyConfig("data_asset", "data_asset_search"),
}


PLANNING_RULES = {
    RetrievalMode.fast: ["simple_vector"],
    RetrievalMode.balanced: ["simple_vector", "parent_context", "rerank"],
    RetrievalMode.reliable: ["simple_vector", "parent_context", "rerank", "image_context"],
    RetrievalMode.deep: ["simple_vector", "parent_context", "rerank", "image_context", "data_asset"],
}


def create_retrieval_plan(query: str, mode: RetrievalMode) -> RetrievalPlan:
    strategies = PLANNING_RULES.get(mode, PLANNING_RULES[RetrievalMode.balanced])
    plan = []
    for strategy in strategies:
        if strategy in STRATEGY_CATALOG:
            cfg = STRATEGY_CATALOG[strategy]
            plan.append({
                "strategy": strategy,
                "capability": cfg.capability,
                "backend_id": cfg.backend_id
            })
    return RetrievalPlan(query=query, plan=plan)
