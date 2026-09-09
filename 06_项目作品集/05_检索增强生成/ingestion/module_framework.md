# Ingestion Module Framework

## 1. Module Boundary

The ingestion module converts raw materials into standard retrieval objects.

It does not decide final retrieval strategy. It prepares clean, structured, index-ready data.

## 2. Recommended Stack

```text
Python
Pydantic
FastAPI or CLI
pypdf / pymupdf
python-docx
pandas
Pillow
OCR optional
Embedding API
```

## 3. Directory Framework

```text
ingestion/
  app/
    main.py
    config.py

    loaders/
      base.py
      markdown.py
      pdf.py
      docx.py
      excel.py
      image.py
      json_seed.py

    processors/
      chunker.py
      summarizer.py
      question_generator.py
      embedding_builder.py
      asset_extractor.py

    writers/
      base.py
      postgres_writer.py
      file_writer.py

    schemas/
      document.py
      chunk.py
      asset.py
      data_asset.py
      embedding_task.py

  samples/
    equipment_manual.md
    data_assets.json
    assets.json

  tests/
    test_chunker.py
    test_embedding_text.py

  README.md
```

## 4. Pipeline

```text
load raw file
  ↓
parse text / assets
  ↓
build document record
  ↓
split chunks
  ↓
generate title_context
  ↓
generate summary
  ↓
generate preset_questions
  ↓
build embedding_text
  ↓
generate embedding or mock embedding
  ↓
write database records
```

## 5. Standard Chunk Object

```json
{
  "document_id": "doc_001",
  "chunk_index": 3,
  "section_path": "设备维护 > 液压系统 > 压力不足",
  "title_context": "液压系统维护手册 - 压力不足故障排查",
  "content": "当液压泵压力不足时，应优先检查过滤器是否堵塞...",
  "summary": "说明液压泵压力不足时的优先检查项。",
  "preset_questions": [
    "液压泵压力不足怎么办？",
    "设备压力上不去应该先查哪里？"
  ],
  "physical_context": {
    "page": 18,
    "image_refs": ["asset_001"]
  }
}
```

## 6. Embedding Text Builder

```python
def build_embedding_text(chunk: Chunk) -> str:
    return f'''
[Title Context] {chunk.title_context}
[Section Path] {chunk.section_path}
[Summary] {chunk.summary}
[Content] {chunk.content}
[Preset Questions] {"; ".join(chunk.preset_questions)}
'''.strip()
```

## 7. First Files To Create

```text
app/loaders/json_seed.py
app/processors/chunker.py
app/processors/embedding_builder.py
app/writers/postgres_writer.py
samples/equipment_manual.md
samples/data_assets.json
```

## 8. First Acceptance Test

```text
Run ingestion on sample markdown
Create document record
Create chunk records
Create preset_questions
Create embedding_text
Write records to database
```