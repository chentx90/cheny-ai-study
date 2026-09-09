"""文本分块处理器。

将长文本按段落和长度约束切分为多个 ``Chunk``，确保：

1. 每个 Chunk 的长度在 ``MIN_CHARS`` ~ ``MAX_CHARS`` 范围内。
2. 跨段落时尽量在段落边界附近切分。
3. 每个 Chunk 自动生成摘要、预设问题，并携带 ``section_path`` 和
   ``title_context`` 以保留文档结构信息。

本模块的 ``Chunker`` 保留为 ingestion 模块独立使用。
核心实现也已同步迁移到 ``backend/app/core/chunker.py``。
"""
import re
from typing import List, Tuple
from ..schemas import Chunk


class Chunker:
    """文本分块器，将长文本切分为语义独立、长度适中的 ``Chunk`` 列表。"""

    MIN_CHARS = 300
    """单个 Chunk 的最小字符数。过短的 Chunk 会被合并到相邻 Chunk 中。"""

    MAX_CHARS = 800
    """单个 Chunk 的最大字符数。超过此阈值时会强制切分到下一 Chunk。"""

    def __init__(self, title_context: str, section_path: str = ""):
        """初始化分块器。

        Args:
            title_context: 当前文档的标题上下文，传递给所有生成的 Chunk。
            section_path: 当前章节路径，在 ``chunk_text`` 调用时也可动态覆盖。
        """
        self.title_context = title_context
        self.section_path = section_path

    def chunk_text(self, text: str, section_path: str = None) -> List[Chunk]:
        """将一段文本切分为 ``Chunk`` 列表。

        处理流程：

        1. 按空行（``\\n\\n``）将文本拆分为段落。
        2. 逐个段落累加，当总长度超过 ``MAX_CHARS`` 时，将当前 Chunk 切出。
        3. 剩余文字作为下一 Chunk 的起始内容。
        4. 每个 Chunk 都附带摘要和预设问题。

        Args:
            text: 待切分的源文本。
            section_path: 可选，覆盖实例级别的 ``section_path``。

        Returns:
            ``Chunk`` 对象列表。
        """
        if section_path:
            self.section_path = section_path

        chunks = []
        chunk_index = 0

        for local_section_path, section_text in self._split_sections(text):
            paragraphs = self._split_paragraphs(section_text)
            current_chunk = ""

            for para in paragraphs:
                for part in self._split_large_block(para):
                    if len(current_chunk) + len(part) <= self.MAX_CHARS:
                        current_chunk = f"{current_chunk}\n\n{part}".strip() if current_chunk else part
                    else:
                        if current_chunk:
                            chunks.append(self._create_chunk(current_chunk, chunk_index, local_section_path))
                            chunk_index += 1
                        current_chunk = part

            if current_chunk:
                chunks.append(self._create_chunk(current_chunk, chunk_index, local_section_path))
                chunk_index += 1

        return chunks

    def _split_paragraphs(self, text: str) -> List[str]:
        """将文本按空行切分为非空段落列表。"""
        paras = re.split(r'\n\s*\n', text)
        return [p.strip() for p in paras if p.strip()]

    def _split_sections(self, text: str) -> List[Tuple[str, str]]:
        sections = []
        heading_stack = []
        current_lines = []
        current_path = self.section_path

        for block in self._split_paragraphs(text):
            match = re.match(r'^(#{1,6})\s+(.+)$', block)
            if match:
                if current_lines:
                    sections.append((current_path, "\n\n".join(current_lines)))
                level = len(match.group(1))
                title = match.group(2).strip()
                heading_stack = heading_stack[:level - 1]
                heading_stack.append(title)
                current_path = " > ".join([self.section_path, *heading_stack]) if self.section_path else " > ".join(heading_stack)
                current_lines = [block]
            else:
                current_lines.append(block)

        if current_lines:
            sections.append((current_path, "\n\n".join(current_lines)))
        return sections or [(self.section_path, text)]

    def _split_large_block(self, block: str) -> List[str]:
        if len(block) <= self.MAX_CHARS:
            return [block]

        lines = block.splitlines()
        if len(lines) > 2 and lines[0].startswith("|") and lines[1].startswith("|"):
            header = lines[:2]
            parts = []
            current = header[:]
            for row in lines[2:]:
                candidate = "\n".join([*current, row])
                if len(candidate) > self.MAX_CHARS and len(current) > 2:
                    parts.append("\n".join(current))
                    current = [*header, row]
                else:
                    current.append(row)
            if current:
                parts.append("\n".join(current))
            return parts

        parts = []
        start = 0
        while start < len(block):
            parts.append(block[start:start + self.MAX_CHARS])
            start += self.MAX_CHARS
        return parts

    def _is_table_block(self, block: str) -> bool:
        lines = block.lstrip().splitlines()
        return len(lines) > 1 and lines[0].startswith("|") and lines[1].startswith("|")

    def _create_chunk(self, content: str, index: int, section_path: str = None) -> Chunk:
        """为一段内容创建一个 ``Chunk``，自动生成摘要和预设问题。"""
        summary = content[:100] + "..." if len(content) > 100 else content
        return Chunk(
            section_path=section_path or self.section_path,
            title_context=self.title_context,
            content=content,
            summary=summary,
            preset_questions=self._generate_preset_questions(content)
        )

    def _generate_preset_questions(self, content: str) -> List[str]:
        """基于规则引擎为 Chunk 内容生成预设问题。

        目前支持的关键词汇匹配规则：

        - 包含 "压力"、"压力不足"：生成关于液压系统压力排查的问题。
        - 包含 "维护"：生成关于设备维护周期的问题。

        最多返回 5 个问题。

        Args:
            content: Chunk 的正文内容。

        Returns:
            预设问题字符串列表。
        """
        questions = []
        if "压力不足" in content or "压力" in content:
            questions.append("设备压力上不去应该先查哪里？")
            questions.append("液压泵压力不足怎么办？")
        if "维护" in content:
            questions.append("设备多久需要维护一次？")
        if "质量" in content:
            questions.append("质量异常处理流程是什么？")
        return questions[:5]
