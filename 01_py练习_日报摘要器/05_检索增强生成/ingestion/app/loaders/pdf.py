"""PDF 文件加载器。

使用 ``fitz``（PyMuPDF）提取 PDF 文件中的文本内容，支持两种输出模式：

1. **普通模式**：逐页提取文本，输出 ``LoadedDocument``（每页一个 ``RawPage``）。
2. **结构化模式**（``structured=True``）：用字体大小推断标题层级，对整篇文档
   按节切分，每节作为一个 ``RawPage``，供后续 ``Chunker`` 使用。

此外支持 OCR 回退：对文本为空或仅有少量文本（扫描件/图片插页）的页面，
可通过 ``ocr_fn`` 回调进行 OCR 文字提取。
"""
import fitz
from pathlib import Path
from typing import Callable, List, Optional
from ..schemas import LoadedDocument, RawPage


def _detect_sections(doc: fitz.Document) -> List[tuple]:
    """通过字体大小推断 PDF 文档中的标题层级。

    方法：
    1. 收集文档中所有 span 的字体大小，取中位数作为正文基准字号。
    2. 以基准字号的 1.15 倍作为标题阈值。
    3. 逐行扫描，当某行最大 span 字号超过阈值时，视为新节标题。
    4. 将标题之间的文本归入对应的节中。

    Args:
        doc: 已打开的 PyMuPDF 文档对象。

    Returns:
        ``[(section_path, content_text), ...]`` 列表。
        ``section_path`` 为提取到的节标题（可能为空字符串），
        ``content_text`` 为该节的正文内容。
    """
    sizes = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["text"].strip():
                        sizes.append(span["size"])
    if not sizes:
        return []
    sizes.sort()
    body_size = sizes[len(sizes) // 2]
    heading_threshold = body_size * 1.15

    sections: List[tuple] = []
    current_heading = ""
    current_lines: List[str] = []

    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                max_size = max(s["size"] for s in spans)
                line_text = "".join(s["text"] for s in spans).strip()
                if not line_text:
                    continue
                if max_size >= heading_threshold:
                    if current_lines:
                        sections.append((current_heading, "\n".join(current_lines)))
                        current_lines = []
                    current_heading = line_text
                else:
                    current_lines.append(line_text)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines)))

    return sections


class PdfLoader:
    """PDF 文件加载器，使用 PyMuPDF 解析页面文本。"""

    def load(
        self,
        file_path: str,
        title: str = "",
        business_domain: str = "general",
        doc_type: str = "manual",
        ocr_fn: Optional[Callable[[fitz.Page], str]] = None,
        structured: bool = False,
    ) -> LoadedDocument:
        """加载并解析 PDF 文件为 ``LoadedDocument``。

        Args:
            file_path: PDF 文件的本地路径。
            title: 文档标题，为空时自动从文件名推断。
            business_domain: 所属业务领域，默认为 "general"。
            doc_type: 文档类型标识，默认为 "manual"。
            ocr_fn: 可选的回调函数，接受 ``fitz.Page`` 并返回 OCR 文字。
                    用于扫描件或图片为主的页面。
            structured: 若为 True，启用结构化模式（按标题层级切分节）。

        Returns:
            包含页面或节信息的 ``LoadedDocument``。
        """
        path = Path(file_path)
        doc = fitz.open(file_path)
        pages: List[RawPage] = []

        for i in range(len(doc)):
            page = doc.load_page(i)
            text = page.get_text("text").strip()
            needs_ocr = (not text) or (page.get_images() and len(text) < 50)
            if needs_ocr and ocr_fn:
                text = ocr_fn(page) or text
            if text:
                pages.append(RawPage(
                    page_number=i + 1,
                    text=text,
                    metadata={"source": str(path), "page_count": len(doc)},
                ))

        if structured:
            sections = _detect_sections(doc)
            if sections:
                pages = []
                for idx, (heading, content) in enumerate(sections):
                    if content.strip():
                        pages.append(RawPage(
                            page_number=idx + 1,
                            text=content,
                            metadata={"section_path": heading or "正文"},
                        ))

        doc.close()
        return LoadedDocument(
            title=title or path.stem,
            source_uri=str(path),
            doc_type=doc_type,
            business_domain=business_domain,
            pages=pages,
        )
