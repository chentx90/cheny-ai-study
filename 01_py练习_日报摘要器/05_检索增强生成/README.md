# Retrieval-Augmented Generation Project Framework

## 1. Project Goal

This project builds a modular RAG system for learning, demonstration, and future industrial-style extension.

The system is designed around decoupling:

```text
Frontend
  ↓
Backend / RAG Gateway
  ↓
Retrieval Strategies
  ↓
Storage Adapters
  ↓
Databases / Indexes / Object Storage
```

Each module can run independently in a container and communicate through stable APIs.

## 2. Module Layout

```text
05_检索增强生成/
  frontend/
    frontend_project_plan.md
    module_framework.md

  backend/
    backend_project_plan.md
    module_framework.md

  database/
    database_project_plan.md
    module_framework.md

  ingestion/
    ingestion_project_plan.md
    module_framework.md
    README.md                    # ← ingestion 模块详细文档

  evaluation/
    evaluation_project_plan.md
    module_framework.md

  docs/
     7_RAG解耦总体架构.md
     8_数据接入与清洗入库模块.md
     9_存储与索引适配器模块.md
     10_召回策略模块.md
     11_RAG编排网关与Agent路由模块.md
     12_容器化部署与模块边界.md
```

## 3. Module Responsibilities

| Module | Responsibility |
|:--|:--|
| frontend | Retrieval playground, evidence display, trace viewer, evaluation UI |
| backend | Unified `/retrieve`, query planning, strategy orchestration, adapter routing |
| database | PostgreSQL + pgvector schema, seed data, indexes, demo SQL |
| **ingestion** | **Parse raw materials, chunk text, create preset questions, generate embeddings** |
| evaluation | Test retrieval quality, compare strategies, produce reports |

## 4. Ingestion Module — Deep Dive

### 4.1 模块定位

Ingestion 模块是本 RAG 系统的**数据接入与解析层**，负责将各类原始文件（PDF、Markdown、Excel、TXT、DOCX、PPTX、JSON 种子文件）解析为结构化的数据对象，供后端存储层消费。

模块区分两种运行模式：

- **独立运行**：本模块自带 `writers/PostgresWriter` 和 `writers/JsonWriter`，可直接在命令行运行，用于本地开发、数据预览和快照测试。
- **被后端集成**：后端通过 `backend/app/services/db_writer.py`（共享数据库连接池）直接调用本模块的 Loader 和 Processor，不依赖 `writers/`。

### 4.2 输入输出契约

```
原始文件（PDF / Markdown / Excel / ...）
  │
  ▼ app/loaders/
  LoadedDocument { pages: List[RawPage] }        ← 文件类 Loader 输出
  ↓ 或 ↓
  Document { title, doc_type, chunks: List[Chunk] }  ← 种子 Loader 输出
  │
  ▼ app/processors/chunker.py
  List[Chunk] { section_path, title_context, content, summary, preset_questions, physical_context }
  │
  ▼ app/processors/summarizer.py
  Chunk.summary = 自动摘要（前两句，≤200字符)
  │
  ▼ app/embeddings/
  Chunk + embedding vector（1536维，可替换为生产服务)
```

### 4.3 核心数据结构

#### Chunk — 文本分块（向量化的最小单元）

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `section_path` | `str` | 章节路径，如 "第一章 > 1.1 液压系统" |
| `title_context` | `str` | 标题上下文（文档/章节标题） |
| `content` | `str` | 原始正文内容 |
| `summary` | `str` | 自动摘要（前两句） |
| `preset_questions` | `List[str]` | 预设问题列表 |
| `physical_context` | `Dict[str, Any]` | 原始文件位置信息 `{"page": 5}` |

#### DataAsset — 结构化数据资产

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `asset_type` | `str` | 类型："table"/"column"/"metric"/"case"/"tool" |
| `name` | `str` | 资产标准名称 |
| `description` | `str` | 业务含义描述 |
| `business_domain` | `str` | 所属业务领域 |
| `parent_name` | `Optional[str]` | 父级资产（如某列所属表） |
| `synonyms` | `List[str]` | 同义词列表 |
| `formula` | `Optional[str]` | 计算公式（仅 metric） |
| `related_table` | `Optional[str]` | 关联表名 |
| `related_columns` | `List[str]` | 关联字段名列表 |

#### Document — 文档模型

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `title` | `str` | 文档标题 |
| `doc_type` | `str` | 文档类型："markdown"/"pdf"/"excel"/"manual"等 |
| `source_uri` | `Optional[str]` | 原始文件路径/URL |
| `business_domain` | `Optional[str]` | 业务领域 |
| `version` | `Optional[str]` | 文档版本号 |
| `chunks` | `List[Chunk]` | 文本分块列表 |

### 4.4 目录详解

```
ingestion/app/
  config.py                # Pydantic Settings（独立运行时的 DB/EMB 配置）
  schemas.py               # Pydantic 数据模型（Document / Chunk / DataAsset / Asset）
  schemas/__init__.py      # re-export 入口

  main.py                  # ingest_document / ingest_data_asset 顶层编排函数

  loaders/
    __init__.py            # re-export 所有 Loader
    base.py                # BaseLoader 抽象基类（load 接口）
    pdf.py                 # PdfLoader：PyMuPDF，支持 OCR / 结构化模式
    markdown.py            # MarkdownLoader：解析 Markdown 标题层级，自动分节分块
    excel.py               # ExcelLoader：双模式（data_asset 结构化 / text 文本化）
    txt.py                 # TxtLoader：纯文本，最简加载器
    docx.py                # DocxLoader：保留 Heading 层级，转 Markdown 标记
    pptx.py                # PptxLoader：逐幻灯片提取文本
    seed.py                # JSON 种子文件加载（load_json_seed / load_data_assets_seed）

  processors/
    __init__.py            # re-export 所有 Processor
    chunker.py             # Chunker：段落拆分，300-800字符/Chunk
    summarizer.py          # Summarizer：取前两句，≤200字符
    question_generator.py  # QuestionGenerator：规则预设问题（已被 LLM 富化取代）
    embedding_builder.py   # EmbeddingBuilder：构建 embedding 文本并编码
    data_asset_builder.py  # DataAssetBuilder：Excel 行数据 → DataAsset 对象

  embeddings/
    __init__.py            # re-export BaseEmbedding / MockEmbedding
    base.py                # BaseEmbedding 抽象接口
    mock.py                # MockEmbedding：SHA256 Seed + random，1536维确定性向量

  writers/
    __init__.py            # re-export PostgresWriter / JsonWriter
    base.py                # BaseWriter 抽象基类（connect / close 接口）
    postgres.py            # PostgresWriter：asyncpg 异步写库（独立 CLI 用）
    json.py                # JsonWriter：JSON 文件预览（开发调试 / 快照测试用）
```

### 4.5 文件加载器说明

| 加载器 | 输入格式 | 输出类型 | 特殊处理 |
|:--|:--|:--|:--|
| `PdfLoader` | `.pdf` | `LoadedDocument` | OCR 回退、结构化模式（字体大小推断标题） |
| `MarkdownLoader` | `.md` | `Document`（自动分块） | 解析 `# `` 标题，按 `## `切分节 |
| `ExcelLoader` | `.xlsx` | `LoadedDocument` 或 `List[DataAsset]` | 双模式：结构化 sheet 解析 / 全表文本化 |
| `TxtLoader` | `.txt` | `LoadedDocument` | 最简加载，无结构保留 |
| `DocxLoader` | `.docx` | `LoadedDocument` | 保留 Heading 样式层级 |
| `PptxLoader` | `.pptx` | `LoadedDocument` | 逐幻灯片提取文本 |
| `load_json_seed` | `.json` | `Document` | 从预定义 JSON 读取 chunks |
| `load_data_assets_seed` | `.json` | `List[DataAsset]` | 从预定义 JSON 读取 data_assets |

### 4.6 Text Chunking 详解

Chunker 将长文本切分为 300-800 字符的 Chunk：

```
原始文本（Markdown 分节后）
  │   按 \n\n 拆分为段落
  │
  ├─[para1]─────────────────────┐
  ├─[para2]─────────────────┐  │  累加 ≤ 800字符
  ├─[para3]────────────┐   │   │
  ├─[para4]──┐         │   │   │  > 800 → 切分
  │           │         │   │   │
  ▼           ▼         ▼   ▼   ▼
 Chunk0     Chunk1     Chunk2   ...

每个 Chunk 附带：
  - section_path    来自加载器/初始化的章节路径
  - title_context   文档标题
  - summary         自动生成（前两句或前 100 字符）
  - preset_questions 关键词规则生成（最多 5 个）
  - physical_context {"page": N} / {"sheet": "X"} 等
```

### 4.7 集成链路

```
后端 services/parse_service.py
  → from ingestion.app.loaders import MarkdownLoader, PdfLoader, ExcelLoader
  → from ingestion.app.processors import Chunker, Summarizer, EmbeddingBuilder
  → 解析并分块
  → backend/app/services/db_writer.py（共享连接池，写入 kb_documents/kb_chunks）
  → 不走 ingestion/writers/postgres.py
```

### 4.8 前端数据流程

```
用户上传文件
  ↓
-ingestion Service（FastAPI 端点，可选独立部署）
  ↓ 调用 ingestion 模块
backend services/parse_service.py
  → 用 PdfLoader / MarkdownLoader / ExcelLoader 解析
  → 用 Chunker 分块、Summarizer 摘要
  → 调用 EmbeddingBuilder 生成向量
  ↓
backend/app/services/db_writer.py
  → 写入 PostgreSQL + pgvector
  ↓
检索结果通过 /retrieve 端点返回前端
```

### 4.9 使用场景

- **批量数据入库**：将 PDF 手册、Excel 设计文档批量解析入库。
- **开发调试快照**：用 `JsonWriter` 写 JSON 预览文件，人工核对分块质量。
- **测试对齐**：`MockEmbedding` 与后端 Mock 服务算法一致，可确保两端测试通过。

## 5. Module Responsibilities

| Module | Responsibility |
|:--|:--|
| frontend | Retrieval playground, evidence display, trace viewer, evaluation UI |
| backend | Unified `/retrieve`, query planning, strategy orchestration, adapter routing |
| database | PostgreSQL + pgvector schema, seed data, indexes, demo SQL |
| ingestion | Parse raw materials, chunk text, create preset questions, generate embeddings |
| evaluation | Test retrieval quality, compare strategies, produce reports |

## 6. First Development Order

```text
1. database
   Create schema and seed demo data.

2. backend
   Create mock /retrieve, then connect pgvector.

3. ingestion
   Create manual JSON / Markdown ingestion pipeline.

4. frontend
   Create retrieval playground and trace viewer.

5. evaluation
   Create basic hit@k evaluation script.
```

## 7. Running Principle

First stage can run as:

```text
frontend
backend
postgres
```

Later stages can split into:

```text
frontend
backend / rag-gateway
retriever-runtime
adapter-postgres
ingestion-service
evaluation-service
postgres
minio
redis
opensearch
qdrant
```

## 8. Core API

The main API should remain unified:

```text
POST /retrieve
```

The request declares user intent and constraints. The backend decides retrieval plan and backend capabilities.

## 9. Vibe Coding Rule

Each module should be small enough to build independently.

Recommended rhythm:

```text
make it run
make it visible
make it traceable
make it replaceable
```