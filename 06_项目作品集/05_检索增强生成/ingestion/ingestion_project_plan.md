# Ingestion Project Plan

## 1. Module Goal

The ingestion module converts raw materials into standardized retrieval objects.

It receives documents, images, tables, and data asset descriptions, then produces documents, chunks, assets, embedding tasks, and index-ready records.

It should not bind data to a specific retrieval strategy. Its output should be reusable by pgvector, OpenSearch, Qdrant, or other backends.

## 2. Main Responsibilities

```text
Load raw files
Parse text
Extract images and tables
Create chunks
Generate title_context
Generate summary
Generate preset_questions
Generate OCR text or image description
Build embedding text
Call embedding model
Write records through backend or adapter
```

## 3. Input Types

```text
Markdown
PDF
Word
HTML
TXT
Images
Excel / CSV
Manual JSON seed data
Database schema descriptions
```

## 4. Standard Output Objects

```text
Document
Chunk
Asset
DataAsset
EmbeddingTask
IndexTask
```

## 5. Chunking Rules

```text
300-800 Chinese characters per chunk
Split by heading, paragraph, step, or clause
Do not cut in the middle of a sentence
Keep one operation step in one chunk when possible
Preserve section_path
Preserve image references
```

## 6. Embedding Text Format

Recommended embedding text:

```text
[Title Context] ...
[Section Path] ...
[Summary] ...
[Content] ...
[Preset Questions] ...
```

## 7. Preset Question Generation

Each chunk should have 2-5 preset questions.

Question types:

```text
casual user question
professional terminology question
fault scenario question
operation step question
```

Example:

```json
[
  "液压泵压力不足怎么办？",
  "液压系统压力异常有哪些原因？",
  "设备压力上不去应该先查哪里？",
  "过滤器堵塞会不会影响液压压力？"
]
```

## 8. Suggested Tech Stack

```text
Python
FastAPI or CLI
Pydantic
pypdf / pymupdf
python-docx
pandas
Pillow
OCR optional
LLM optional for summary/questions
Embedding API
```

## 9. Suggested Directory Structure

```text
ingestion/
  app/
    main.py
    config.py
    loaders/
      markdown.py
      pdf.py
      docx.py
      excel.py
      image.py
    processors/
      chunker.py
      summarizer.py
      question_generator.py
      embedding_builder.py
    writers/
      postgres_writer.py
      file_writer.py
    schemas/
      document.py
      chunk.py
      asset.py
  samples/
  tests/
  Dockerfile
  README.md
```

## 10. First Vibe Coding Tasks

1. Create manual JSON ingestion path.
2. Create markdown loader.
3. Implement simple chunker.
4. Generate embedding text.
5. Call embedding model or mock embedding.
6. Write kb_documents and kb_chunks.
7. Write kb_assets from image references.
8. Write data_assets from seed JSON.
9. Add CLI command for demo ingestion.
10. Add one complete sample dataset.

## 11. Acceptance Criteria

```text
A sample markdown file can be ingested
Chunks contain section_path, title_context, content, summary, preset_questions
Embeddings can be generated or mocked
Records can be written to PostgreSQL
Image URL metadata can be associated with chunks
Data assets can be seeded
```