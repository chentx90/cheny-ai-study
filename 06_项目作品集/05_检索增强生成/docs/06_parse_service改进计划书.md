# parse_service 改进计划书

## 基线确认

`parse_service.py` 当前已完成：
- `_parse_pdf`：OCR 触发逻辑（空页 / 图片页 → `ocr_client.ocr_pdf_page`）
- `ocr_client.py`：HTTP 调用 OCR 服务，`OCR_API_URL` 空时静默跳过
- `config.py`：`ocr_api_url: str = ""`

**尚未实现**（本计划范围）：
1. `txt` / `docx` / `pptx` 三种 handler
2. Excel `text` 模式（当前只支持固定 sheet 名的 data_asset 模式）
3. 上传入口的格式/大小早期校验

---

## 改动一：新增三个 handler

### 改动位置

`backend/app/services/parse_service.py`

### 统一模板

三者均与 `_parse_markdown` 完全一致：提取 `full_text` → `_resolve_doc_meta` → `_build_text_chunks`。
唯一区别在文字提取方式。

---

### 1. `_parse_txt`

```python
async def _parse_txt(path: Path, job: dict) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    options = _job_options(job)
    title, content_hash = await _resolve_doc_meta(text, job, path)
    chunks = await _build_text_chunks(text, title, options)
    return {
        "document": {"title": title, "doc_type": job.get("doc_type", "text"),
                     "business_domain": job.get("business_domain", "general"),
                     "source_uri": str(path), "content_hash": content_hash},
        "pages": [{"page_number": 1, "text": text}], "chunks": chunks,
        "data_assets": [], "sheets": [], "errors": [],
        "stats": {"pages": 1, "chunks": len(chunks), "data_assets": 0, "sheets": 0, "errors": 0},
    }
```

无新依赖。

---

### 2. `_parse_docx`

文字提取规则：
- Heading 样式段落 → 转为 `## 标题` 前缀（保留层级，供 Chunker 识别节边界）
- 普通段落 → 直接取 `para.text`
- 空段落跳过

```python
async def _parse_docx(path: Path, job: dict) -> dict:
    from docx import Document as DocxDoc
    doc = DocxDoc(path)
    lines = []
    for para in doc.paragraphs:
        if not para.text.strip():
            continue
        if para.style.name.startswith("Heading"):
            level = para.style.name.split()[-1]
            prefix = "#" * int(level) if level.isdigit() else "##"
            lines.append(f"{prefix} {para.text.strip()}")
        else:
            lines.append(para.text.strip())
    text = "\n\n".join(lines)
    options = _job_options(job)
    title, content_hash = await _resolve_doc_meta(text, job, path)
    chunks = await _build_text_chunks(text, title, options)
    return {
        "document": {"title": title, "doc_type": job.get("doc_type", "document"),
                     "business_domain": job.get("business_domain", "general"),
                     "source_uri": str(path), "content_hash": content_hash},
        "pages": [{"page_number": 1, "text": text}], "chunks": chunks,
        "data_assets": [], "sheets": [], "errors": [],
        "stats": {"pages": 1, "chunks": len(chunks), "data_assets": 0, "sheets": 0, "errors": 0},
    }
```

新依赖：`pip install python-docx`

---

### 3. `_parse_pptx`

每个 slide 作为独立段落，slide 序号作为节标题，保留结构：

```python
async def _parse_pptx(path: Path, job: dict) -> dict:
    from pptx import Presentation
    prs = Presentation(path)
    slide_texts = []
    for i, slide in enumerate(prs.slides, 1):
        texts = [
            shape.text_frame.text.strip()
            for shape in slide.shapes
            if shape.has_text_frame and shape.text_frame.text.strip()
        ]
        if texts:
            slide_texts.append(f"## 第{i}页\n\n" + "\n".join(texts))
    text = "\n\n".join(slide_texts)
    options = _job_options(job)
    title, content_hash = await _resolve_doc_meta(text, job, path)
    chunks = await _build_text_chunks(text, title, options)
    return {
        "document": {"title": title, "doc_type": job.get("doc_type", "presentation"),
                     "business_domain": job.get("business_domain", "general"),
                     "source_uri": str(path), "content_hash": content_hash},
        "pages": [{"page_number": i+1, "text": t} for i, t in enumerate(slide_texts)],
        "chunks": chunks, "data_assets": [], "sheets": [], "errors": [],
        "stats": {"pages": len(slide_texts), "chunks": len(chunks), "data_assets": 0, "sheets": 0, "errors": 0},
    }
```

新依赖：`pip install python-pptx`

---

### 4. 注册到 `handlers`

在 `parse()` 的 `handlers` 字典追加三行：

```python
handlers = {
    "pdf":      _parse_pdf,
    "excel":    _parse_excel,
    "markdown": _parse_markdown,
    "json":     _parse_json,
    "txt":      _parse_txt,       # 新增
    "docx":     _parse_docx,      # 新增
    "pptx":     _parse_pptx,      # 新增
}
```

---

## 改动二：Excel text 模式

### 背景

当前 `_parse_excel` 只处理固定 sheet 名（`tables/columns/metrics/cases/tools`），普通业务 Excel 被完全跳过（`data_assets=[]`，无 chunks）。

### 方案

`job.options` 中增加 `excel_mode` 字段，默认 `"data_asset"`（原有行为不变）；值为 `"text"` 时，读所有 sheet 并转为文字分块。

### 改动位置

`_parse_excel` 函数头部插入分支：

```python
async def _parse_excel(path: Path, job: dict) -> dict:
    import pandas as pd
    options = _job_options(job)
    if options.get("excel_mode") == "text":
        return await _parse_excel_as_text(path, job, options)
    # 原有 data_asset 逻辑不变 ...
```

新增函数：

```python
async def _parse_excel_as_text(path: Path, job: dict, options: dict) -> dict:
    import pandas as pd
    excel_file = pd.ExcelFile(path)
    page_texts = []
    for sheet_name in excel_file.sheet_names:
        df = pd.read_excel(excel_file, sheet_name=sheet_name).fillna("")
        try:
            body = df.to_markdown(index=False)
        except Exception:
            body = df.to_string(index=False)
        page_texts.append(f"## {sheet_name}\n\n{body}")
    full_text = "\n\n".join(page_texts)
    title, content_hash = await _resolve_doc_meta(full_text, job, path)
    chunks = await _build_text_chunks(full_text, title, options)
    return {
        "document": {"title": title, "doc_type": job.get("doc_type", "excel"),
                     "business_domain": job.get("business_domain", "general"),
                     "source_uri": str(path), "content_hash": content_hash},
        "pages": [{"page_number": i+1, "text": t} for i, t in enumerate(page_texts)],
        "chunks": chunks, "data_assets": [], "sheets": [], "errors": [],
        "stats": {"pages": len(page_texts), "chunks": len(chunks), "data_assets": 0,
                  "sheets": len(page_texts), "errors": 0},
    }
```

新依赖：`pip install tabulate`（`df.to_markdown()` 依赖）

---

## 改动三：上传入口早期校验

### 改动位置

`backend/app/api/ingestion.py`，`upload_file` 路由函数

### 规则

```python
ALLOWED_EXTENSIONS = {"pdf", "md", "markdown", "xlsx", "xls", "json", "txt", "docx", "pptx"}
MAX_BYTES = 50 * 1024 * 1024  # 50 MB

@router.post("/ingestion/uploads")
async def upload_file(file: UploadFile = File(...), ...):
    ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: .{ext}，支持：{sorted(ALLOWED_EXTENSIONS)}")
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"文件超过 {MAX_BYTES // 1024 // 1024} MB 限制")
    # 原有 save_upload 逻辑不变
    ...
```

---

## 改动四：`source_type` 前端传值对齐

前端 `NewImportTab.tsx` 的 `source_type` 下拉/自动检测需同步新增三种值，否则文件上传后无法触发正确 handler。

对应前端改动：
- 文件扩展名 → `source_type` 映射表补充 `.txt→txt`、`.docx→docx`、`.pptx→pptx`
- 接受文件选择器的 `accept` 属性加入 `.txt,.docx,.pptx`

---

## 改动五：依赖声明

`backend/requirements.txt` 追加（如有此文件）：

```
python-docx>=1.1.2
python-pptx>=1.0.2
tabulate>=0.9.0
```

---

## 实施顺序

| 步骤 | 文件 | 操作 |
|:--|:--|:--|
| 1 | `parse_service.py` | 添加 `_parse_txt`、`_parse_docx`、`_parse_pptx`，注册到 `handlers` |
| 2 | `parse_service.py` | 在 `_parse_excel` 头部插入 `excel_mode` 分支，新增 `_parse_excel_as_text` |
| 3 | `api/ingestion.py` | `upload_file` 加类型/大小校验 |
| 4 | `frontend/…/NewImportTab.tsx` | 扩展名映射 + accept 属性 |
| 5 | `requirements.txt` | 追加三个依赖 |

## 验证

```bash
# 后端单元测试
cd backend && python -m pytest tests/ -v

# 手动验证各格式
# 上传 test.txt → preview → 查 chunks > 0
# 上传 test.docx（含 Heading）→ preview → chunks 的 section_path 包含标题文字
# 上传 test.pptx → preview → pages 数量 = slide 数量
# 上传 test.xlsx（普通业务表）→ options.excel_mode="text" → chunks > 0
# 上传 .exe → 400；上传 60MB 文件 → 413
```
