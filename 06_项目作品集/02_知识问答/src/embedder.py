"""
embedder.py - Embedding 模块
支持文本模型（BGE-M3 / BGE-Large-zh）和多模态模型（BGE-VL-Large）
"""

import logging
import numpy as np
from dataclasses import dataclass
from sentence_transformers import SentenceTransformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    vectors: np.ndarray       # shape (n, dim)
    texts: list[str]
    metadatas: list[dict]


class TextEmbedder:
    """文本 embedding：BGE-M3 / BGE-Large-zh-v1.5"""

    def __init__(self, model_name: str, device: str = "cuda", truncate_dim: int = 0):
        logger.info(f"加载 embedding 模型: {model_name}, truncate_dim={truncate_dim}")
        self.model_name = model_name
        self.truncate_dim = truncate_dim
        self.model = SentenceTransformer(
            model_name, device=device,
            truncate_dim=truncate_dim if truncate_dim > 0 else None
        )
        effective_dim = truncate_dim if truncate_dim > 0 else self.model.get_sentence_embedding_dimension()
        logger.info(f"模型加载完成，维度: {effective_dim}, max_seq_length: {self.model.max_seq_length}")

    def encode(self, chunks: list, batch_size: int = 32) -> EmbeddingResult:
        """批量 encode 文档端（不加前缀）。"""
        texts = [chunk.text for chunk in chunks]
        metadatas = [chunk.metadata for chunk in chunks]

        vectors = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        return EmbeddingResult(vectors=np.array(vectors), texts=texts, metadatas=metadatas)

    def encode_query(self, query: str) -> np.ndarray:
        """encode 查询端（加前缀）。"""
        prefix = "为这个句子生成表示以用于检索相关段落: "
        vector = self.model.encode(prefix + query, normalize_embeddings=True)
        return np.array(vector)


class MultimodalEmbedder:
    """多模态 embedding：BGE-VL-Large（SentenceTransformer 兼容格式）"""

    def __init__(self, model_name: str, device: str = "cuda", truncate_dim: int = 0):
        logger.info(f"加载多模态模型: {model_name}")
        self.model_name = model_name
        self.model = SentenceTransformer(
            model_name, device=device, trust_remote_code=True
        )
        logger.info(f"多模态模型加载完成，维度: {self.model.get_sentence_embedding_dimension()}")

    def encode(self, chunks: list, batch_size: int = 8) -> EmbeddingResult:
        """对 PDF 页面文本做 embedding。"""
        texts = [chunk.text for chunk in chunks]
        metadatas = [chunk.metadata for chunk in chunks]

        vectors = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        return EmbeddingResult(vectors=np.array(vectors), texts=texts, metadatas=metadatas)

    def encode_query(self, query: str) -> np.ndarray:
        """文本查询 embedding。"""
        prefix = "为这个句子生成表示以用于检索相关段落: "
        vector = self.model.encode(prefix + query, normalize_embeddings=True)
        return np.array(vector)


def get_embedder(model_name: str, model_type: str, truncate_dim: int = 0):
    """工厂函数：根据类型返回对应 embedder。"""
    if model_type == "text":
        return TextEmbedder(model_name, truncate_dim=truncate_dim)
    elif model_type == "multimodal":
        return MultimodalEmbedder(model_name, truncate_dim=truncate_dim)
    else:
        raise ValueError(f"未知模型类型: {model_type}")