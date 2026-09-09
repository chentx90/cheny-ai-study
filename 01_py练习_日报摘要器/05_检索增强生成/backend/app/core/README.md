# backend/app/core

核心类型与工具，供所有层共用。

| 文件 | 内容 |
|:--|:--|
| `schemas.py` | 全部领域 Pydantic 类型：`RetrieveRequest` `KnowledgePackage` `EvidenceItem` `ExecutionContext` 等 |
| `chunker.py` | `Chunker`：文本分块，支持 `max_chars` / `overlap`；返回 `ChunkResult` dataclass |
| `execution_engine.py` | `ExecutionEngine`：按 `method.steps` 顺序运行算子，记录 trace |
| `method_loader.py` | 从 `methods/*.json` 加载 `RetrievalMethod`；`get_available_methods()` 枚举所有配置 |
| `method_resolver.py` | `resolve_method()`：按优先级（显式 method > mode > intent）确定方法 ID；`detect_intent()` |
| `registry.py` | `CapabilityRegistryService`：注册后端能力与 adapter 实例，通过 `get_adapter(backend_id)` 获取 |
| `planner.py` | `STRATEGY_CATALOG`：策略元数据，`create_retrieval_plan()` |
