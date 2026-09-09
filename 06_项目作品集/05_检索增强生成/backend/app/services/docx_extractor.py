"""DOCX to Markdown extraction helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


_END_PUNCTUATION = set("。；;：:，,、.!！？?")
_NUMBERED_HEADING_RE = re.compile(r"^([一二三四五六七八九十]+[、.]|\d+([.、]\d+)*[、.]?)\s*\S+")
_PAGE_MARK_RE = re.compile(r"^第\s*\d+\s*页\s*共\s*\d+(\s*\d+)?\s*$")


@dataclass
class ExtractedDocx:
    text: str
    tables: int
    paragraphs: int


class NumberingResolver:
    """Resolve Word automatic numbering labels for paragraphs."""

    def __init__(self, doc):
        self._num_to_abstract = {}
        self._levels = {}
        self._counters = {}
        try:
            root = doc.part.numbering_part.element
        except Exception:
            return

        for abstract in root.findall(qn("w:abstractNum")):
            abstract_id = abstract.get(qn("w:abstractNumId"))
            for level in abstract.findall(qn("w:lvl")):
                ilvl = level.get(qn("w:ilvl")) or "0"
                fmt_el = level.find(qn("w:numFmt"))
                text_el = level.find(qn("w:lvlText"))
                start_el = level.find(qn("w:start"))
                self._levels[(abstract_id, ilvl)] = {
                    "fmt": fmt_el.get(qn("w:val")) if fmt_el is not None else "decimal",
                    "text": text_el.get(qn("w:val")) if text_el is not None else f"%{int(ilvl) + 1}.",
                    "start": int(start_el.get(qn("w:val"))) if start_el is not None else 1,
                }

        for num in root.findall(qn("w:num")):
            num_id = num.get(qn("w:numId"))
            abstract_ref = num.find(qn("w:abstractNumId"))
            if abstract_ref is not None:
                self._num_to_abstract[num_id] = abstract_ref.get(qn("w:val"))

    def label_for(self, paragraph: Paragraph) -> Optional[tuple[str, int, str]]:
        num_id, ilvl = _paragraph_numbering(paragraph)
        if num_id is None:
            return None
        abstract_id = self._num_to_abstract.get(num_id)
        level = self._levels.get((abstract_id, str(ilvl)), {})
        fmt = level.get("fmt", "decimal")
        if fmt == "bullet":
            return "-", ilvl, fmt

        counters = self._counters.setdefault(num_id, {})
        counters[ilvl] = counters.get(ilvl, level.get("start", 1) - 1) + 1
        for deeper in [key for key in counters if key > ilvl]:
            counters.pop(deeper, None)

        pattern = level.get("text", f"%{ilvl + 1}.")
        label = pattern
        for idx in range(ilvl + 1):
            value = counters.get(idx, 1)
            label = label.replace(f"%{idx + 1}", _format_number(value, fmt))
        return label, ilvl, fmt


def extract_docx_markdown(file_path: str | Path) -> ExtractedDocx:
    path = Path(file_path)
    doc = Document(path)
    numbering = NumberingResolver(doc)
    blocks = []
    table_count = 0
    paragraph_count = 0

    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            rendered = _render_paragraph(block, numbering)
            if rendered:
                blocks.append(rendered)
                paragraph_count += 1
        elif isinstance(block, Table):
            rendered = _render_table(block)
            if rendered:
                blocks.append(rendered)
                table_count += 1

    return ExtractedDocx(
        text="\n\n".join(blocks),
        tables=table_count,
        paragraphs=paragraph_count,
    )


def _iter_blocks(doc) -> Iterable[Paragraph | Table]:
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _render_paragraph(paragraph: Paragraph, numbering: NumberingResolver) -> str:
    text = _clean_text(paragraph.text)
    if not text or _is_noise_text(text):
        return ""

    numbering_info = numbering.label_for(paragraph)
    numbered_text = text
    numbering_level = None
    number_format = ""
    if numbering_info:
        label, numbering_level, number_format = numbering_info
        if label and not _already_numbered(text, label):
            sep = " " if label.endswith((".", ")", "-", "、")) else " "
            numbered_text = f"{label}{sep}{text}".strip()

    heading_level = _heading_level(paragraph, numbered_text, numbering_level, number_format)
    if heading_level:
        return f"{'#' * heading_level} {numbered_text}"
    return numbered_text


def _heading_level(
    paragraph: Paragraph,
    text: str,
    numbering_level: Optional[int],
    number_format: str,
) -> Optional[int]:
    style_name = getattr(paragraph.style, "name", "") or ""
    if style_name.startswith("Heading"):
        suffix = style_name.split()[-1]
        return int(suffix) if suffix.isdigit() else 2

    outline_level = _outline_level(paragraph)
    if outline_level is not None:
        return outline_level + 1

    plain = text.strip()
    if (
        numbering_level is not None
        and number_format != "bullet"
        and _looks_like_short_heading(paragraph, plain)
    ):
        return min(numbering_level + 2, 6)

    if _NUMBERED_HEADING_RE.match(plain) and _looks_like_short_heading(paragraph, plain):
        return 3 if "." in plain[:6] else 2

    if _looks_like_short_heading(paragraph, plain):
        return 2
    return None


def _looks_like_short_heading(paragraph: Paragraph, text: str) -> bool:
    if len(text) > 24 or any(char in text for char in "|&——-"):
        return False
    if any(char in text for char in "，,；;：:。.!！？?"):
        return False
    if text[-1:] in _END_PUNCTUATION:
        return False
    if len(text) <= 12:
        return True
    return _has_emphasis(paragraph)


def _is_noise_text(text: str) -> bool:
    if _PAGE_MARK_RE.match(text):
        return True
    compact = text.replace(" ", "")
    if " " in text and len(compact) <= 4 and not re.search(r"\d+[.、]\S+", compact):
        return True
    if len(compact) <= 1:
        return True
    return False


def _render_table(table: Table) -> str:
    rows = []
    width = 0
    for row in table.rows:
        cells = [_clean_text(cell.text).replace("\n", "<br>") for cell in row.cells]
        if any(cells):
            rows.append(cells)
            width = max(width, len(cells))
    if not rows:
        return ""

    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * width
    body = normalized[1:]

    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"

    lines = [fmt(header), fmt(separator)]
    lines.extend(fmt(row) for row in body)
    return "\n".join(lines)


def _paragraph_numbering(paragraph: Paragraph) -> tuple[Optional[str], int]:
    ppr = paragraph._p.pPr
    if ppr is None or ppr.numPr is None or ppr.numPr.numId is None:
        return None, 0
    num_id = str(ppr.numPr.numId.val)
    ilvl = int(ppr.numPr.ilvl.val) if ppr.numPr.ilvl is not None else 0
    return num_id, ilvl


def _outline_level(paragraph: Paragraph) -> Optional[int]:
    ppr = paragraph._p.pPr
    if ppr is None:
        return None
    outline = ppr.find(qn("w:outlineLvl"))
    if outline is None:
        return None
    try:
        return int(outline.get(qn("w:val")))
    except (TypeError, ValueError):
        return None


def _has_emphasis(paragraph: Paragraph) -> bool:
    return any(run.bold or (run.font.size and run.font.size.pt >= 14) for run in paragraph.runs)


def _already_numbered(text: str, label: str) -> bool:
    compact = text.strip()
    return compact.startswith(label) or bool(_NUMBERED_HEADING_RE.match(compact))


def _format_number(value: int, fmt: str) -> str:
    if fmt in {"upperRoman", "lowerRoman"}:
        roman = _to_roman(value)
        return roman if fmt == "upperRoman" else roman.lower()
    if fmt in {"upperLetter", "lowerLetter"}:
        letter = chr(ord("A") + ((value - 1) % 26))
        return letter if fmt == "upperLetter" else letter.lower()
    return str(value)


def _to_roman(value: int) -> str:
    pairs = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    result = []
    for number, roman in pairs:
        while value >= number:
            result.append(roman)
            value -= number
    return "".join(result)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
