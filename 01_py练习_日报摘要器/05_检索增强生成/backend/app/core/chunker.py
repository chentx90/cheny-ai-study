"""文本分块器：从 ingestion 模块迁入，消除跨包依赖。

原 ingestion/app/processors/chunker.py 依赖 ingestion/app/schemas.Chunk，
这里改用本地 dataclass，与 ingestion_service 的 dict 转换保持一致。
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ChunkResult:
    section_path: str
    title_context: str
    content: str
    summary: str
    preset_questions: List[str] = field(default_factory=list)
    physical_context: Optional[dict] = None


class Chunker:
    MAX_CHARS = 800

    def __init__(self, title_context: str, section_path: str = "", max_chars: int = None, overlap: int = 0):
        self.title_context = title_context
        self.section_path = section_path
        self.max_chars = max_chars if max_chars and max_chars > 0 else self.MAX_CHARS
        self.overlap = max(0, overlap or 0)

    def chunk_text(self, text: str, section_path: str = None) -> List[ChunkResult]:
        if section_path:
            self.section_path = section_path

        sections = self._split_sections(text)
        chunks: List[ChunkResult] = []
        for local_section_path, section_text in sections:
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n', section_text) if p.strip()]
            current = ""
            for para in paragraphs:
                for part in self._split_large_block(para):
                    candidate_len = len(current) + len(part)
                    if candidate_len <= self.max_chars:
                        current = f"{current}\n\n{part}".strip() if current else part
                    else:
                        if current:
                            chunks.append(self._make(current, len(chunks), local_section_path))
                            tail = current[-self.overlap:] if self.overlap and not self._is_table_block(part) else ""
                            if tail and len(tail) + len(part) + 2 > self.max_chars:
                                tail = ""
                            current = f"{tail}\n\n{part}".strip() if tail else part
                        else:
                            current = part
            if current:
                chunks.append(self._make(current, len(chunks), local_section_path))
        return chunks

    def _split_sections(self, text: str) -> List[tuple[str, str]]:
        base_path = self.section_path
        sections: List[tuple[str, List[str]]] = []
        heading_stack: List[str] = []
        current_lines: List[str] = []
        current_path = base_path

        for block in [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]:
            match = re.match(r'^(#{1,6})\s+(.+)$', block)
            if match:
                if current_lines and self._has_body_content(current_lines):
                    sections.append((current_path, current_lines))
                level = len(match.group(1))
                title = match.group(2).strip()
                heading_stack = heading_stack[:level - 1]
                heading_stack.append(title)
                current_path = " > ".join([base_path, *heading_stack]) if base_path else " > ".join(heading_stack)
                current_lines = [block]
            else:
                current_lines.append(block)

        if current_lines and self._has_body_content(current_lines):
            sections.append((current_path, current_lines))
        return [(path, "\n\n".join(lines)) for path, lines in sections] or [(base_path, text)]

    def _has_body_content(self, lines: List[str]) -> bool:
        return any(not re.match(r'^#{1,6}\s+.+$', line.strip()) for line in lines)

    def _split_large_block(self, block: str) -> List[str]:
        if len(block) <= self.max_chars:
            return [block]

        lines = block.splitlines()
        if len(lines) > 2 and lines[0].startswith("|") and lines[1].startswith("|"):
            header = lines[:2]
            parts = []
            current = header[:]
            for row in lines[2:]:
                candidate = "\n".join([*current, row])
                if len(candidate) > self.max_chars and len(current) > 2:
                    parts.append("\n".join(current))
                    current = [*header, row]
                else:
                    current.append(row)
            if current:
                parts.append("\n".join(current))
            return parts

        parts = []
        start = 0
        step = max(1, self.max_chars)
        while start < len(block):
            parts.append(block[start:start + step])
            start += step
        return parts

    def _is_table_block(self, block: str) -> bool:
        lines = block.lstrip().splitlines()
        return len(lines) > 1 and lines[0].startswith("|") and lines[1].startswith("|")

    def _make(self, content: str, index: int, section_path: str = None) -> ChunkResult:
        summary = content[:100] + "..." if len(content) > 100 else content
        return ChunkResult(
            section_path=section_path or self.section_path,
            title_context=self.title_context,
            content=content,
            summary=summary,
        )
