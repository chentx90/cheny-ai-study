## 一 设计

1. 查询理解层
2. 路由决策层
3. 多索引召回层
4. 融合精排层
5. 证据压缩与校验层
6. Agent 知识服务接口层

## 二 流程

用户问题需求
｜
Query Analyzer：意图识别、实体、时间、领域、可靠性
｜
outer： 选择检索策略组合
｜
Retriever Pool：多路召回
｜
RRF / Rerank / Graph Expand:融合精排
｜
Evidence Builder：压缩、去重、溯源、置信度
｜
Knowledge Package：返回数据给Agent


### L1：简单问答 / 低风险查询

适合：

```text
定义解释
简单事实
内部文档普通查询
无需强溯源
```

推荐策略：

```text
Fusion：向量 + BM25
语义切分
摘要标题增强
轻量 Rerank
```

流程：

```text
query
  ↓
问题重写，可选
  ↓
向量检索 + BM25
  ↓
RRF融合
  ↓
TopK轻量Rerank
  ↓
返回答案 + 引用
```

对应你列的方法：

```text
1 简单RAG
2 语义切分
5 添加摘要标题
7 问题重写
8 Rerank
15 Fusion
```

### L2：分析型查询 / 中等风险任务

适合：

```text
数据分析解释
政策条款问答
技术方案比较
多文档综合
需要较强上下文
```

推荐策略：

```text
Fusion + 父文档召回 + 层次索引 + RSE滑窗 + 多召回压缩
```

流程：

```text
query
  ↓
Query Decompose：拆成子问题
  ↓
章节摘要层召回
  ↓
定位相关章节原文
  ↓
chunk召回 + 父文档扩展
  ↓
RSE连续窗口合并
  ↓
Rerank精排
  ↓
压缩成证据包
```

对应方法：

```text
3 父文档召回
4 上下文增强检索
9 RSE滑动窗口
10 多召回压缩
13 层次索引
15 Fusion
16 CRAG纠错
```

这档目标是：**信息完整，不断章取义。**

---

### L3：高可靠 / 工业决策级查询

适合：

```text
合规、法律、财务、医疗、工程安全
生产事故分析
复杂技术根因定位
跨系统知识推理
```

推荐策略：

```text
多步规划 + GraphRAG + CRAG + 自我增强检索 + 多智能体校验
```

流程：

```text
query
  ↓
任务风险识别
  ↓
规划检索子任务
  ↓
结构化检索：数据库 / 表格 / 文档 / 图谱
  ↓
GraphRAG扩展实体关系
  ↓
CRAG判断证据是否充分
  ↓
不足则二次召回 / 查询重写
  ↓
生成答案前做证据一致性检查
  ↓
输出结论、证据、置信度、缺口
```

对应方法：

```text
11 自我增强检索生成
12 GraphRAG
13 层次索引
15 Fusion
16 CRAG
多智能体配合
```

这档目标是： 宁可慢一点，也要可解释、可追溯、可质疑。 

**三、推荐的核心检索组合**

工业 Agent 的默认组合，我建议不是 16 个全开，而是这个“主干组合”：

```text
Fusion + Semantic Chunk + Metadata Context + Summary Index + Parent Recall + Rerank + CRAG
```

即：

```text
向量语义检索
+ BM25关键词检索
+ 语义切分
+ 元数据/物理位置上下文
+ 摘要标题增强
+ 父文档召回
+ 精排
+ 纠错判断
```

这是性价比最高的一组。

对应管线：

```text
1. 文档入库时：
   - 语义切分
   - 保留标题层级
   - 保留页码/章节/表格/图像/来源
   - 生成chunk摘要
   - 为chunk生成可能问题
   - 建立向量索引、BM25索引、摘要层索引、实体图谱索引

2. 查询时：
   - query重写
   - query分类
   - 多路召回
   - RRF融合
   - Rerank精排
   - 父文档/邻近窗口扩展
   - CRAG判断是否足够
   - 输出证据包
```

---

**四、知识库入库设计**

检索系统强不强，70% 在入库阶段。

每个 chunk 不应该只有正文，建议设计成：

```json
{
  "chunk_id": "doc_001_c023",
  "doc_id": "doc_001",
  "title": "设备维护手册",
  "section_path": "第三章 > 液压系统 > 故障排查",
  "summary": "本节说明液压泵压力异常的常见原因和处理步骤",
  "content": "原文chunk内容...",
  "questions": [
    "液压泵压力不足怎么办？",
    "液压系统压力波动的原因是什么？"
  ],
  "entities": ["液压泵", "压力阀", "过滤器"],
  "metadata": {
    "source": "maintenance_manual_v3.pdf",
    "page": 42,
    "created_at": "2026-06-01",
    "doc_type": "manual",
    "department": "设备运维",
    "security_level": "internal"
  },
  "parent_id": "doc_001_section_03_02",
  "prev_chunk_id": "doc_001_c022",
  "next_chunk_id": "doc_001_c024"
}
```

你列的这些方法里，最值得在入库阶段做的是：

```text
2 语义切分
4 添加物理位置上下文
5 添加摘要标题
6 为文本块设计问题
12 GraphRAG实体抽取
13 层次索引
```

这样查询时就不需要每次临时“猜上下文”。

---

**五、多路召回设计**

一次请求可以同时跑 5 条召回路：

```text
A. Dense Retriever：向量语义召回
B. Sparse Retriever：BM25关键词召回
C. Summary Retriever：章节摘要层召回
D. Question Retriever：假想问题/预生成问题召回
E. Graph Retriever：实体关系图谱召回
```

然后用 RRF 融合：

```text
final_score = RRF(dense_rank, bm25_rank, summary_rank, question_rank, graph_rank)
```

这样各自弥补短板：

|召回路|擅长|弱点|
|:--|:--|:--|
|向量检索|语义相似|容易漏关键词精确匹配|
|BM25|精确术语、编号、型号|不懂同义表达|
|摘要层|找章节、主题|粒度粗|
|问题索引|问答匹配强|依赖问题生成质量|
|GraphRAG|实体关系推理|构建成本高|

这是工业系统里很稳的一种“多路保险”。

---

**六、路由策略：不要所有问题都全量检索**

你可以设计一个 Query Router，根据任务类型选策略。

```text
Query Router 输出：
{
  "intent": "troubleshooting",
  "risk_level": "high",
  "need_structured_data": true,
  "need_citation": true,
  "need_graph": true,
  "time_sensitive": false,
  "retrieval_plan": ["fusion", "summary", "parent", "graph", "crag"]
}
```

路由规则示例：

|用户问题类型|推荐策略|
|:--|:--|
|“XX是什么”|Fusion + Rerank|
|“根据制度判断是否合规”|Fusion + ParentRecall + CRAG|
|“分析故障原因”|GraphRAG + 层次索引 + 多步检索|
|“查某个指标数据”|表匹配 + SQL/数据库访问 + 文档解释|
|“总结这份长文档”|层次索引 + RSE + 父文档|
|“找所有相关规定”|BM25 + 向量 + RRF + Expand|
|“给出高可靠结论”|CRAG + 自我增强检索 + 证据一致性检查|

---

**七、CRAG 纠错闭环**

CRAG 是工业 Agent 很关键的一层。它不是负责召回，而是负责判断：

```text
当前证据够不够？
有没有答非所问？
有没有来源冲突？
是否需要补充检索？
```

实现流程：

```text
召回证据
  ↓
Evidence Evaluator 判断
  ↓
结果分三类：
  1. Correct：证据充足，生成答案
  2. Ambiguous：证据不完整，补充检索
  3. Incorrect：召回跑偏，重写问题重新检索
```

可以让模型输出结构化判断：

```json
{
  "relevance": 0.72,
  "coverage": 0.58,
  "conflict": false,
  "missing_information": ["设备型号", "故障发生时间"],
  "next_action": "rewrite_and_retrieve"
}
```

这层能明显提升系统可靠性，特别适合工业场景。

---

**八、给 Agent 的返回格式**

不要只返回自然语言答案。工业 Agent 更需要“知识包”。

建议返回：

```json
{
  "answer": "根据维护手册，液压泵压力不足通常由过滤器堵塞、泄压阀异常或油液不足导致。",
  "confidence": 0.82,
  "evidence": [
    {
      "source": "设备维护手册V3.pdf",
      "page": 42,
      "section": "第三章 > 液压系统 > 故障排查",
      "quote": "液压泵压力不足时，应首先检查过滤器堵塞情况...",
      "score": 0.91
    }
  ],
  "missing_info": [
    "当前设备型号",
    "压力表读数",
    "最近维护记录"
  ],
  "suggested_next_steps": [
    "查询设备维护数据库",
    "检查过滤器状态",
    "核对液压油液位"
  ],
  "retrieval_trace": {
    "strategies": ["fusion", "parent_recall", "rerank", "crag"],
    "query_rewrites": ["液压泵压力不足原因", "液压系统压力异常排查"]
  }
}
```

这样工业 Agent 可以继续做任务编排，而不是只能读一段回答。

---

**九、一套推荐默认策略**

我建议你把系统预设成 4 个模式。

### `fast`

```text
Fusion + RRF + topK
```

用于普通问答。

### `balanced`

```text
Fusion + SummaryIndex + Rerank + ParentRecall
```

用于默认工业问答。

### `reliable`

```text
Fusion + SummaryIndex + ParentRecall + Rerank + CRAG
```

用于需要引用和判断的任务。

### `deep`

```text
Query Decompose + Fusion + GraphRAG + RSE + CRAG + Multi-agent Review
```

用于复杂分析、复盘、事故、合规。