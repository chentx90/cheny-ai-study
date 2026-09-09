生产级 RAG Pipeline 搭建指南
从零到生产的完整工程路径，按实际搭建顺序展开。

第零步：架构选型决策
在动手之前，先回答这几个问题，决定整个系统走向：
┌─────────────────────────────────────────────────────┐
│                  架构决策矩阵                         │
├──────────────┬──────────────────────────────────────┤
│ 数据规模      │ <10万文档 → 单机方案                   │
│              │ 10万~1000万 → 分布式向量库              │
│              │ >1000万 → 分层索引 + 图谱              │
├──────────────┼──────────────────────────────────────┤
│ 数据类型      │ 纯文本 → 标准 pipeline                │
│              │ 含表格/图片 → 多模态 pipeline           │
│              │ 含代码 → AST 感知分块                  │
├──────────────┼──────────────────────────────────────┤
│ 更新频率      │ 低频(天/周) → 批量重建                  │
│              │ 中频(小时) → 增量索引                   │
│              │ 高频(分钟) → 流式管线                   │
├──────────────┼──────────────────────────────────────┤
│ 延迟要求      │ >2s → 异步全流程                      │
│              │ <1s → 缓存 + 预计算                    │
│              │ <500ms → 流式检索 + 流式生成            │
├──────────────┼──────────────────────────────────────┤
│ 准确度要求    │ 一般 → 简单 top-K                     │
│              │ 高 → 混合检索 + Rerank                 │
│              │ 极高 → Agentic RAG + 人工兜底          │
└──────────────┴──────────────────────────────────────┘

第一步：数据接入与预处理
1.1 文档加载器设计
生产环境面对的是异构数据源，需要统一抽象：
from abc import ABC, abstractmethod

class DocumentLoader(ABC):
    """统一文档加载接口"""
    @abstractmethod
    def load(self, source: str) -> list[Document]:
        """返回 Document 列表，每个 Document 包含:
        - content: 文本内容
        - metadata: 来源、页码、时间、类型等
        """
        pass

# 实现示例
class PDFLoader(DocumentLoader):
    def load(self, source: str) -> list[Document]:
        # 推荐: UnstructuredIO / Docling / MinerU
        # 重点: 表格提取、图片OCR、版面保留
        pass

class WebLoader(DocumentLoader):
    def load(self, source: str) -> list[Document]:
        # 处理 JS 渲染、反爬、正文提取
        pass

class DatabaseLoader(DocumentLoader):
    def load(self, source: str) -> list[Document]:
        # 结构化数据 → 自然语言模板填充
        pass

生产要点：

每个文档必须携带来源元数据（文件路径、页码、URL、时间戳），用于最终溯源
建立文档指纹（hash），用于增量更新时的变更检测
异常文档隔离，不阻塞整个管线

1.2 清洗 Pipeline
class CleaningPipeline:
    def __init__(self):
        self.steps = [
            self.remove_headers_footers,   # 去页眉页脚
            self.normalize_whitespace,      # 规范化空白
            self.remove_boilerplate,        # 去样板内容
            self.deduplicate,               # 去重
            self.detect_language,           # 语言标注
            self.pii_mask,                  # 敏感信息脱敏
        ]
    
    def run(self, docs: list[Document]) -> list[Document]:
        for step in self.steps:
            docs = step(docs)
        return docs

第二步：分块（Chunking）—— 最关键的一步

分块质量直接决定检索上限。这里做不好，后面所有优化都是补救。

2.1 推荐的分层分块策略
class HierarchicalChunker:
    """分层分块：大块用于上下文理解，小块用于精准检索"""
    
    def chunk(self, document: Document) -> list[Chunk]:
        # Level 1: 按章节/标题切分（大块，保留完整语境）
        sections = self.split_by_heading(document)
        
        chunks = []
        for section in sections:
            # Level 2: 按段落切分（中块）
            paragraphs = self.split_by_paragraph(section)
            
            for para in paragraphs:
                # Level 3: 按句子/语义切分（小块，用于精确匹配）
                if len(para.content) > self.max_chunk_size:
                    sub_chunks = self.recursive_split(para)
                    chunks.extend(sub_chunks)
                else:
                    chunks.append(para)
        
        return chunks

2.2 分块参数经验值
┌─────────────────┬────────────┬──────────┬──────────────────────┐
│ 场景            │ chunk_size │ overlap  │ 说明                  │
├─────────────────┼────────────┼──────────┼──────────────────────┤
│ 通用问答        │ 512 tokens │ 64       │ 平衡召回与精度         │
│ 精准事实问答    │ 256 tokens │ 32       │ 小块更精确             │
│ 长文档摘要      │ 1024 tokens│ 128      │ 大块保留更多上下文      │
│ 代码           │ 函数/类级   │ 2-3行    │ 按 AST 边界           │
│ 表格           │ 整表为一块  │ 0        │ 表格不可切割           │
│ 对话记录       │ 会话级      │ 1-2轮    │ 按对话轮次             │
└─────────────────┴────────────┴──────────┴──────────────────────┘

2.3 元数据增强
每个 chunk 除了文本，还要携带丰富的元数据：
chunk.metadata = {
    "source": "product_manual_v3.pdf",
    "page": 42,
    "heading": "支付接口说明",
    "heading_level": 2,
    "doc_type": "technical_doc",
    "language": "zh",
    "created_at": "2026-01-15",
    "chunk_index": 137,       # 在文档中的位置
    "parent_chunk_id": "xxx", # 父级大块引用
    "token_count": 380,
}

第三步：Embedding 向量化
3.1 模型选型决策树
你的场景是？
├── 通用场景（中英文混合）
│   ├── 预算充足 → text-embedding-3-large (OpenAI)
│   └── 需要本地部署 → BGE-large-zh-v1.5 / GTE-large
├── 特定领域（医疗/法律/金融）
│   └── 通用模型 + 领域微调（1000-10000条标注数据即可显著提升）
├── 多语言
│   └── BGE-M3 / multilingual-e5-large
└── 多模态（图+文）
    └── CLIP / SigLIP + 文本 Embedding 联合

3.2 Embedding 服务化
# 生产环境必须服务化，不能每次调用都加载模型
class EmbeddingService:
    def __init__(self, model_name: str, batch_size: int = 64):
        self.model = load_model(model_name)
        self.batch_size = batch_size
        self.cache = LRUCache(maxsize=10000)  # 语义缓存
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        # 1. 查缓存
        cached, uncached_indices, uncached_texts = self._check_cache(texts)
        
        # 2. 批量编码未缓存的文本
        if uncached_texts:
            embeddings = self.model.encode(
                uncached_texts, 
                batch_size=self.batch_size,
                normalize_embeddings=True  # 归一化，用内积即余弦相似度
            )
            self._update_cache(uncached_texts, embeddings)
        
        # 3. 合并返回
        return self._merge_results(cached, embeddings, uncached_indices)

关键点：

批量处理（batch），不要逐条调用
归一化向量（normalize），后续检索直接用内积，速度快
向量维度记录：不同模型维度不同，混用会崩

第四步：向量存储与索引
4.1 向量库部署架构
                    ┌──────────────┐
                    │   应用层      │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  检索代理层   │  ← 查询路由、缓存、限流
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ 向量DB    │ │ BM25索引  │ │ 图数据库  │
        │(Milvus)  │ │(Elastic) │ │(Neo4j)   │
        └──────────┘ └──────────┘ └──────────┘

4.2 Milvus 生产配置示例
from pymilvus import Collection, FieldSchema, CollectionSchema, DataType

# Schema 设计
fields = [
    FieldSchema("id", DataType.INT64, is_primary=True, auto_id=True),
    FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=1024),
    FieldSchema("content", DataType.VARCHAR, max_length=8192),
    FieldSchema("source", DataType.VARCHAR, max_length=512),
    FieldSchema("doc_type", DataType.VARCHAR, max_length=64),
    FieldSchema("created_at", DataType.INT64),  # 时间戳，用于过滤
]

schema = CollectionSchema(fields)

# 索引选择
index_params = {
    "index_type": "HNSW",      # 生产推荐 HNSW
    "metric_type": "COSINE",   # 归一化后用 COSINE 或 IP
    "params": {
        "M": 16,               # 每个节点的连接数，16-64
        "efConstruction": 200  # 构建时搜索范围，越大越准
    }
}

# 搜索时的参数
search_params = {
    "metric_type": "COSINE",
    "params": {"ef": 128}  # 搜索时的精度控制，越大越准但越慢
}

4.3 生产环境配置要点
┌────────────────────────────────────────────────────┐
│                 Milvus 生产配置                      │
├─────────────────┬──────────────────────────────────┤
│ 硬件             │ 向量检索是内存密集型               │
│                 │ 内存 ≥ 向量数据总量的 1.5 倍       │
│                 │ SSD 用于 WAL 持久化               │
├─────────────────┼──────────────────────────────────┤
│ 分片策略         │ 按业务/租户分 collection          │
│                 │ 大表用 partition 按时间分区         │
├─────────────────┼──────────────────────────────────┤
│ 备份             │ 定期快照 + 对象存储备份            │
│                 │ 跨 AZ 副本（Milvus Cloud 自带）    │
├─────────────────┼──────────────────────────────────┤
│ 监控             │ 查询延迟 P50/P99                  │
│                 │ 内存使用率                        │
│                 │ 索引构建进度                      │
└─────────────────┴──────────────────────────────────┘

第五步：检索策略 —— 核心竞争力
5.1 混合检索实现
class HybridRetriever:
    """稠密 + 稀疏 + 元数据过滤的混合检索"""
    
    async def retrieve(
        self, 
        query: str, 
        filters: dict = None,
        top_k: int = 20
    ) -> list[RetrievalResult]:
        
        # 1. 查询改写（可选）
        rewritten_queries = await self.query_rewriter.rewrite(query)
        
        # 2. 并发执行多种检索
        dense_task = self.dense_search(rewritten_queries, filters, top_k)
        sparse_task = self.sparse_search(query, filters, top_k)
        
        dense_results, sparse_results = await asyncio.gather(
            dense_task, sparse_task
        )
        
        # 3. 融合排序 (RRF)
        fused = self.reciprocal_rank_fusion(
            [dense_results, sparse_results],
            k=60  # RRF 常数，通常 30-60
        )
        
        return fused[:top_k]
    
    def reciprocal_rank_fusion(
        self, 
        result_lists: list[list], 
        k: int = 60
    ) -> list:
        """RRF 融合：score = Σ 1/(k + rank_i)"""
        scores = {}
        for results in result_lists:
            for rank, doc in enumerate(results):
                doc_id = doc.id
                scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
        
        # 按融合分数排序
        sorted_ids = sorted(scores, key=scores.get, reverse=True)
        return [self.doc_map[id] for id in sorted_ids]

5.2 查询改写策略
class QueryRewriter:
    """查询改写是提升召回率最有效的手段之一"""
    
    async def rewrite(self, query: str) -> list[str]:
        strategies = await asyncio.gather(
            self.hyde(query),           # 假设性文档
            self.multi_query(query),    # 多角度扩展
            self.keyword_extract(query) # 关键词提取
        )
        
        # 合并去重
        all_queries = [query]  # 原始 query 保留
        for strategy_results in strategies:
            all_queries.extend(strategy_results)
        
        return list(set(all_queries))
    
    async def hyde(self, query: str) -> list[str]:
        """HyDE: 让 LLM 生成假设性答案，用答案去检索"""
        prompt = f"请回答以下问题（200字以内）：{query}"
        hypothetical_answer = await self.llm.generate(prompt)
        return [hypothetical_answer]
    
    async def multi_query(self, query: str) -> list[str]:
        """多角度查询扩展"""
        prompt = f"""将以下问题从3个不同角度重新表述，每行一个：
原始问题：{query}"""
        result = await self.llm.generate(prompt)
        return result.strip().split('\n')

5.3 Reranking（重排序）
class Reranker:
    """二阶段检索：粗召回 → 精排"""
    
    def __init__(self):
        # Cross-Encoder 精排模型
        self.model = CrossEncoder("BAAI/bge-reranker-v2-m3")
    
    async def rerank(
        self, 
        query: str, 
        documents: list[str], 
        top_n: int = 5
    ) -> list[tuple[str, float]]:
        
        # 构造 query-doc 对
        pairs = [(query, doc) for doc in documents]
        
        # Cross-Encoder 打分
        scores = self.model.predict(pairs)
        
        # 按分数排序
        scored_docs = sorted(
            zip(documents, scores), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        return scored_docs[:top_n]

生产建议：

粗召回取 top_2050，Rerank 后取 top_310 送入 LLM
Reranker 比 Embedding 模型慢 10-100 倍，必须控制输入数量
可以用轻量 Reranker（如 FlashRank）做第一轮，重量级模型做第二轮

第六步：生成与引用
6.1 Prompt 模板
RAG_PROMPT = """你是一个专业的知识助手。请严格基于以下参考文档回答用户问题。

## 规则
1. 仅使用参考文档中的信息回答，不要编造
2. 如果文档中没有相关信息，明确说"根据现有资料无法回答"
3. 在回答中标注信息来源，格式：[来源X]
4. 如有多个文档信息冲突，指出差异

## 参考文档
{contexts}

## 用户问题
{question}

## 回答"""

6.2 引用溯源实现
class CitationGenerator:
    async def generate_with_citation(
        self, 
        query: str, 
        contexts: list[RetrievalResult]
    ) -> AsyncGenerator[str, None]:
        
        # 构造带编号的上下文
        formatted_contexts = ""
        for i, ctx in enumerate(contexts, 1):
            source = ctx.metadata.get("source", "未知来源")
            page = ctx.metadata.get("page", "")
            formatted_contexts += f"[来源{i}] ({source}, p.{page})\n{ctx.content}\n\n"
        
        prompt = RAG_PROMPT.format(
            contexts=formatted_contexts, 
            question=query
        )
        
        # 流式生成
        async for chunk in self.llm.stream_generate(prompt):
            yield chunk
        
        # 生成后校验：引用的来源是否存在
        # 生成后校验：回答是否真的基于上下文（faithfulness check）

第七步：质量保障体系
7.1 评估 Pipeline
class RAGEvaluator:
    """生产级评估框架"""
    
    async def evaluate(self, qa_pairs: list[dict]) -> dict:
        results = {
            "retrieval": await self.eval_retrieval(qa_pairs),
            "generation": await self.eval_generation(qa_pairs),
            "end_to_end": await self.eval_e2e(qa_pairs),
        }
        return results
    
    async def eval_retrieval(self, qa_pairs):
        """检索质量评估"""
        metrics = {
            "recall_at_5": 0,    # 前5个结果中命中相关文档的比例
            "mrr": 0,            # 第一个正确结果的排名
            "ndcg_at_10": 0,     # 考虑位置的排序质量
        }
        # ... 计算逻辑
        return metrics
    
    async def eval_generation(self, qa_pairs):
        """生成质量评估（LLM-as-Judge）"""
        metrics = {
            "faithfulness": 0,    # 回答是否忠于上下文
            "relevancy": 0,       # 回答是否切题
            "completeness": 0,    # 回答是否完整
        }
        # 用强模型评估弱模型的输出
        return metrics

7.2 Golden Set 构建
Golden Set = [
    {
        "question": "产品A的退货政策是什么？",
        "ground_truth": "30天内无理由退货...",
        "relevant_docs": ["policy_doc.pdf#page12", "faq.md#section3"],
        "difficulty": "easy",
        "category": "售后政策"
    },
    # ... 100-500 条，覆盖核心场景
]

构建方法：

从真实用户日志中采样高频问题
让领域专家标注标准答案和相关文档
覆盖不同难度（单文档事实 → 多文档推理 → 无法回答）
定期更新，随数据源变化而迭代

7.3 在线监控指标
┌──────────────────┬──────────────────────────────────┐
│ 指标              │ 采集方式                          │
├──────────────────┼──────────────────────────────────┤
│ 端到端延迟 P50/P99│ APM (LangSmith/Phoenix)          │
│ 检索召回率        │ 用户反馈（👍👎）+ 抽样人工评估     │
│ 幻觉率           │ LLM-as-Judge 定期抽检             │
│ "无法回答"比例    │ 统计触发兜底的回答占比             │
│ 重试率           │ 用户追问/重新提问的比例            │
│ Token 消耗       │ 按请求统计，设置预算告警            │
│ 向量库查询延迟    │ 数据库原生监控                    │
│ 缓存命中率       │ 缓存层统计                        │
└──────────────────┴──────────────────────────────────┘

第八步：生产加固
8.1 缓存策略
class SemanticCache:
    """语义缓存：相似问题直接返回缓存结果"""
    
    def __init__(self, threshold=0.95):
        self.cache = VectorStore()  # 缓存用独立的小向量库
        self.threshold = threshold
    
    async def get_or_compute(self, query: str, compute_fn):
        # 1. 用 query embedding 在缓存中搜索
        cached = await self.cache.search(
            embedding=embed(query), 
            top_k=1, 
            threshold=self.threshold
        )
        
        if cached:
            return cached[0].response  # 缓存命中
        
        # 2. 缓存未命中，执行完整 pipeline
        response = await compute_fn(query)
        
        # 3. 写入缓存
        await self.cache.insert(
            embedding=embed(query),
            response=response,
            metadata={"cached_at": time.time()}
        )
        
        return response

8.2 限流与降级
class RAGWithFallback:
    """带降级策略的 RAG"""
    
    async def query(self, question: str) -> Response:
        try:
            # Tier 1: 完整 pipeline（混合检索 + Rerank + LLM）
            return await self.full_pipeline(question)
        except TimeoutError:
            # Tier 2: 降级为纯向量检索（跳过 Rerank）
            return await self.simple_retrieval(question)
        except VectorDBError:
            # Tier 3: 降级为纯 LLM（无检索）
            return await self.llm_only(question)
        except Exception:
            # Tier 4: 兜底
            return Response("系统暂时繁忙，请稍后重试")

8.3 增量更新机制
class IncrementalIndexer:
    """增量索引更新"""
    
    async def sync(self, data_source: str):
        # 1. 检测变更
        current_fingerprints = await self.scan_source(data_source)
        stored_fingerprints = await self.get_stored_fingerprints(data_source)
        
        # 2. 计算差异
        to_add = current_fingerprints - stored_fingerprints
        to_delete = stored_fingerprints - current_fingerprints
        to_update = self.detect_modifications(current_fingerprints, stored_fingerprints)
        
        # 3. 执行更新
        for doc in to_delete:
            await self.vector_store.delete_by_filter({"doc_id": doc.id})
        
        for doc in to_add:
            chunks = self.chunker.chunk(doc)
            embeddings = await self.embedder.embed([c.content for c in chunks])
            await self.vector_store.insert(chunks, embeddings)
        
        for doc in to_update:
            await self.delete_and_reindex(doc)
        
        # 4. 记录同步状态
        await self.save_sync_checkpoint(data_source, time.time())

第九步：完整 Pipeline 编排
class ProductionRAGPipeline:
    """生产级 RAG Pipeline 总控"""
    
    def __init__(self):
        self.cache = SemanticCache(threshold=0.95)
        self.query_rewriter = QueryRewriter()
        self.retriever = HybridRetriever()
        self.reranker = Reranker()
        self.generator = CitationGenerator()
        self.evaluator = OnlineEvaluator()
    
    async def query(self, question: str, user_context: dict = None) -> Response:
        
        # 0. 语义缓存检查
        cached = await self.cache.get(question)
        if cached:
            return cached
        
        # 1. 查询改写
        queries = await self.query_rewriter.rewrite(question)
        
        # 2. 混合检索
        candidates = await self.retriever.retrieve(
            queries=queries,
            filters=user_context.get("filters"),
            top_k=30
        )
        
        # 3. Rerank 精排
        reranked = await self.reranker.rerank(
            query=question,
            documents=candidates,
            top_n=5
        )
        
        # 4. 生成回答（流式）
        response = self.generator.generate_with_citation(
            query=question,
            contexts=reranked
        )
        
        # 5. 异步质量监控（不阻塞响应）
        asyncio.create_task(
            self.evaluator.log_and_evaluate(question, reranked, response)
        )
        
        # 6. 写入缓存
        await self.cache.set(question, response)
        
        return response

最终：生产上线 Checklist
数据层
  □ 文档解析覆盖所有数据源格式
  □ 分块策略经过 A/B 测试验证
  □ 元数据完整（来源、页码、时间）
  □ 增量更新机制就绪

检索层
  □ 混合检索（稠密 + 稀疏）已实现
  □ Reranker 已集成并调参
  □ 查询改写策略已验证
  □ 向量库有备份和监控

生成层
  □ Prompt 模板经过多场景测试
  □ 引用溯源可工作
  □ 流式输出已实现
  □ 防幻觉约束已加入

质量层
  □ Golden Set（≥100条）已构建
  □ 离线评估指标达标（Recall@5 ≥ 0.8, Faithfulness ≥ 0.85）
  □ 在线监控看板已搭建
  □ 用户反馈通道已打通

运维层
  □ 语义缓存已启用
  □ 限流和降级策略已实现
  □ Token 消耗有预算告警
  □ 端到端延迟 P99 < 3s（或满足业务 SLA）
  □ 日志和 tracing 完整

这是一条从数据到回答的完整工程路径。每个环节都有大量可调旋钮，生产环境中的差距往往不在于用了多花哨的算法，而在于这些基础环节是否做得扎实。
你想深入哪个环节？比如分块策略的调优、Reranker 的选型对比、或者评估体系的具体搭建，都可以继续展开。