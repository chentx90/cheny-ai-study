# OCR 服务构件设计说明书

## 一、构件定位

将扫描类 PDF、图片嵌入 PDF 及独立图片文件中的文字转换为结构化文本，供接入管道构件后续分块入库。

以独立 FastAPI 进程运行，通过 HTTP 接口与后端解耦，GPU 资源与 API 服务隔离。

---

## 二、触发条件

在 `parse_service._parse_pdf()` 中，以下任一条件满足时调用 OCR：

| 判断条件 | 说明 |
|:--|:--|
| `page.get_text("text").strip() == ""` | 扫描页，无可提取文字 |
| `page.get_images()` 非空 且 文字 < 50 字 | 图片嵌入为主，文字极少 |

`OCR_API_URL` 为空时跳过，不影响普通文字 PDF 的正常流程。

---

## 三、模型选型

| 项 | 内容 |
|:--|:--|
| 模型 | Unlimited-OCR（百度，2026/06） |
| 架构 | VLM：自定义视觉编码器 + DeepSeek V2 语言模型 |
| 本地路径 | `<MODELS_DIR>\Unlimited-OCR` |
| 推理库 | Hugging Face Transformers（safetensors，bfloat16） |
| 硬件要求 | NVIDIA GPU ≥ 8GB VRAM，CUDA |
| 不兼容 | llama.cpp（自定义架构，非 GGUF，含自定义 logit processor） |

---

## 四、目录结构

```text
ocr_service/
  server.py          # FastAPI 入口，POST /ocr
  model.py           # 模型加载与 infer 封装
  requirements.txt   # torch / transformers / pillow / pymupdf / einops…
```

---

## 五、接口规范

### POST /ocr

**请求**

```json
{
  "image_path": "C:/tmp/page_0001.png"
}
```

> `image_path` 为 OCR 服务**本机**可访问的绝对路径。
> 接入管道将页面渲染为 PNG 临时文件后传入。

**响应**

```json
{
  "text": "识别出的完整文字内容...",
  "page_count": 1
}
```

**错误**

| HTTP 状态码 | 含义 |
|:--|:--|
| 400 | image_path 不存在 |
| 503 | 模型未加载完成 |
| 500 | 推理异常 |

---

## 六、核心实现

### model.py

```python
import torch
from transformers import AutoModel, AutoTokenizer
import tempfile

MODEL_PATH = r"<MODELS_DIR>\Unlimited-OCR"

class OCRModel:
    def __init__(self):
        self.tokenizer = AutoTokenizer.from_pretrained(
            MODEL_PATH, trust_remote_code=True)
        self.model = AutoModel.from_pretrained(
            MODEL_PATH, trust_remote_code=True,
            use_safetensors=True, torch_dtype=torch.bfloat16,
        ).eval().cuda()

    def infer(self, image_path: str) -> str:
        out_dir = tempfile.mkdtemp()
        result = self.model.infer(
            self.tokenizer,
            prompt="<image>document parsing.",
            image_file=image_path,
            output_path=out_dir,
            base_size=1024, image_size=640, crop_mode=True,
            max_length=32768,
            no_repeat_ngram_size=35, ngram_window=128,
            save_results=False,
        )
        return result if isinstance(result, str) else ""
```

### server.py

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
from .model import OCRModel

app = FastAPI()
_model: OCRModel | None = None

@app.on_event("startup")
async def load_model():
    global _model
    _model = OCRModel()

class OcrReq(BaseModel):
    image_path: str

@app.post("/ocr")
async def ocr(req: OcrReq):
    if not _model:
        raise HTTPException(503, "Model loading")
    if not Path(req.image_path).exists():
        raise HTTPException(400, f"File not found: {req.image_path}")
    return {"text": _model.infer(req.image_path)}
```

### 启动

```bash
cd ocr_service
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 10001
```

---

## 七、接入管道调用点

`backend/app/services/ocr_client.py`（进行 HTTP 调用）：

```python
import httpx, tempfile
from pathlib import Path
import fitz
from ..config import settings

async def ocr_pdf_page(page: fitz.Page, page_num: int) -> str:
    if not settings.OCR_API_URL:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72)).save(tmp.name)
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{settings.OCR_API_URL}/ocr",
                json={"image_path": tmp.name},
            )
            r.raise_for_status()
            return r.json().get("text", "")
```

`parse_service._parse_pdf()` 中嵌入调用：

```python
text = page.get_text("text").strip()
needs_ocr = (not text) or (page.get_images() and len(text) < 50)
if needs_ocr:
    text = await ocr_pdf_page(page, i) or text
```

---

## 八、配置项

在 `backend/app/config.py` 追加：

```python
OCR_API_URL: str = ""   # 空 = 不启用 OCR；如 http://localhost:10001
```

---

## 九、降级策略

| 场景 | 行为 |
|:--|:--|
| `OCR_API_URL` 未配置 | 跳过 OCR，文字保持原样（空页保留为空） |
| OCR 服务不可达（连接超时） | 记录 warning，文字降级为 fitz 原始提取结果 |
| OCR 返回空文本 | 保留 fitz 原始文字，不覆盖 |
| 模型加载中（503） | 抛出异常，接入任务置 `error` 状态，可重试 |
