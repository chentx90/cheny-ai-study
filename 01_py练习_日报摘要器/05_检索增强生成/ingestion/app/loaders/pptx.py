"""PowerPoint (.pptx) 文件加载器。

使用 ``python-pptx`` 库遍历幻灯片，提取每页中的所有文本内容并组装为
``LoadedDocument``。每张幻灯片对应一个 ``RawPage``，页号为幻灯片序号。
"""
from pathlib import Path
from ..schemas import LoadedDocument, RawPage


class PptxLoader:
    """PowerPoint 文件加载器，从 .pptx 文件中提取文本内容。"""

    def load(self, file_path: str, title: str = "", business_domain: str = "general", doc_type: str = "presentation") -> LoadedDocument:
        """加载 .pptx 文件并提取所有幻灯片的文本。

        Args:
            file_path: .pptx 文件路径。
            title: 文档标题，为空则使用文件名（无扩展名）。
            business_domain: 业务领域标识。
            doc_type: 文档类型标识。

        Returns:
            包含所有幻灯片文本的 ``LoadedDocument``。
        """
        from pptx import Presentation
        path = Path(file_path)
        prs = Presentation(path)
        pages = []
        for i, slide in enumerate(prs.slides, 1):
            texts = [
                shape.text_frame.text.strip()
                for shape in slide.shapes
                if shape.has_text_frame and shape.text_frame.text.strip()
            ]
            if texts:
                pages.append(RawPage(page_number=i, text="\n".join(texts)))
        return LoadedDocument(
            title=title or path.stem,
            source_uri=str(path),
            doc_type=doc_type,
            business_domain=business_domain,
            pages=pages,
        )
