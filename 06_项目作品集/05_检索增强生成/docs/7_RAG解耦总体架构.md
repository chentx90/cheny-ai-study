# RAG 解耦总体架构

## 一、设计目标

本项目将检索增强生成系统拆分为一组可独立运行、可单独容器化、可替换实现的模块。

核心原则：

```text
数据源不绑定召回方式
数据库不绑定检索算法
召回方式不绑定固定接口
Agent 不直接访问底层数据库
RAG 编排层负责组合不同能力
```

系统不预设“某个数据库只能使用某种 RAG 方法”，而是通过能力注册、适配器和检索计划实现任意组合。

例如：

```text
PostgreSQL + pgvector  可以参与向量召回、元数据过滤、父文档扩展
OpenSearch            可以参与 BM25、过滤检索、Hybrid
Qdrant / Milvus        可以参与向量召回、多向量召回
Neo4j / NebulaGraph    可以参与 GraphRAG、实体扩展
MinIO / S3             可以参与原文、图片、附件取回
```

## 二、总体分层

```text
Agent 应用层
  ↓
RAG 编排网关层
  ↓
召回策略层
  ↓
索引适配器层
  ↓
数据存储层
  ↓
数据接入与清洗层
```

每一层只依赖抽象契约，不依赖具体实现。

## 三、模块划分

```text
rag-gateway
  RAG 编排网关，接收查询请求，生成检索计划，组合召回结果

query-understanding
  查询理解模块，识别意图、实体、时间、业务域、可靠性要求

retrieval-planner
  检索计划模块，根据查询需求选择召回策略和数据后端

retriever-runtime
  召回策略执行模块，执行 vector、bm25、parent、rerank、graph 等策略

index-adapter
  数据库/索引适配器模块，屏蔽 PostgreSQL、Qdrant、OpenSearch 等差异

ingestion-service
  数据清洗入库模块，负责解析、切分、摘要、问题生成、embedding

metadata-service
  元数据服务，管理文档、chunk、资产、权限、版本、日志

object-service
  原始文件和图片附件服务，可使用 MinIO / S3

evaluation-service
  检索效果评估和反馈模块，可后续接入
```

## 四、核心思想：能力注册

每个数据库或索引后端不直接暴露为固定接口，而是注册自己支持的能力。

示例：

```json
{
  "backend": "postgres_pgvector",
  "capabilities": [
    "vector_search",
    "metadata_filter",
    "chunk_fetch",
    "parent_expand",
    "asset_fetch"
  ]
}
```

```json
{
  "backend": "opensearch",
  "capabilities": [
    "keyword_search",
    "bm25_search",
    "metadata_filter"
  ]
}
```

```json
{
  "backend": "neo4j",
  "capabilities": [
    "entity_search",
    "graph_expand",
    "path_search"
  ]
}
```

召回策略只声明需要什么能力，不关心由哪个数据库提供。

## 五、检索计划

一次查询被转换为检索计划，而不是固定调用某个接口。

示例：

```json
{
  "query": "液压泵压力不足怎么排查？",
  "intent": "troubleshooting",
  "plan": [
    {
      "step": "semantic_recall",
      "strategy": "vector_search",
      "required_capability": "vector_search",
      "candidate_backends": ["postgres_pgvector", "qdrant"]
    },
    {
      "step": "keyword_recall",
      "strategy": "bm25_search",
      "required_capability": "bm25_search",
      "candidate_backends": ["opensearch"]
    },
    {
      "step": "context_expand",
      "strategy": "parent_expand",
      "required_capability": "parent_expand",
      "candidate_backends": ["postgres_pgvector"]
    },
    {
      "step": "asset_attach",
      "strategy": "asset_fetch",
      "required_capability": "asset_fetch",
      "candidate_backends": ["postgres_pgvector", "object_service"]
    }
  ]
}
```

## 六、数据后端与召回策略任意组合

| 数据后端 | 可组合能力 |
|:--|:--|
| PostgreSQL | 元数据过滤、业务资产查询、父文档扩展、日志、pgvector 向量检索 |
| pgvector | Chunk 向量召回、数据资产向量召回 |
| OpenSearch | BM25、关键词召回、过滤召回 |
| Qdrant / Milvus | 大规模向量召回、多集合向量召回 |
| Neo4j / NebulaGraph | 实体关系、路径扩展、GraphRAG |
| MinIO / S3 | 原文、图片、附件、解析结果 |
| Redis | 缓存、短期会话、热门召回结果 |

| 召回策略 | 依赖能力 |
|:--|:--|
| simple_vector | vector_search |
| bm25 | keyword_search / bm25_search |
| hybrid | vector_search + keyword_search |
| parent_context | chunk_fetch + parent_expand |
| preset_question | vector_search 或 keyword_search |
| image_context | asset_fetch |
| data_asset | vector_search + metadata_filter |
| rerank | candidate_recall + rerank_model |
| graph_rag | entity_search + graph_expand |
| crag | evidence_evaluate + retry_plan |

## 七、服务间调用关系

```text
Agent
  ↓
rag-gateway
  ↓
query-understanding
  ↓
retrieval-planner
  ↓
retriever-runtime
  ↓
index-adapter
  ↓
PostgreSQL / pgvector / OpenSearch / Qdrant / Neo4j / MinIO
```

## 八、容器化边界

每个模块可以单独容器化：

```text
rag-gateway
query-understanding
retrieval-planner
retriever-runtime
index-adapter-postgres
index-adapter-opensearch
index-adapter-qdrant
ingestion-service
metadata-service
object-service
evaluation-service
```

第一阶段可以合并部署，后续按模块拆容器：

```text
阶段 1：rag-service 单体 + postgres
阶段 2：rag-gateway / ingestion-service / postgres 分离
阶段 3：retriever-runtime / index-adapter 分离
阶段 4：多数据库、多策略、多容器组合
```

## 九、总结

本架构将 RAG 系统拆成三类能力：

```text
数据能力：不同数据库和索引后端提供什么能力
策略能力：不同召回算法需要什么能力
编排能力：根据查询动态组合数据能力和策略能力
```

最终目标是：

```text
任意数据库后端
  ×
任意召回策略
  ×
任意 Agent 场景
```

通过统一能力注册和检索计划进行组合，而不是在代码中写死某个数据库对应某个接口。