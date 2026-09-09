"""Markdown 文件加载器。

将 Markdown 文件解析为 ``Document`` 对象，自动提取标题并基于 Markdown
层级标题（## 及以上）进行节的切分，再将每个节交由 ``Chunker`` 进行细粒度
分块。最终产出一个带有完整 Chunk 列表的 ``Document`` 实例。
"""
import re
from pathlib import Path
from ..schemas import Document, Chunk
from ..processors.chunker import Chunker


class MarkdownLoader:
    """Markdown 文件加载器，负责从 Markdown 文件生成结构化的 ``Document``。"""

    def __init__(self):
        """初始化加载器，创建一个基于空 title_context 的 ``Chunker`` 实例。

        实际的 ``title_context`` 在 ``parse`` / ``load`` 调用时动态设置，
        以便每个文档的标题上下文都能准确传递到其 Chunk 中。
        """
        self.chunker = Chunker("")

    def load(self, file_path: str, business_domain: str = "equipment") -> Document:
        """从文件路径加载并解析 Markdown 文件为 ``Document``。

        Args:
            file_path: Markdown 文件的本地路径。
            business_domain: 所属业务领域，默认为 "equipment"。

        Returns:
            包含分块结果的 ``Document`` 对象。
        """
        content = Path(file_path).read_text(encoding="utf-8")
        return self.parse(content, business_domain)

    def parse(self, content: str, business_domain: str = "equipment") -> Document:
        """将 Markdown 文本内容解析为 ``Document``。

        处理逻辑：

        1. 用正则从文本开头提取一级标题（``# ``）作为文档 ``title``。
        2. 用 ``_extract_sections`` 按 ``##、###、####`` 标题切分各节。
        3. 对每个节调用 ``Chunker.chunk_text`` 生成 ``Chunk`` 列表。
        4. 组装完整的 ``Document``。

        Args:
            content: Markdown 原始文本。
            business_domain: 所属业务领域。

        Returns:
            包含所有 Chunk 的 ``Document``。
        """
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else "Untitled Document"

        sections = self._extract_sections(content)

        chunks = []
        self.chunker.title_context = title

        for section_path, section_content in sections:
            section_chunks = self.chunker.chunk_text(section_content, section_path)
            chunks.extend(section_chunks)

        return Document(
            title=title,
            doc_type="markdown",
            source_uri=None,
            business_domain=business_domain,
            version="1.0",
            chunks=chunks
        )

    def _extract_sections(self, content: str) -> list:
        """按 Markdown 二级及以下标题切分文本，返回 ``(section_path, content)`` 元组列表。

        忽略一级标题（``# ``）本身，仅以二级标题（``## ``）作为节边界，
        将三、四级标题（``###、####``）纳入节内容中。

        Args:
            content: Markdown 原始文本。

        Returns:
            ``[(section_path, section_text), ...]`` 列表。
        """
        sections = []
        lines = content.split('\n')
        current_section = ""
        current_content = []

        for line in lines:
            header_match = re.match(r'^(#{2,})\s+(.+)$', line)
            if header_match:
                if current_section and current_content:
                    sections.append((current_section, '\n'.join(current_content)))
                level = len(header_match.group(1))
                title = header_match.group(2)
                current_section = title
                current_content = []
            elif current_section:
                current_content.append(line)
            elif re.match(r'^#\s+', line):
                pass

        if current_section and current_content:
            sections.append((current_section, '\n'.join(current_content)))

        return sections