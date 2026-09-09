"""纯文本文件 (.txt) 加载器。

直接从文件读取 UTF-8 文本内容，产出单页 ``LoadedDocument``。
这是最简化的加载器，适用于无结构的纯文本文件。
"""
from pathlib import Path
from ..schemas import LoadedDocument, RawPage


class TxtLoader:
    """纯文本文件加载器。"""

    def load(self, file_path: str, title: str = "", business_domain: str = "general", doc_type: str = "text") -> LoadedDocument:
        """加载 .txt 文件为 ``LoadedDocument``。

        Args:
            file_path: 纯文本文件路径。
            title: 文档标题，为空则使用文件名（无扩展名）。
            business_domain: 业务领域标识。
            doc_type: 文档类型标识。

        Returns:
            包含文本内容的 ``LoadedDocument``（单页）。
        """
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        return LoadedDocument(
            title=title or path.stem,
            source_uri=str(path),
            doc_type=doc_type,
            business_domain=business_domain,
            pages=[RawPage(page_number=1, text=text)] if text else [],
        )
