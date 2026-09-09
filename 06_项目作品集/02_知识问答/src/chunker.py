"""
数据切分
接收一个文件路径 + 分块配置，输出一组 chunk（文本片段 + 元数据）。
"""
import glob
import os
import logging
import pypdfium2 as pdfium
from pathlib import Path
from dataclasses import dataclass
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

PROJECT_DIR = Path(__file__).parent.parent
MD_DIR = PROJECT_DIR / "data/cleaned/3-结构文本"
TXT_DIR = PROJECT_DIR / "data/cleaned/1-提取文本"
TMD_DIR = PROJECT_DIR / "data/cleaned/2-混合文本"

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

@dataclass
class Chunk:
    text: str
    metadata: dict


def chunk_by_title(text: str, source: str, chunk_size: int = 1024, overlap: int = 128) -> list[Chunk]:
    """
    输入：md 文本字符串 + source 文件名 + chunk_size + overlap
    逻辑：
        用 LangChain 的 MarkdownHeaderTextSplitter 按标题切第一刀
    切出来的块如果超过 chunk_size，用 RecursiveCharacterTextSplitter 切第二刀
    每个最终块包装成 Chunk 对象
    """
    headers_to_split = [
        ("#", "h1"),
        ("##", "h2"),
        ("###", "h3"),
    ]
    splitter_1 = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split) # langchain的ma标题切片器
    sub_docs = splitter_1.split_text(text)

    splitter_2 = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    sub_docs = splitter_2.split_documents(sub_docs)

    chunks = []
    for idx, sub_doc in enumerate(sub_docs):
        chunks.append(Chunk(
            text=sub_doc.page_content,  # Document 的文本在 .page_content
            metadata={
                "source": source,  # 变量，不加引号
                "chunk_idx": idx,  # 从 0 开始（行业惯例）
                "method": "title",
                "headers": sub_doc.metadata,
            }
        ))
    return chunks

def chunk_by_recursive(text: str, source: str, chunk_size: int = 1024, overlap: int = 128) -> list[Chunk]:
    """按行切割"""
    separators = ["\n\n", "\n", "。", ".", " ", ""]
    splitter_2 = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap, separators=separators)
    sub_docs = splitter_2.split_text(text)

    chunks = []
    for idx, sub_doc in enumerate(sub_docs):
        chunks.append(Chunk(
            text=sub_doc,
            metadata={
                "source": source,  # 变量，不加引号
                "chunk_idx": idx,  # 从 0 开始（行业惯例）
                "method": "recursive",
            }
        ))
    return chunks

def chunk_by_length(text: str, source: str, chunk_size: int = 1024, overlap: int = 128) -> list[Chunk]:
    """数字切割"""
    splitter_2 = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    sub_docs = splitter_2.split_text(text)

    chunks = []
    for idx, sub_doc in enumerate(sub_docs):
        chunks.append(Chunk(
            text=sub_doc,
            metadata={
                "source": source,  # 变量，不加引号
                "chunk_idx": idx,  # 从 0 开始（行业惯例）
                "method": "length",
            }
        ))
    return chunks

def chunk_by_page(file_path: Path, source: str) -> list[Chunk]:
    """pdf分页"""
    pdf = pdfium.PdfDocument(str(file_path))
    chunks = []
    for idx, page in enumerate(pdf):
        textpage = page.get_textpage()
        text = textpage.get_text_bounded()
        textpage.close()
        page.close()
        chunks.append(Chunk(
            text=text,
            metadata={
                "source": source,
                "page_idx": idx,
                "method": "page",
            }
        ))
    return chunks

def chunk_file(file_path: Path, method: str, chunk_size: int = 1024, overlap: int = 128) -> list[Chunk]:
    source = file_path.name
    if method == "page":
        return chunk_by_page(file_path, source)

    text = file_path.read_text(encoding="utf-8")
    if not text.strip():
        return []

    if method == "title":
        return chunk_by_title(text, source, chunk_size, overlap)
    elif method == "recursive":
        return chunk_by_recursive(text, source, chunk_size, overlap)
    elif method == "length":
        return chunk_by_length(text, source, chunk_size, overlap)
    else:
        logger.error(f"未知分块方式: {method}")
        return []