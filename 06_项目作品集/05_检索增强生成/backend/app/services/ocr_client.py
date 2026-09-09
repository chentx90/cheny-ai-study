"""OCR client backed by third-party OpenAI/NewAPI-compatible vision APIs.

OCR is optional. When OCR_BASE_URL/OCR_MODEL or an API key is missing, scanned
PDF pages are skipped and normal text extraction still works.
"""
from __future__ import annotations

import base64

import fitz
import httpx

from ..config import settings


class OCRVisionClient:
    def __init__(self) -> None:
        self.base_url = settings.ocr_base_url.rstrip("/")
        self.api_key = settings.resolved_ocr_api_key
        self.model = settings.ocr_model

    def is_available(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    async def recognize_pdf_page(self, page: fitz.Page, page_num: int) -> str:
        if not self.is_available():
            return ""

        pixmap = page.get_pixmap(matrix=fitz.Matrix(180 / 72, 180 / 72), alpha=False)
        image_b64 = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "请对这张 PDF 页面做 OCR。只输出页面中的原始文字，"
                                "尽量保留标题、段落、编号、表格行列关系；不要解释。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
            return self._extract_text(response.json())
        except Exception:
            return ""

    @staticmethod
    def _extract_text(data: dict) -> str:
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                return "\n".join(parts).strip()
        text = data.get("text")
        return text.strip() if isinstance(text, str) else ""


ocr_client = OCRVisionClient()


async def ocr_pdf_page(page: fitz.Page, page_num: int) -> str:
    return await ocr_client.recognize_pdf_page(page, page_num)
