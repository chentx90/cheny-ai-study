# PostgreSQL + pgvector RAG 数据库项目计划书

## 一、项目定位

本模块是工厂管理系统的知识与数据底座，负责承接文档知识、图片资料、数据资产、指标口径和历史案例等内容，为上层 Agent 平台提供统一、可追溯、可更新的 RAG 检索服务。

系统采用 PostgreSQL + pgvector 作为第一阶段数据库方案。PostgreSQL 负责结构化元数据、业务资产、版本状态和检索日志，pgvector 负责文本向量相似度检索。Agent 平台不直接访问底层数据库，而是通过 RAG API 获取结构化知识包。

## 二、建设目标

1. 使用 PostgreSQL 管理文档、Chunk、图片 URL、数据资产、检索日志。
2. 使用 pgvector 存储 Chunk 向量和数据资产向量，实现基础语义检索。
3. 明确 Chunking 格式，保证每个文本块可以独立理解和追溯。
4. 为每个 Chunk 预留 `preset_questions` 字段，增强问题相关性。
5. 预留多种 RAG 检索接口，由 Agent 层判断路由后调用。
6. 支持文档问答、图片证据返回、智能问数资产匹配、父文档上下文召回。
7. 保留后续扩展 BM25、Rerank、GraphRAG、多模态图片理解的接口空间。

## 三、系统边界

### 1. 本模块负责

- 文档基础信息管理
- 文档 Chunk 存储
- Chunk 向量存储
- 图片 URL、OCR、图片描述存储
- 表、字段、指标等数据资产存储
- RAG 检索接口的数据支撑
- 检索日志记录
- 知识状态管理

### 2. 本模块不负责

- Agent 多步推理
- 业务数据库真实数据查询
- 前端页面交互
- 大模型最终回答生成
- 复杂工作流编排

这些能力由 Agent 平台、业务数据库访问服务、前端系统分别承担。

## 四、整体架构

```text
用户问题
  ↓
Agent 层判断意图和路由
  ↓
调用对应 RAG 接口
  ↓
PostgreSQL + pgvector 检索
  ↓
返回知识包
  ↓
Agent 生成最终回答
```

容器划分：

```text
agent-service
  LangChain + LangGraph
  负责路由、工具调用、回答生成

rag-service
  FastAPI
  负责 RAG 检索接口

postgres
  PostgreSQL + pgvector
  存文档、Chunk、图片、向量、数据资产

minio
  存 PDF、图片、附件，可后续接入

redis
  缓存 query embedding、热门结果、任务状态，可后续接入
```

第一阶段核心运行容器：

```text
agent-service
rag-service
postgres
```

## 五、数据库表设计

当前阶段保留 5 张核心表：

```text
1. kb_documents      文档表
2. kb_chunks         文本块表
3. kb_assets         图片/附件资产表
4. data_assets       数据资产表
5. rag_query_logs    检索日志表
```

---

## 六、表一：kb_documents 文档表

用于存储一份文档的基本信息。

```sql
CREATE TABLE kb_documents (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT,
    source_uri TEXT,
    business_domain TEXT,
    version INT DEFAULT 1,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

字段说明：

| 字段 | 说明 |
|:--|:--|
| id | 文档唯一 ID |
| title | 文档标题 |
| doc_type | 文档类型，如 manual、policy、case、spec |
| source_uri | 原始文件地址，可以是本地路径、MinIO 地址、URL |
| business_domain | 业务域，如 equipment、quality、production |
| version | 版本号 |
| status | active / inactive / deleted |
| created_at | 创建时间 |
| updated_at | 更新时间 |

文档示例：

```text
液压系统维护手册
质量异常处理规范
设备点检制度
生产日报字段说明
```

---

## 七、表二：kb_chunks 文本块表

`kb_chunks` 是 RAG 的核心表。文本、章节上下文、摘要、预设问题和向量都保存在这里，便于检索和演示。

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE kb_chunks (
    id UUID PRIMARY KEY,
    document_id UUID REFERENCES kb_documents(id),
    chunk_index INT,
    section_path TEXT,
    title_context TEXT,
    content TEXT NOT NULL,
    summary TEXT,
    preset_questions TEXT[],
    physical_context JSONB,
    embedding vector(1024),
    embedding_model TEXT,
    token_count INT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

字段说明：

| 字段 | 说明 |
|:--|:--|
| document_id | 所属文档 |
| chunk_index | 当前文档中的第几个 Chunk |
| section_path | 章节路径 |
| title_context | 给 Chunk 补充的标题上下文 |
| content | Chunk 原文 |
| summary | Chunk 摘要 |
| preset_questions | 为这个 Chunk 预设的可能问题 |
| physical_context | 页码、段落、图片引用等物理位置 |
| embedding | Chunk 向量 |
| embedding_model | 使用的 embedding 模型 |
| token_count | token 数 |
| status | active / inactive / deleted |

向量索引：

```sql
CREATE INDEX kb_chunks_embedding_hnsw_idx
ON kb_chunks
USING hnsw (embedding vector_cosine_ops);
```

如果 embedding 模型维度不是 1024，需要同步调整：

```sql
embedding vector(768)
embedding vector(1536)
```

---

## 八、Chunking 格式要求

每个 Chunk 需要具备独立理解能力，不能只保存孤立正文。推荐格式如下：

```json
{
  "document_id": "doc_001",
  "chunk_index": 3,
  "section_path": "设备维护 > 液压系统 > 压力不足",
  "title_context": "液压系统维护手册 - 压力不足故障排查",
  "content": "当液压泵压力不足时，应优先检查过滤器是否堵塞、油液液位是否正常，以及泄压阀是否异常。",
  "summary": "说明液压泵压力不足时的优先检查项。",
  "preset_questions": [
    "液压泵压力不足怎么办？",
    "液压系统压力不够应该先检查哪里？",
    "过滤器堵塞会导致液压泵压力不足吗？"
  ],
  "physical_context": {
    "page": 18,
    "paragraph": 2,
    "image_refs": ["asset_001"]
  }
}
```

### 1. content 要求

```text
每个 Chunk 建议 300-800 中文字
尽量按标题、段落、步骤、条款切分
不要从一句话中间切断
同一个检查步骤不要拆开
```

### 2. title_context 要求

`title_context` 用来补足 Chunk 脱离原文后的语义。

原文：

```text
首先检查过滤器是否堵塞。
```

增强后：

```text
液压系统维护手册 - 压力不足故障排查：
首先检查过滤器是否堵塞。
```

### 3. section_path 要求

`section_path` 保留文档层级。

```text
一级标题 > 二级标题 > 三级标题
```

示例：

```text
设备维护 > 液压系统 > 故障排查
质量管理 > 不良品处理 > 返工流程
安全制度 > 特种设备 > 点检要求
```

### 4. summary 要求

`summary` 是给 RAG 和 Agent 快速判断用的短摘要。

要求：

```text
一句话说清这个 Chunk 讲什么
尽量包含业务对象和动作
避免泛泛总结
```

示例：

```text
说明液压泵压力不足时，应检查过滤器、油液液位和泄压阀。
```

### 5. preset_questions 要求

`preset_questions` 用于增强问题相关性。

每个 Chunk 建议预设 2-5 个问题：

```text
一个口语化问法
一个专业术语问法
一个故障场景问法
一个操作步骤问法
```

示例：

```json
[
  "液压泵压力不足怎么办？",
  "液压系统压力异常有哪些原因？",
  "设备压力上不去应该先查哪里？",
  "过滤器堵塞会不会影响液压压力？"
]
```

第一阶段可以人工编写，后续可用 LLM 自动生成。

### 6. physical_context 要求

`physical_context` 保存物理位置，方便引用和展示。

```json
{
  "page": 18,
  "paragraph": 2,
  "table": null,
  "image_refs": ["asset_001"]
}
```

如果来源是 Excel：

```json
{
  "sheet": "点检记录",
  "row_range": "12-25",
  "column_range": "A-F"
}
```

---

## 九、表三：kb_assets 图片/附件资产表

用于保存图片 URL、OCR、图片描述和物理位置。

```sql
CREATE TABLE kb_assets (
    id UUID PRIMARY KEY,
    document_id UUID REFERENCES kb_documents(id),
    chunk_id UUID REFERENCES kb_chunks(id),
    asset_type TEXT DEFAULT 'image',
    asset_url TEXT NOT NULL,
    caption TEXT,
    ocr_text TEXT,
    description TEXT,
    physical_context JSONB,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT now()
);
```

字段说明：

| 字段 | 说明 |
|:--|:--|
| asset_type | image / pdf / excel / video |
| asset_url | 图片或附件 URL |
| caption | 图片标题 |
| ocr_text | OCR 识别文本 |
| description | 图片语义描述 |
| physical_context | 页码、区域、截图位置 |

示例：

```json
{
  "asset_type": "image",
  "asset_url": "http://localhost:9000/factory/pump_fault_01.png",
  "caption": "液压泵压力异常示意图",
  "ocr_text": "过滤器 压力阀 液压泵",
  "description": "图片展示液压泵、过滤器、压力阀之间的连接关系。",
  "physical_context": {
    "page": 18,
    "bbox": [0.12, 0.2, 0.8, 0.65]
  }
}
```

第一阶段通过 Chunk 的 `physical_context.image_refs` 关联图片。后续可扩展：

```text
OCR 文本 embedding
图片 caption embedding
CLIP 图片向量
多模态模型分析
```

---

## 十、表四：data_assets 数据资产表

`data_assets` 用于智能问数前匹配表、字段、指标、案例和工具。当前阶段将这些资产统一管理，便于 Agent 做问数路由和 SQL 生成准备。

```sql
CREATE TABLE data_assets (
    id UUID PRIMARY KEY,
    asset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    business_domain TEXT,
    parent_name TEXT,
    synonyms TEXT[],
    formula TEXT,
    related_table TEXT,
    related_columns TEXT[],
    example_values TEXT[],
    embedding vector(1024),
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT now()
);
```

asset_type 示例：

```text
table
column
metric
case
tool
```

表资产示例：

```json
{
  "asset_type": "table",
  "name": "dwd_order_detail",
  "description": "订单明细事实表，记录每笔订单的商品、金额、用户和时间信息。",
  "business_domain": "sales",
  "synonyms": ["订单明细", "销售明细表"],
  "related_columns": ["order_id", "pay_amount", "pay_time", "region"]
}
```

字段资产示例：

```json
{
  "asset_type": "column",
  "name": "pay_amount",
  "parent_name": "dwd_order_detail",
  "description": "订单实付金额，不含退款后调整。",
  "synonyms": ["销售额", "支付金额", "GMV"],
  "example_values": ["99.00", "158.50"]
}
```

指标资产示例：

```json
{
  "asset_type": "metric",
  "name": "销售额",
  "description": "统计周期内已支付订单的实付金额合计，剔除退款订单。",
  "formula": "sum(pay_amount)",
  "related_table": "dwd_order_detail",
  "related_columns": ["pay_amount", "pay_time", "order_status"],
  "synonyms": ["GMV", "营收金额"]
}
```

---

## 十一、表五：rag_query_logs 检索日志表

用于记录 Agent 调用了什么 RAG 方式，方便调试、演示和后续优化。

```sql
CREATE TABLE rag_query_logs (
    id UUID PRIMARY KEY,
    query TEXT NOT NULL,
    agent_route TEXT,
    rag_method TEXT,
    retrieved_chunk_ids UUID[],
    retrieved_asset_ids UUID[],
    latency_ms INT,
    created_at TIMESTAMP DEFAULT now()
);
```

rag_method 示例：

```text
simple_vector
preset_question
parent_context
image_context
data_asset
hybrid
rerank
```

---

## 十二、RAG 检索接口设计

RAG 服务统一由 `rag-service` 提供，Agent 层根据问题类型判断调用哪个接口。

### 1. 简单向量检索 simple_vector

```text
POST /rag/simple-vector
```

用途：

```text
普通文档问答
快速语义检索
```

逻辑：

```text
query embedding
  ↓
kb_chunks.embedding 相似度搜索
  ↓
返回 top_k chunks
```

### 2. 预设问题检索 preset_question

```text
POST /rag/preset-question
```

用途：

```text
用户问法和原文差异较大时，用 Chunk 预设问题增强匹配。
```

第一阶段推荐做法：

```text
embedding_text = title_context + content + summary + preset_questions
```

后续可拆出独立问题向量表。

### 3. 父文档上下文检索 parent_context

```text
POST /rag/parent-context
```

用途：

```text
命中 Chunk 后返回相邻 Chunk 或同章节内容，避免断章取义。
```

逻辑：

```text
先向量召回 top chunks
  ↓
根据 document_id 和 chunk_index
  ↓
补充前一个 Chunk、后一个 Chunk
  ↓
合并返回
```

### 4. 图片增强检索 image_context

```text
POST /rag/image-context
```

用途：

```text
设备图、流程图、截图、说明书图片。
```

逻辑：

```text
召回 Chunk
  ↓
读取 physical_context.image_refs
  ↓
查询 kb_assets
  ↓
返回 asset_url、caption、description
```

### 5. 数据资产检索 data_asset

```text
POST /rag/data-asset
```

用途：

```text
智能问数前匹配表、字段、指标。
```

逻辑：

```text
query embedding
  ↓
data_assets 向量检索
  ↓
按 asset_type 分组返回 metric / table / column
```

### 6. 混合检索 hybrid

```text
POST /rag/hybrid
```

第一阶段可使用：

```text
向量检索
  +
关键词 ILIKE 简单匹配
  ↓
合并去重
```

后续替换为：

```text
OpenSearch / BM25 + RRF
```

### 7. 精排 rerank

```text
POST /rag/rerank
```

第一阶段可先保留接口：

```text
先 simple_vector 召回 20 条
  ↓
用规则或模型重新排序
  ↓
返回 top 5
```

后续替换为真正的 reranker。

---

## 十三、RAG API 请求与返回格式

统一请求：

```json
{
  "query": "液压泵压力不足怎么办？",
  "top_k": 5,
  "business_domain": "equipment",
  "need_image": true,
  "mode": "balanced"
}
```

统一返回：

```json
{
  "query": "液压泵压力不足怎么办？",
  "rag_method": "image_context",
  "results": [
    {
      "chunk_id": "chunk_001",
      "document_id": "doc_001",
      "score": 0.86,
      "section_path": "设备维护 > 液压系统 > 故障排查",
      "title_context": "液压系统维护手册 - 压力不足故障排查",
      "content": "当液压泵压力不足时，应优先检查过滤器是否堵塞...",
      "summary": "说明液压泵压力不足时的优先检查项。",
      "preset_questions": [
        "液压泵压力不足怎么办？"
      ],
      "assets": [
        {
          "asset_url": "http://localhost:9000/factory/pump_fault_01.png",
          "caption": "液压泵压力异常示意图"
        }
      ]
    }
  ],
  "retrieval_trace": {
    "collections": ["kb_chunks", "kb_assets"],
    "strategies": ["pgvector", "image_context"]
  }
}
```

---

## 十四、基础 SQL 示例

### 1. 文档向量检索

```sql
SELECT
    c.id AS chunk_id,
    c.document_id,
    c.section_path,
    c.title_context,
    c.content,
    c.summary,
    c.preset_questions,
    c.physical_context,
    1 - (c.embedding <=> :query_embedding) AS score
FROM kb_chunks c
JOIN kb_documents d ON d.id = c.document_id
WHERE c.status = 'active'
  AND d.status = 'active'
  AND (:business_domain IS NULL OR d.business_domain = :business_domain)
ORDER BY c.embedding <=> :query_embedding
LIMIT :top_k;
```

### 2. 图片证据查询

```sql
SELECT
    a.id,
    a.asset_type,
    a.asset_url,
    a.caption,
    a.ocr_text,
    a.description,
    a.physical_context
FROM kb_assets a
WHERE a.chunk_id = :chunk_id
  AND a.status = 'active';
```

### 3. 数据资产检索

```sql
SELECT
    id,
    asset_type,
    name,
    description,
    parent_name,
    synonyms,
    formula,
    related_table,
    related_columns,
    1 - (embedding <=> :query_embedding) AS score
FROM data_assets
WHERE status = 'active'
ORDER BY embedding <=> :query_embedding
LIMIT :top_k;
```

---

## 十五、Agent 层路由设计

Agent 不直接判断 SQL 或向量细节，只判断调用哪个 RAG 接口。

| 用户问题 | Agent 路由 | 调用接口 |
|:--|:--|:--|
| “XX 是什么？” | 普通知识问答 | `/rag/simple-vector` |
| “液压泵压力不足怎么办？” | 故障问答 | `/rag/image-context` |
| “这个制度具体怎么规定？” | 长上下文问答 | `/rag/parent-context` |
| “上月销售额是多少？” | 智能问数 | `/rag/data-asset` |
| “有哪些相关文档？” | 多路检索 | `/rag/hybrid` |
| “给我可靠一点的答案” | 精排模式 | `/rag/rerank` |

LangGraph 节点：

```text
analyze_query
  判断问题类型

route_rag_method
  选择 RAG 方法

call_rag_api
  调用对应接口

evaluate_result
  判断结果是否足够

answer
  生成最终回答
```

AgentState 示例：

```python
from typing import TypedDict, List, Dict, Any, Optional

class AgentState(TypedDict):
    query: str
    intent: Optional[str]
    rag_method: Optional[str]
    rag_results: List[Dict[str, Any]]
    need_database: bool
    need_image: bool
    final_answer: Optional[str]
    missing_info: List[str]
```

---

## 十六、入库流程设计

```text
上传文件 / 注册文档
  ↓
写入 kb_documents
  ↓
解析文本、图片、表格
  ↓
按 Chunking 规则切分
  ↓
生成 section_path、title_context、summary
  ↓
生成 preset_questions
  ↓
提取图片，写入 kb_assets
  ↓
拼接 embedding_text
  ↓
生成 embedding
  ↓
写入 kb_chunks.embedding
  ↓
检索测试
```

推荐 embedding 文本：

```text
title_context
section_path
summary
content
preset_questions
```

也可以拼接为：

```text
[标题上下文] ...
[章节路径] ...
[摘要] ...
[正文] ...
[可能问题] ...
```

---

## 十七、更新策略

### 1. 新增

```text
新增 kb_documents
新增 kb_chunks
新增 kb_assets
status = active
```

### 2. 修改

第一阶段可以按文档版本处理：

```text
旧文档 status = inactive
新文档 version + 1
新 Chunk status = active
```

后续可增加 `content_hash` 字段进行更细粒度增量更新。

### 3. 删除

优先软删除：

```text
kb_documents.status = deleted
kb_chunks.status = deleted
kb_assets.status = deleted
```

### 4. 日志

每次检索写入 `rag_query_logs`：

```text
query
agent_route
rag_method
retrieved_chunk_ids
retrieved_asset_ids
latency_ms
```

---

## 十八、开发阶段计划

### 阶段 1：最小 RAG 闭环

只做：

```text
kb_documents
kb_chunks
/rag/simple-vector
```

演示目标：

```text
上传或手写几条设备维护文档
切成 Chunk
生成 embedding
用户提问
返回相关 Chunk
```

### 阶段 2：图片 URL 证据

增加：

```text
kb_assets
/rag/image-context
```

演示目标：

```text
用户询问设备故障
系统返回文字说明 + 图片 URL
```

### 阶段 3：预设问题增强

使用：

```text
preset_questions
/rag/preset-question
```

演示目标：

```text
用户口语化提问
系统仍能匹配专业文档 Chunk
```

### 阶段 4：智能问数资产匹配

增加：

```text
data_assets
/rag/data-asset
```

演示目标：

```text
用户询问“销售额怎么算”
系统返回指标定义、相关表和字段
```

### 阶段 5：Agent 路由

增加：

```text
LangGraph route_rag_method
```

演示目标：

```text
同一个 Agent 根据问题自动调用 simple_vector / image_context / data_asset
```

---

## 十九、项目交付物

```text
docker-compose.yml
init.sql
FastAPI RAG 服务
入库脚本
测试文档与图片
测试数据资产
RAG API 示例
README 部署说明
```

## 二十、演示场景

### 场景 1：文档 + 图片检索

用户问：

```text
液压泵压力不足应该先检查哪里？
```

系统返回：

```text
维护手册中的相关段落
章节路径
页码
液压泵故障示意图 asset_url
```

### 场景 2：预设问题增强检索

用户问：

```text
设备压力上不去咋办？
```

系统通过 `preset_questions` 匹配到：

```text
液压泵压力不足怎么办？
液压系统压力不够应该先检查哪里？
```

并返回对应 Chunk。

### 场景 3：问数资产匹配

用户问：

```text
上个月华东区销售额同比增长多少？
```

系统返回：

```text
销售额指标口径
相关事实表
时间字段
区域字段
可用于 SQL 生成的字段信息
```

### 场景 4：Agent 自动路由

用户连续提出不同问题：

```text
液压泵压力不足怎么办？
销售额怎么算？
这个制度完整条款是什么？
```

Agent 分别调用：

```text
/rag/image-context
/rag/data-asset
/rag/parent-context
```

---

## 二十一、风险与控制

| 风险 | 控制方式 |
|:--|:--|
| Chunk 语义不完整 | 添加 title_context、section_path、summary |
| 用户问法和原文差异大 | 使用 preset_questions 增强匹配 |
| 图片无法被文本问题召回 | 保存 OCR、caption、description，并与 Chunk 关联 |
| 向量召回不稳定 | 后续增加 hybrid、rerank |
| Agent 误用知识 | RAG API 返回来源、分数、检索方法和证据包 |
| 表结构后续不够用 | data_assets 可拆为 data_tables / data_columns / metrics |

## 二十二、后续扩展方向

当基础流程跑通后，可以逐步扩展：

```text
kb_chunks.embedding
  拆成 chunk_embeddings

data_assets
  拆成 data_tables / data_columns / metrics

kb_documents.section_path
  拆成 doc_sections

kb_assets
  增加 media_embeddings

/rag/hybrid
  替换为 OpenSearch + BM25 + RRF

/rag/rerank
  替换为真实 Reranker

pgvector
  按规模迁移到 Qdrant / Milvus
```

## 二十三、总结

本模块的核心原则：

```text
少量核心表承载完整演示闭环；
Chunk 格式明确，保证可独立理解；
图片先存 URL、OCR 和描述，后续再做多模态；
预设问题先存在 Chunk 字段里，后续再独立建索引；
RAG 方法通过 API 预留；
Agent 层负责判断路由，不让数据库层承担业务推理。
```

第一阶段按 5 张表和 7 个 RAG 接口推进，可以完成一个可部署、可演示、可继续扩展的工厂管理系统知识检索底座。