# LangChain + LangGraph Agent 平台项目计划书

## 一、项目定位

本模块是工厂管理系统的智能体应用层，负责理解用户问题、规划任务、调用 RAG 检索服务、调用数据库查询工具，并输出可解释的分析结果。

Agent 平台不直接管理知识入库，也不直接维护向量索引。它通过标准接口调用 RAG API、数据库访问服务和业务工具，实现工厂管理场景下的智能问答、智能问数、故障分析、制度查询和多步任务编排。

## 二、建设目标

1. 使用 Python 作为主开发语言。
2. 使用 LangChain 封装模型、工具、检索器、Prompt 和输出解析。
3. 使用 LangGraph 构建可控的 Agent 状态机，避免无限循环和不可解释行为。
4. 支持基础问答、单步工具调用、单轮分析循环、多步规划。
5. 通过 RAG API 获取知识包，而不是直接访问向量数据库。
6. 通过数据库工具服务执行受控 SQL 查询，而不是让 Agent 直接连生产数据库。
7. 支持后续容器化部署，与数据库、RAG 服务分离。

## 三、系统边界

### 1. Agent 平台负责

- 用户意图识别
- 问题改写
- 任务分解
- 工具选择
- RAG API 调用
- 数据库查询工具调用
- 结果解释
- 证据引用
- 多步分析流程控制
- 输出结构化结果

### 2. Agent 平台不负责

- 文档解析和切分
- embedding 生成
- 向量索引写入
- 原始文件存储
- 业务数据库底层权限管理
- 前端页面实现

这些由 ingestion-service、rag-api-service、database-service、front-end 分别负责。

## 四、容器划分建议

```text
factory-agent-platform
  Python + LangChain + LangGraph
  对外提供 Agent API

factory-rag-api
  统一知识检索服务
  提供 /retrieve/documents、/retrieve/data-assets 等接口

factory-db-query-api
  受控数据库访问服务
  提供 SQL 校验、执行、结果返回

factory-postgres
  PostgreSQL + pgvector
  存 RAG 元数据、向量和项目业务演示数据

factory-ingestion
  文档清洗、图片 OCR、embedding、入库

factory-redis
  会话缓存、任务状态、短期记忆
```

调用关系：

```text
用户 / 前端
  ↓
Agent Platform
  ↓
RAG API / DB Query API / Tool API
  ↓
PostgreSQL / pgvector / MinIO / 业务数据库
```

## 五、Agent 能力层级

### L1：基础问答

适合：

```text
系统功能解释
普通知识问答
文档片段解释
```

流程：

```text
用户问题
  ↓
基础意图识别
  ↓
调用 RAG API
  ↓
根据证据生成回答
```

### L2：单步工具调用

适合：

```text
智能问数
匹配数据表
查询某个指标
检索某个制度条款
```

流程：

```text
用户问题
  ↓
判断是否需要工具
  ↓
调用 RAG API 匹配指标/表/字段
  ↓
调用数据库查询工具
  ↓
解释查询结果
```

### L3：单轮分析循环

适合：

```text
故障原因分析
质量异常分析
生产数据解释
```

流程：

```text
解读问题
  ↓
调用 RAG 或数据库工具
  ↓
分析返回结果
  ↓
判断信息是否足够
  ↓
不足则补充调用一次工具
  ↓
输出结论
```

### L4：多步规划

适合：

```text
跨部门问题分析
复杂异常复盘
制度 + 数据 + 案例综合判断
```

流程：

```text
任务分解
  ↓
多个子 Agent 或多个节点协作
  ↓
文档检索 / 数据查询 / 案例检索 / 规则校验
  ↓
证据汇总
  ↓
输出结构化报告
```

## 六、Agent 类型设计

### 1. RouterAgent

负责判断问题类型。

输出示例：

```json
{
  "intent": "data_analysis",
  "risk_level": "medium",
  "need_rag": true,
  "need_database": true,
  "need_image": false,
  "route": "data_agent"
}
```

问题类型：

```text
general_qa
document_qa
data_analysis
troubleshooting
quality_analysis
safety_compliance
tool_help
```

### 2. RAGAgent

负责调用 RAG API，获取知识包。

输入：

```json
{
  "query": "液压泵压力不足怎么办？",
  "mode": "balanced",
  "collections": ["docs_chunks", "media_assets"]
}
```

输出：

```json
{
  "evidence": [],
  "image_urls": [],
  "missing_info": [],
  "confidence": 0.82
}
```

### 3. DataAgent

负责智能问数。

核心流程：

```text
用户问题
  ↓
匹配指标口径
  ↓
匹配数据表
  ↓
匹配字段
  ↓
生成候选 SQL
  ↓
SQL 安全检查
  ↓
调用数据库访问服务
  ↓
解释结果
```

注意：

```text
Agent 不直接连接数据库。
Agent 只向 db-query-api 提交结构化查询请求。
db-query-api 负责白名单、权限、SQL 校验和执行。
```

### 4. TroubleshootingAgent

负责故障排查。

调用内容：

```text
设备手册
历史故障案例
维修记录
图片资料
传感器数据
```

输出：

```text
可能原因
证据来源
建议检查步骤
需要补充的信息
风险提示
```

### 5. ReportAgent

负责汇总结果，生成报告。

报告结构：

```text
问题背景
检索证据
数据结果
判断结论
建议措施
缺失信息
引用来源
```

## 七、LangGraph 状态机设计

### 1. 全局状态 AgentState

```python
from typing import TypedDict, List, Dict, Any, Optional

class AgentState(TypedDict):
    user_query: str
    intent: Optional[str]
    risk_level: Optional[str]
    plan: List[str]
    evidence: List[Dict[str, Any]]
    data_results: List[Dict[str, Any]]
    image_urls: List[str]
    missing_info: List[str]
    tool_calls: List[Dict[str, Any]]
    final_answer: Optional[str]
    error: Optional[str]
    loop_count: int
```

### 2. 节点设计

```text
analyze_query
  分析用户问题，判断意图、风险、是否需要工具

route_task
  决定进入 RAG、Data、Troubleshooting 或 General QA

retrieve_knowledge
  调用 RAG API 获取证据包

match_data_assets
  匹配指标、表、字段

generate_sql_request
  生成结构化 SQL 请求

execute_db_tool
  调用数据库工具服务

evaluate_evidence
  判断证据是否充分

answer
  生成最终回答

fallback
  信息不足或工具失败时输出保守结果
```

### 3. 图结构

```text
START
  ↓
analyze_query
  ↓
route_task
  ├── general_answer
  ├── retrieve_knowledge
  ├── match_data_assets
  └── troubleshooting_flow
        ↓
evaluate_evidence
  ├── enough → answer
  ├── need_more → retrieve_knowledge / execute_db_tool
  └── failed → fallback
```

### 4. 循环控制

为了避免 Agent 无限调用工具：

```text
loop_count <= 2：允许补充检索
loop_count > 2：停止调用，输出已有证据和缺失信息
```

## 八、工具接口设计

### 1. RAG 检索工具

```python
@tool
def retrieve_documents(query: str, mode: str = "balanced") -> dict:
    """Call RAG API to retrieve document evidence."""
```

对应 HTTP：

```text
POST /retrieve/documents
```

请求：

```json
{
  "query": "液压泵压力不足怎么办？",
  "mode": "balanced",
  "need_media": true
}
```

### 2. 数据资产匹配工具

```python
@tool
def retrieve_data_assets(query: str) -> dict:
    """Retrieve metrics, tables and columns for data analysis."""
```

对应 HTTP：

```text
POST /retrieve/data-assets
```

### 3. 数据库查询工具

```python
@tool
def execute_safe_query(sql_request: dict) -> dict:
    """Execute checked SQL request through db-query-api."""
```

注意：

```text
只允许 SELECT
禁止 DROP / DELETE / UPDATE / INSERT
必须带权限上下文
必须有 limit
复杂 SQL 先 explain 或 dry_run
```

### 4. 图片证据工具

第一阶段不需要单独做图片理解，可以直接使用 RAG 返回的 image_url。

后续扩展：

```python
@tool
def analyze_image(image_url: str, question: str) -> dict:
    """Use multimodal model to analyze image evidence."""
```

## 九、Prompt 设计原则

### 1. 工业问答要求

```text
不要编造来源
没有证据时明确说明缺少信息
优先返回可执行步骤
涉及安全、质量、设备风险时保守表达
输出结论、依据、建议、缺口
```

### 2. DataAgent 要求

```text
先解释指标口径，再解释数据结果
SQL 必须基于已匹配的表和字段
不能凭空创造字段名
查询失败时返回失败原因和需要补充的信息
```

### 3. 故障分析要求

```text
区分可能原因和已确认原因
给出检查优先级
引用手册、案例或数据证据
不要替代现场安全判断
```

## 十、接口返回格式

Agent 最终输出建议结构化。

```json
{
  "answer": "液压泵压力不足时，建议优先检查过滤器堵塞、油液液位和泄压阀状态。",
  "confidence": 0.82,
  "evidence": [
    {
      "source": "液压系统维护手册",
      "section": "故障排查",
      "page": 18,
      "quote": "压力不足时，应首先检查过滤器是否堵塞。"
    }
  ],
  "image_urls": [
    "http://minio:9000/factory/manuals/pump_fault_01.png"
  ],
  "data_results": [],
  "missing_info": [
    "设备型号",
    "当前压力表读数"
  ],
  "next_steps": [
    "检查过滤器状态",
    "核对液压油液位",
    "检查泄压阀是否异常"
  ]
}
```

## 十一、开发阶段计划

### 阶段 1：Agent 基础框架

- FastAPI Agent 服务
- LangChain 模型封装
- LangGraph 基础状态机
- RouterAgent
- General QA
- RAG API 工具封装

交付目标：

```text
用户提问后，Agent 能识别意图并调用 RAG API 回答。
```

### 阶段 2：DataAgent 智能问数

- 指标/表/字段匹配工具
- SQL 请求生成
- SQL 安全检查
- 数据库查询工具调用
- 查询结果解释

交付目标：

```text
用户问“上月销售额是多少”，Agent 能匹配指标和表，生成受控查询并解释结果。
```

### 阶段 3：故障分析 Agent

- 设备手册检索
- 历史案例检索
- 图片 URL 证据返回
- 检查步骤生成
- 信息不足判断

交付目标：

```text
用户问设备异常，Agent 能给出可能原因、证据、检查步骤和缺失信息。
```

### 阶段 4：多步规划与报告

- 多节点 LangGraph
- evidence evaluator
- 最多两轮补充检索
- ReportAgent
- 结构化报告输出

交付目标：

```text
Agent 能完成一个文档 + 数据 + 案例组合分析任务。
```

## 十二、项目目录建议

```text
factory-agent-platform/
  app/
    main.py
    config.py
    graph/
      state.py
      nodes.py
      edges.py
      builder.py
    agents/
      router_agent.py
      rag_agent.py
      data_agent.py
      troubleshooting_agent.py
      report_agent.py
    tools/
      rag_tools.py
      db_tools.py
      image_tools.py
    prompts/
      router.md
      data_agent.md
      troubleshooting.md
      report.md
    schemas/
      request.py
      response.py
      knowledge_package.py
  tests/
  Dockerfile
  pyproject.toml
  README.md
```

## 十三、API 设计

### 1. Agent 主接口

```text
POST /agent/chat
```

请求：

```json
{
  "query": "液压泵压力不足怎么办？",
  "user_id": "u001",
  "session_id": "s001",
  "mode": "balanced"
}
```

响应：

```json
{
  "answer": "...",
  "intent": "troubleshooting",
  "confidence": 0.82,
  "evidence": [],
  "image_urls": [],
  "missing_info": [],
  "trace_id": "uuid"
}
```

### 2. Agent 问数接口

```text
POST /agent/data-analysis
```

### 3. Agent 故障分析接口

```text
POST /agent/troubleshooting
```

## 十四、与 RAG 数据库模块的关系

Agent 平台只消费 RAG API。

```text
Agent Platform
  ↓
factory-rag-api
  ↓
PostgreSQL + pgvector
```

RAG API 返回：

```text
文本证据
图片 URL
章节路径
页码
指标口径
表字段信息
置信度
缺失信息
```

Agent 平台负责：

```text
判断是否够用
是否继续检索
是否调用数据库
如何生成最终答案
```

## 十五、演示场景

### 场景 1：文档问答

用户：

```text
液压泵压力不足应该怎么排查？
```

Agent：

```text
调用 RAG API
返回维护手册证据
给出检查步骤
附带图片 URL
```

### 场景 2：智能问数

用户：

```text
上个月华东区销售额同比增长多少？
```

Agent：

```text
匹配销售额指标
匹配订单事实表
匹配区域字段和时间字段
调用数据库查询工具
解释同比结果
```

### 场景 3：质量异常分析

用户：

```text
某批次不良率升高，帮我分析可能原因。
```

Agent：

```text
拆分任务
查询质量数据
检索质量制度和历史案例
输出可能原因、证据和下一步检查建议
```

### 场景 4：制度合规查询

用户：

```text
这个设备点检记录缺失是否违反要求？
```

Agent：

```text
检索点检制度
查询点检记录
对照规则输出判断
说明缺失证据
```

## 十六、技术选型

| 模块       | 技术                           |
| :------- | :--------------------------- |
| Agent 编排 | LangGraph                    |
| 工具封装     | LangChain Tools              |
| API 服务   | FastAPI                      |
| 数据校验     | Pydantic                     |
| HTTP 调用  | httpx                        |
| 会话缓存     | Redis                        |
| 模型接入     | OpenAI-compatible API / 本地模型 |
| 日志追踪     | structlog / OpenTelemetry    |
| 容器化      | Docker / Docker Compose      |

## 十七、风险与控制

| 风险 | 控制方式 |
|:--|:--|
| Agent 无限循环 | LangGraph 状态机 + loop_count 限制 |
| 工具误调用 | Router 节点 + 工具白名单 |
| SQL 风险 | db-query-api 校验，只允许 SELECT |
| 知识幻觉 | 必须引用 RAG evidence，没有证据则说明缺失 |
| 多工具结果冲突 | evidence evaluator 判断冲突和置信度 |
| 回答不可追溯 | 输出 trace_id、evidence、retrieval_trace |

## 十八、第一阶段最小可行目标

第一阶段只做四个闭环：

```text
1. 基础问答闭环
用户问题 → RAG API → Agent 回答

2. 图片证据闭环
用户问题 → RAG API → 文本证据 + image_url → Agent 回答

3. 智能问数闭环
用户问题 → 匹配指标表字段 → SQL 工具 → 数据解释

4. 故障分析闭环
用户问题 → 文档证据 + 案例证据 → 检查步骤
```

## 十九、总结

Agent 平台的核心不是让大模型自由发挥，而是把它限制在可解释、可追溯、可控工具调用的流程里。

设计原则：

```text
LangGraph 负责流程可控；
LangChain 负责工具和模型封装；
RAG API 负责知识检索；
DB Query API 负责安全查询；
Agent 负责理解、规划、调用和解释。
```

本项目先实现可部署、可演示、可扩展的工业 Agent 雏形，再逐步增加多智能体协作、GraphRAG、多模态图片理解和复杂分析报告能力。