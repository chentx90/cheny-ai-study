"""DOCX (.docx) 文件加载器。

使用 ``python-docx`` 库读取 Word 文档的段落文本，同时保留 Heading 样式
的层级信息。将 Heading 段落转换为 Markdown 标题标记（#、##、###），
使下游 ``Chunker`` 能够识别文档结构并按章节切分。
"""
from pathlib import Path
from ..schemas import LoadedDocument, RawPage


class DocxLoader:
    """DOCX 文件加载器，从 .docx 文件中提取保留层级结构的文本。"""

    def load(self, file_path: str, title: str = "", business_domain: str = "general", doc_type: str = "document") -> LoadedDocument:
        """加载 .docx 文件并提取文本内容。

        处理方法：

        1. 遍历所有段落，跳过空段。
        2. 对 ``Heading X`` 样式的段落，根据级别数字添加对应数量的 ``#`` 前缀。
        3. 普通段落保持原样。
        4. 将所有内容用空行连接，产出单一的 ``RawPage``。

        Args:
            file_path: .docx 文件路径。
            title: 文档标题，为空则使用文件名。
            business_domain: 业务领域标识。
            doc_type: 文档类型标识。

        Returns:
            包含文本的 ``LoadedDocument``。
        """
        path = Path(file_path)
        from backend.app.services.docx_extractor import extract_docx_markdown

        extracted = extract_docx_markdown(path)
        return LoadedDocument(
            title=title or path.stem,
            source_uri=str(path),
            doc_type=doc_type,
            business_domain=business_domain,
            pages=[RawPage(
                page_number=1,
                text=extracted.text,
                metadata={"paragraphs": extracted.paragraphs, "tables": extracted.tables},
            )] if extracted.text else [],
        )
