# 后端模块

## 定位

RAG 系统的 API 网关与编排中心。提供检索、接入、知识管理三条主要链路，通过 FastAPI + asyncpg 对外服务。

## 目录结构

```
backend/
├── app/
│   ├── main.py               # 启动、lifespan（单连接池 → app.state.db）
│   ├── config.py             # Settings（pydantic-settings，读 .env）
│   │
│   ├── api/
│   │   ├── retrieve.py       # POST /retrieve, POST /retrieve/plan
│   │   ├── methods.py        # GET /methods, GET /methods/{id}, GET /operators
│   │   ├── system.py         # GET /health, GET /capabilities, GET /strategies
│   │   ├── ingestion.py      # /ingestion/* 接入管道
│   │   └── knowledge.py      # /knowledge/* 知识库管理 CRUD
│   │
│   ├── core/
│   │   ├── schemas.py        # 全部领域类型（RetrieveRequest, KnowledgePackage …）
│   │   ├── chunker.py        # 文本分块器（max_chars / overlap）
│   │   ├── services/embedding_client.py # 第三方 API embedding 客户端
│   │   ├── execution_engine.py  # 按 steps 顺序运行算子，记录 trace
│   │   ├── method_loader.py  # 从磁盘加载 methods/*.json
│   │   ├── method_resolver.py   # 显式method > mode > intent 推断 > 默认
│   │   ├── registry.py       # CapabilityRegistryService + adapter 注册
│   │   └── planner.py        # STRATEGY_CATALOG，mode → strategy 映射
│   │
│   ├── operators/            # 单步检索算子
│   │   ├── vector_search.py      # pgvector <=> 余弦距离
│   │   ├── parent_expand.py      # chunk → parent_doc 展开
│   │   ├── asset_fetch.py        # 关联图片/附件资产
│   │   └── data_asset_search.py  # 结构化数据资产检索
│   │
│   ├── adapters/
│   │   ├── base.py           # BaseAdapter（检索接口契约）
│   │   ├── postgres.py       # 检索 + 知识管理方法（接受共享 pool）
│   │   └── mock.py           # 内存 mock，单元测试用
│   │
│   ├── services/
│   │   ├── ingestion_service.py  # 编排：任务生命周期 + 后台任务调度
│   │   ├── parse_service.py      # 无状态：文件 → ParsedDoc dict（调 ingestion 库）
│   │   ├── commit_service.py     # 无状态：去重 / 归档 / 同名序号（DB 操作）
│   │   ├── db_writer.py          # 无状态：INSERT kb_documents / kb_chunks / data_assets
│   │   ├── llm_enrich.py         # LLM 富化（摘要/预设问题/标题提取）
│   │   ├── doc_identity.py       # normalize_text / compute_content_hash / derive_title
│   │   ├── upload_service.py     # 文件存储（本地磁盘）
│   │   └── ingestion_job_store.py # 任务状态 CRUD（asyncpg）
│   │
│   └── methods/              # 检索方法 JSON 配置
│       ├── document_vector_v1.json
│       ├── document_context_v1.json
│       ├── equipment_troubleshooting_v1.json
│       └── data_asset_lookup_v1.json
│
└── tests/
    ├── test_api.py           # 检索 API 单元测试
    └── test_ingestion_e2e.py # 接入全链路端到端测试
```

## 检索请求链路

```
POST /api/retrieve
  └─ retrieve.py
       ├─ method_resolver.resolve_method()   # 确定 method_id
       ├─ method_loader.load_method()        # 加载 JSON → RetrievalMethod
       ├─ ExecutionEngine.run()
       │    └─ for step in method.steps:
       │         operator.execute(ctx)       # e.g. vector_search → SQL
       └─ 返回 KnowledgePackage{evidence, assets, data_assets, trace}
```

## 接入服务分层

```
POST /api/ingestion/jobs/{id}/commit
  └─ ingestion.py → IngestionService.run_commit()
       ├─ parse_service.parse()             # 文件 → ParsedDoc（chunks, doc 元数据）
       ├─ doc_identity.compute_content_hash()  # SHA256(归一化正文 + domain)
       ├─ commit_service.check_duplicate()  # 查 content_hash → 409 / replace / new
       ├─ commit_service.resolve_title()    # 查同名 → 追加 (2)(3)
       └─ db_writer.write()                 # INSERT kb_documents + kb_chunks
```

## 关键设计决策

**连接池**：全应用共享一个 `asyncpg.Pool`，通过 `app.state.db` 传递给所有服务，消除多池并发问题。

**依赖注入**：路由通过 `Depends(get_ingestion_service)` 获取服务实例，无 module-level global，方便测试替换。

**去重语义**：`commit` 支持 `on_duplicate=block|replace|new`；`block`（默认）命中返回 HTTP 409 含已有文档 id/title；`replace` 旧文档归档（`status=archived`），检索层只读 `active`。

**方法优先级**：`显式 method > 显式 mode > intent 推断 > 默认`

## 运行测试

```bash
cd backend
python -m pytest tests/ -v
```

## 方法配置格式

```json
{
  "method_id": "document_vector_v1",
  "description": "普通文档向量检索",
  "steps": [
    {
      "name": "chunk_vector",
      "operator": "vector_search",
      "backend": "postgres_pgvector",
      "params": {"top_k": 5}
    }
  ]
}
```
