# RAG 编排网关与 Agent 路由模块

## 一、模块定位

RAG 编排网关是 Agent 与底层检索系统之间的中间层。

Agent 不直接调用 PostgreSQL、Qdrant、OpenSearch、Neo4j，也不直接决定具体数据库。Agent 只表达任务意图、约束条件和结果要求，RAG 编排网关负责生成检索计划并组合不同召回能力。

## 二、职责边界

### Agent 层负责

```text
理解用户意图
判断是否需要检索
判断是否需要数据库查询
判断是否需要图片证据
判断是否需要高可靠回答
调用 RAG 编排网关
根据知识包生成最终回答
```

### RAG 编排网关负责

```text
接收检索请求
查询理解
选择召回策略
选择后端能力
生成检索计划
调用 retriever-runtime
聚合证据
返回知识包
```

### 底层适配器负责

```text
执行具体数据库查询
执行向量检索
执行 BM25 检索
取回图片、附件、Chunk
写入检索日志
```

## 三、统一检索入口

不提前固定多个接口，而是使用统一入口：

```text
POST /retrieve
```

请求示例：

```json
{
  "query": "液压泵压力不足应该怎么排查？",
  "agent_id": "factory_agent",
  "session_id": "s001",
  "mode": "balanced",
  "constraints": {
    "business_domain": "equipment",
    "need_image": true,
    "need_citation": true,
    "risk_level": "medium"
  }
}
```

如果 Agent 已经判断出策略，也可以传入建议：

```json
{
  "query": "液压泵压力不足应该怎么排查？",
  "requested_strategies": ["hybrid", "parent_context", "image_context"],
  "constraints": {
    "business_domain": "equipment"
  }
}
```

这些只是建议，不强制绑定具体数据库。

## 四、Planner 输出

RAG 编排网关会生成检索计划：

```json
{
  "query": "液压泵压力不足应该怎么排查？",
  "intent": "troubleshooting",
  "plan": [
    {
      "name": "semantic_recall",
      "strategy": "simple_vector",
      "required_capabilities": ["vector_search"],
      "candidate_backends": ["postgres_pgvector", "qdrant_main"],
      "top_k": 20
    },
    {
      "name": "keyword_recall",
      "strategy": "bm25",
      "required_capabilities": ["bm25_search"],
      "candidate_backends": ["opensearch_main"],
      "top_k": 20
    },
    {
      "name": "fusion",
      "strategy": "hybrid_fusion",
      "method": "rrf"
    },
    {
      "name": "context_expand",
      "strategy": "parent_context",
      "required_capabilities": ["parent_expand"]
    },
    {
      "name": "asset_attach",
      "strategy": "image_context",
      "required_capabilities": ["asset_fetch"]
    }
  ]
}
```

## 五、知识包返回

统一返回 Knowledge Package：

```json
{
  "query": "液压泵压力不足应该怎么排查？",
  "intent": "troubleshooting",
  "confidence": 0.82,
  "evidence": [
    {
      "object_type": "chunk",
      "object_id": "chunk_001",
      "score": 0.91,
      "content": "当液压泵压力不足时，应优先检查过滤器是否堵塞...",
      "source": {
        "document_id": "doc_001",
        "title": "液压系统维护手册",
        "section_path": "设备维护 > 液压系统 > 故障排查",
        "page": 18
      },
      "assets": [
        {
          "asset_type": "image",
          "asset_url": "http://localhost:9000/factory/pump_fault_01.png",
          "caption": "液压泵压力异常示意图"
        }
      ]
    }
  ],
  "missing_info": [
    "当前设备型号",
    "压力表读数"
  ],
  "retrieval_trace": {
    "strategies": ["simple_vector", "bm25", "hybrid_fusion", "parent_context", "image_context"],
    "backends": ["postgres_pgvector", "opensearch_main"],
    "latency_ms": 120
  }
}
```

## 六、Agent 路由逻辑

Agent 层可以使用 LangGraph 做路由。

```text
analyze_query
  ↓
decide_retrieval_need
  ↓
build_retrieval_request
  ↓
call_rag_gateway
  ↓
evaluate_knowledge_package
  ↓
answer_or_continue
```

AgentState：

```python
from typing import TypedDict, List, Dict, Any, Optional

class AgentState(TypedDict):
    query: str
    intent: Optional[str]
    need_rag: bool
    need_database: bool
    need_image: bool
    need_high_reliability: bool
    retrieval_request: Dict[str, Any]
    knowledge_package: Dict[str, Any]
    final_answer: Optional[str]
    missing_info: List[str]
```

## 七、路由示例

| 用户问题 | Agent 判断 | RAG 请求倾向 |
|:--|:--|:--|
| “XX 是什么？” | 普通知识问答 | mode=fast |
| “液压泵压力不足怎么办？” | 故障问答，需要图片 | need_image=true |
| “这个制度完整条款是什么？” | 长上下文问答 | need_citation=true |
| “上月销售额是多少？” | 智能问数 | need_database=true，先检索 data_asset |
| “给我可靠一点的答案” | 高可靠回答 | mode=reliable |
| “这个问题和哪些设备有关？” | 关系推理 | prefer_graph=true |

## 八、模式设计

`mode` 不是固定接口，而是检索强度配置。

```text
fast
  快速召回，少量候选

balanced
  多路召回，父文档扩展

reliable
  多路召回 + rerank + 证据评估

deep
  查询分解 + 多轮召回 + 图谱扩展
```

## 九、容器化设计

容器名称：

```text
rag-gateway
```

职责：

```text
统一 /retrieve 入口
查询理解
检索计划生成
策略编排
知识包聚合
检索轨迹记录
```

可以拆分：

```text
query-understanding
retrieval-planner
rag-gateway
```

第一阶段可合并在一个 FastAPI 服务中。

## 十、总结

RAG 编排网关的重点是：

```text
不钉死接口
不钉死数据库
不钉死策略
通过统一请求、检索计划和能力注册动态组合
```

Agent 只提出任务需求，RAG 网关负责把需求转换为可执行的检索计划。