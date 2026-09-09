"""文档身份工具：内容归一化、指纹计算、标题提取。

用于入库去重与标识：
  - normalize_text: 折叠空白，使同内容不同排版得到一致指纹。
  - compute_content_hash: SHA256(归一化正文) 叠加 business_domain。
  - derive_title: 按优先级确定标题（手动 > LLM > 正文首行/markdown 标题 > 文件名）。
"""
import re
import hashlib
from typing import Optional


def normalize_text(text: str) -> str:
    """折叠所有连续空白为单个空格并去首尾，保证排版差异不影响指纹。"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def compute_content_hash(text: str, business_domain: Optional[str] = None) -> str:
    """对归一化正文 + 业务域计算 SHA256 指纹。"""
    base = normalize_text(text)
    domain = (business_domain or "").strip().lower()
    digest = hashlib.sha256(f"{domain}\x00{base}".encode("utf-8")).hexdigest()
    return digest


def _title_from_content(text: str, max_len: int = 50) -> str:
    """从正文提取标题：优先首个 markdown 一级标题，否则首个非空行，截断。"""
    if not text:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # markdown 标题去掉前导 #
        m = re.match(r"^#{1,6}\s+(.*)$", stripped)
        candidate = m.group(1).strip() if m else stripped
        if candidate:
            return candidate[:max_len]
    return ""


def derive_title(
    text: str,
    manual: Optional[str] = None,
    llm_title: Optional[str] = None,
    filename_stem: Optional[str] = None,
) -> str:
    """按优先级返回标题：手动 > LLM 提取 > 正文首行/标题 > 文件名兜底。"""
    if manual and manual.strip():
        return manual.strip()
    if llm_title and llm_title.strip():
        return llm_title.strip()[:80]
    from_content = _title_from_content(text)
    if from_content:
        return from_content
    if filename_stem and filename_stem.strip():
        return filename_stem.strip()
    return "未命名文档"
