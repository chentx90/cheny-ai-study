# ingestion 模块

## 定位

**数据接入与解析库**——将原始文件（PDF、Markdown、Excel、TXT、DOCX、PPTX、JSON 种子文件）解析为标准化的结构化数据，供后端存储层和 RAG pipeline 消费。

模块设计原则：

1. **独立可运行**：不直接连接数据库时，可通过 ``writers/JsonWriter`` 输出 JSON 预览文件进行本地验证。
2. **不直接连库（后端接入点）**：后端集成时，由 ``backend/app/services/db_writer.py``（共享连接池）负责持久化，不依赖 ``writers/PostgresWriter``。
3. **可扩展**：通过 ``BaseLoader`` 统一接口，新增文件格式只需一个 Loader 子类。

## 解析流水线

```
原始文件（PDF / Markdown / Excel / JSON）
  │
  ▼ loaders/
  LoadedDocument { pages: List[RawPage], metadata }  ──── 或 ────  Document { title, chunks }
  │                   ↑ 文件加载器                     processors/summarizer.py 规则摘要
  │                                                        processors/chunker.py 文本分块
  ▼ processors/                              ──── 或 ────  processors/embedding_builder.py embedding 文本构建
  List[Chunk] { section_path, title_context,
               content, summary, preset_questions,
               physical_context }
  │
  ├─▶ processors/summarizer.py              # 规则摘要（取前两句，≤200字符）
  ├─▶ processors/embedding_builder.py       # 调用 Embedding 服务生成向量文本
  └─▶ processors/data_asset_builder.py      # Excel → DataAsset（表/列/指标）
  │
  ▼ embeddings/
  Chunk + embedding vector（1536维，MockEmbedding 或生产服务）
  │
  ▼ writers/（独立运行时）
  postgres.py → PostgresWriter    # 独立 CLI / 测试用
  json.py     → JSON 预览文件     # 开发调试 / 快照测试用
```

> **再次强调**：后端接入链路使用 `backend/app/services/db_writer.py`（共享池），不走 `writers/postgres.py`。

## 输入输出契约

### 文件类 Loader（PdfLoader / MarkdownLoader / ExcelLoader / TxtLoader / DocxLoader / PptxLoader）

| 输入 | 输出 | 说明 |
|:--|:--|:--|
| 文件路径 + 业务领域 | ``LoadedDocument`` | ``LoadedDocument`` 包含 ``List[RawPage]``，每个 ``RawPage`` 对应一页/一节，含 ``text`` 和 ``metadata`` |

### 种子 Loader

| 输入 | 输出 | 说明 |
|:--|:--|:--|
| JSON 路径（含 chunks） | ``Document`` | ``load_json_seed`` |
| JSON 路径（含 data_assets） | ``List[DataAsset]`` | ``load_data_assets_seed`` |

### Chunk

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| ``section_path`` | ``str`` | 章节路径，如 "第一章 > 1.1 液压系统" |
| ``title_context`` | ``str`` | 标题上下文（文档/章节标题） |
| ``content`` | ``str`` | 原始正文 |
| ``summary`` | ``str`` | 自动摘要（前两句） |
| ``preset_questions`` | ``List[str]`` | 预设问题列表 |
| ``physical_context`` | ``Dict[str, Any]`` | 物理位置 {"page": 5} |

### DataAsset

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| ``asset_type`` | ``str`` | 资产类型："table" / "column" / "metric" / "case" / "tool" |
| ``name`` | ``str`` | 资产名称 |
| ``description`` | ``str`` | 业务含义描述 |
| ``business_domain`` | ``str`` | 所属业务领域 |
| ``parent_name`` | ``Optional[str]`` | 父级资产名称（如某列所属表） |
| ``synonyms`` | ``List[str]`` | 同义词列表 |
| ``formula`` | ``Optional[str]`` | 计算公式（仅 metric） |
| ``related_table`` | ``Optional[str]`` | 关联表名 |
| ``related_columns`` | ``List[str]`` | 关联字段名列表 |

## 目录详解

```
ingestion/
  README.md              # 本文件（模块说明）
  ingestion_project_plan.md  # 项目计划文档

  app/
    config.py            # Pydantic Settings（独立运行时的 DB/EMB 配置）
    schemas.py           # Pydantic 数据模型（Document / Chunk / DataAsset / Asset）
    schemas/__init__.py  # re-export 入口
    main.py              # ingest_document / ingest_data_asset 顶层编排函数

    loaders/             # 数据加载器子包
      __init__.py        # re-export 所有 Loader
      base.py            # BaseLoader 抽象基类
      pdf.py             # PdfLoader：PyMuPDF，支持 OCR / 结构化模式
      markdown.py        # MarkdownLoader：解析标题层级，自动分节分块
      excel.py           # ExcelLoader：双模式（data_asset / text），结构化 + 文本化
      txt.py             # TxtLoader：纯文本，最简加载器
      docx.py            # DocxLoader：保留 Heading 层级，转 Markdown 标记
      pptx.py            # PptxLoader：逐幻灯片提取文本
      seed.py            # load_json_seed / load_data_assets_seed：JSON 种子文件加载

    processors/          # 文本处理器子包
      __init__.py        # re-export 所有 Processor
      chunker.py         # Chunker：段落拆分，300-800字符/Chunk
      summarizer.py      # Summarizer：取前两句，≤200字符
      question_generator.py  # QuestionGenerator：规则预设问题（已被 LLM 富化取代）
      embedding_builder.py   # EmbeddingBuilder：委托 Chunk.build_embedding_text()
      data_asset_builder.py  # DataAssetBuilder：Excel 行 → DataAsset

    embeddings/          # Embedding 服务子包
      __init__.py        # re-export BaseEmbedding / MockEmbedding
      base.py            # BaseEmbedding 抽象接口
      mock.py            # MockEmbedding：SHA256 Seed + numpy random，1536维向量

    writers/             # 写入器子包
      __init__.py        # re-export PostgresWriter / JsonWriter
      base.py            # BaseWriter 抽象基类（connect / close）
      postgres.py        # PostgresWriter：asyncpg 异步写库（独立 CLI 用）
      json.py            # JsonWriter：JSON 文件预览（开发调试 / 快照测试用）
```

## 各文件详细说明

### config.py

Pydantic Settings 配置类，集中管理票据集中配置项。

| 配置项 | 默认值 | 说明 |
|:--|:--|:--|
| ``database_url`` | ``postgresql://rag_user:rag_pass@localhost:5432/rag_db`` | PostgreSQL 连接字符串 |
| ``embedding_model`` | ``text-embedding-3-small`` | Embedding 模型名称标签 |
| ``embedding_dimension`` | ``1536`` | Embedding 向量维度 |

通过 ``.env`` 文件或环境变量覆盖配置。生产环境强烈建议通过环境变量传入。

### loaders/

#### base.py — `BaseLoader`

抽象基类，定义 ``load(file_path, **kwargs) -> object`` 接口。所有文件类加载器都应继承此类。

#### pdf.py — `PdfLoader` + `_detect_sections`

- **普通模式**：逐页提取文本，遇到空白页或图片页时触发 ``ocr_fn``（可选）。
- **结构化模式**（``structured=True``）：用 ``_detect_sections`` 函数根据字体大小推断标题层级，将整篇文档按节切分为多段文本，每节附带 ``section_path`` 元数据。

关键技术细节：

- 字体大小基准取所有 span 的字号中位数，以 1.15 倍为阈值判定标题。
- ``needs_ocr`` 判断：页面无文本 **或**（有嵌入图片 且 文本 < 50 字符）时触发 OCR。

#### markdown.py — `MarkdownLoader`

- 提取 ``# `` 开头的行作为文档标题。
- 按 ``## `` 及以上标题切分各节，将每节文本送入 ``Chunker``。
- Heading 层级标记（``#、##、###``）在节内容中保留，供下游 Chunker 识别。

#### excel.py — `ExcelLoader`

提供两种使用方式：

1. **结构化（``load_data_assets``）**：只读取预定义 sheet 名（``tables、columns、metrics、cases、tools``），逐行解析为 ``DataAsset`` 列表。
2. **文本化（``load_as_text``）**：读取所有 sheet，每个 sheet 格式化为 Markdown 表格文字输出。

对于 ``metrics`` sheet，自动提取 ``formula``、``related_table``、``related_columns`` 字段。

#### txt.py — `TxtLoader`

最简加载器，读取纯文本文件，输出单页 ``LoadedDocument``。

#### docx.py — `DocxLoader`

使用 ``python-docx``，保留段落样式。Heading 样式段落会被转换为 Markdown 标题标记（``# `` 前缀），保持文档层级结构。

#### pptx.py — `PptxLoader`

使用 ``python-pptx``，遍历幻灯片中所有带文字的 Shape，输出每页文本。

#### seed.py — `load_json_seed` / `load_data_assets_seed`

用于从 JSON 文件快速生成测试/演示数据：

- ``load_json_seed``：返回 ``Document``，支持 ``chunks`` 字段。
- ``load_data_assets_seed``：返回 ``List[DataAsset]``，支持 ``data_assets`` 数组。

### processors/

#### chunker.py — `Chunker`

将长文本切分为多个 ``Chunk`` 的文本处理器。

核心参数：

| 参数 | 默认值 | 说明 |
|:--|:--|:--|
| ``MIN_CHARS`` | 300 | 单个 Chunk 最小字符数 |
| ``MAX_CHARS`` | 800 | 单个 Chunk 最大字符数 |

算法：

1. 按 ``\\n\\n``（空行）拆分段落。
2. 逐个段落累加文本，超过 ``MAX_CHARS`` 则输出当前 Chunk。
3. 每个 Chunk 自动生成摘要（取前 100 字符）和预设问题。

预设问题通过关键词匹配生成（"压力"、"维护"、"质量"），仅在设备领域知识类文档中有显著效果。

#### summarizer.py — `Summarizer`

对 ``Chunk`` 生成精简摘要：

1. 将换行统一为空格，按句号（。）拆分句子。
2. 取前两句作为摘要。
3. 截断至 200 字符。

#### question_generator.py — `QuestionGenerator`（⚠️ 已废弃，仅保留实现）

基于关键词匹配，为 Chunk 生成 0-3 个预设问题。已被后端 LLM 富化取代，供独立测试时参考。

#### embedding_builder.py — `EmbeddingBuilder`

负责将文本内容交给 ``BaseEmbedding`` 实现类生成向量。提供三个接口：

1. ``build_embedding_text(chunk)``：委托 ``Chunk.build_embedding_text()`` 拼接文本。
2. ``embed_chunk(chunk)``：为 Chunk 生成向量。
3. ``embed_data_asset(asset)``：为 DataAsset 生成向量。

#### data_asset_builder.py — `DataAssetBuilder`

将 Excel 行数据映射为 ``DataAsset`` 对象。自动推断 ``asset_type``（行中的 ``type`` 字段优先于 sheet 名称映射）。

### embeddings/

#### base.py — `BaseEmbedding`

抽象基类，定义 ``embed(text) -> List[float]`` 接口。

#### mock.py — `MockEmbedding`

本地开发/测试用 Embedding 实现。策略：

1. MD5 哈希文本取前 8 字符，转为整数种子。
2. 使用该种子初始化 Python ``random.Random``，确保确定性输出。
3. 生成 ``dimension`` 维、范围 ``[-1, 1]`` 的均匀随机向量。

此实现与后端 ``MockEmbeddingService`` 完全对齐，可保持测试一致性。

### writers/

#### base.py — `BaseWriter`

抽象基类，定义 ``connect()`` 和 ``close()`` 生命周期接口。

#### postgres.py — `PostgresWriter`

独立 CLI / 测试用的 PostgreSQL 写入器：

- 通过 ``asyncpg.create_pool`` 创建异步连接池。
- ``write_document``：写入 ``kb_documents`` 表。
- ``write_chunks``：批量写入 ``kb_chunks`` 表（使用 ``executemany``）。
- ``write_data_asset``：写入 ``data_assets`` 表。
- ``ingest_document``：组合 ``write_document`` + ``write_chunks`` 的便捷方法。

> 注意：向量字段在插入时通过 ``$9::vector`` 转换。

#### json.py — `JsonWriter`

将 ``Document`` 或 ``DataAsset`` 序列化为 JSON 文件写入指定目录。

主要用途：

- 开发调试时对解析结果进行人工审核。
- CI 测试中的快照对比验证。

## 使用方式

### 作为独立 CLI 运行

```bash
cd ingestion
python -c "
import asyncio
from app.loaders import PdfLoader, load_json_seed
from app.processors import Chunker, Summarizer, EmbeddingBuilder
from app.embeddings import MockEmbedding
from app.writers import PostgresWriter, JsonWriter

async def main():
    # 1. 加载文件
    loader = PdfLoader()
    doc = loader.load('sample.pdf', business_domain='equipment')

    # 2. 分块（分块已在 MarkdownLoader 中自动完成）
    # 这里做额外的 Summarizer / Embedding 处理
    summarizer = Summarizer()
    embedding_builder = EmbeddingBuilder(MockEmbedding())

    for chunk in doc.chunks:
        chunk.summary = summarizer.summarize(chunk)
        # embedding 向量在写入时由 PostgresWriter 自动计算

    # 3. 写入 PostgreSQL
    writer = PostgresWriter('postgresql://rag_user:rag_pass@localhost:5432/rag_db')
    await writer.connect()
    doc_id = await writer.ingest_document(doc)
    await writer.close()
    print(f'Inserted document id={doc_id}')

    # 4. JSON 预览
    json_writer = JsonWriter('./output')
    json_writer.write_document(doc)

asyncio.run(main())
"
```

### 作为子模块被后端调用

后端的 ``services/parse_service.py`` 直接使用 ``ingestion`` 模块的加载器和处理器：

```python
from ingestion.app.loaders import PdfLoader, MarkdownLoader
from ingestion.app.processors import Chunker, Summarizer

loader = MarkdownLoader()
document = loader.parse(markdown_text, business_domain="equipment")

chunker = Chunker(document.title)
for section_path, section_text in sections:
    chunks = chunker.chunk_text(section_text, section_path)
    document.chunks.extend(chunks)

summarizer = Summarizer()
for chunk in document.chunks:
    chunk.summary = summarizer.summarize(chunk)
```

后端通过 ``db_writer.py`` 将 ``Document`` 和 ``Chunk`` 写入数据库，不使用 ``PostgresWriter``。

## 与其他模块的关系

| 关系 | 说明 |
|:--|:--|
| **上游** | 原始文件（PDF、Excel、Markdown 等） |
| **下游（后端）** | ``backend/app/services/db_writer.py`` 通过 ``ingestion`` 模块的解析结果做写库 |
| **下游（evaluation）** | ``evaluation`` 模块从数据库读取 Chunk 和 embedding 做评测 |
| **工具依赖** | ``fitz``（PDF）、``pandas``（Excel）、``python-docx``（DOCX）、``python-pptx``（PPTX）、``pydantic-settings``（配置） |

## 注意事项

1. ``processors/chunker.py`` 保留供 ingestion 模块独立使用；核心分块逻辑也已同步在 ``backend/app/core/chunker.py`` 中实现。
2. ``writers/postgres.py`` 保留供独立 CLI 和测试使用。后端接入走 ``backend/app/services/db_writer.py``。
3. ``embeddings/mock.py`` 与后端 ``MockEmbeddingService`` 实现一致（SHA256 seed + Python random），可对齐测试。
4. ``question_generator.py`` 已被 LLM 富化取代，仅保留架构参考价值。
5. ``LoadedDocument`` 和 ``RawPage`` 类型若尚未在 ``schemas.py`` 中定义，需要补充或确认导入链。
