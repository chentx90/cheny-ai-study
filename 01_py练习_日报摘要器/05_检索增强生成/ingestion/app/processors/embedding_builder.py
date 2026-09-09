"""Embedding 构建器。

负责将 ``Chunk`` 或 ``DataAsset`` 的文本内容交给 ``BaseEmbedding`` 实现类，
生成对应的向量表示（List[float]）。

关键职责：

1. ``build_embedding_text``：委托给 ``Chunk.build_embedding_text()``，
   拼接一段富含上下文的信息文本，作为 embedding 模型的输入。
2. ``embed_chunk``：为 ``Chunk`` 生成 embedding 向量。
3. ``embed_data_asset``：为 ``DataAsset`` 生成 embedding 向量。

实际使用时，需传入 ``BaseEmbedding`` 的具体实现（如 ``MockEmbedding``
用于本地开发/测试，或真实的 OpenAI / Azure OpenAI embedding 服务类）。
"""
from typing import List
from ..schemas import Chunk
from ..embeddings.base import BaseEmbedding


class EmbeddingBuilder:
    """负责将 Chunk 或 DataAsset 文本转换为 embedding 向量的构建器。"""

    def __init__(self, embedding_service: BaseEmbedding):
        """初始化构建器，注入 embedding 服务实例。

        Args:
            embedding_service: 实现了 ``BaseEmbedding.embed(text)`` 接口的服务，
                                如 ``MockEmbedding`` 或第三方 SDK 封装类。
        """
        self.embedding_service = embedding_service

    def build_embedding_text(self, chunk: Chunk) -> str:
        """委托 ``Chunk.build_embedding_text()`` 获取 embedding 输入文本。

        Args:
            chunk: 待处理的 ``Chunk``。

        Returns:
            拼接后的、适合作为 embedding 输入的文本字符串。
        """
        return chunk.build_embedding_text()

    def embed_chunk(self, chunk: Chunk) -> List[float]:
        """为 ``Chunk`` 生成 embedding 向量。

        Args:
            chunk: 待向量化的 ``Chunk``。

        Returns:
            embedding 向量（浮点数列表）。
        """
        text = self.build_embedding_text(chunk)
        return self.embedding_service.embed(text)

    def embed_data_asset(self, asset) -> List[float]:
        """为 ``DataAsset`` 生成 embedding 向量。

        注：``DataAsset`` 类上应实现 ``build_embedding_text()`` 方法，
        与 ``Chunk`` 保持一致的接口约定。

        Args:
            asset: 待向量化的 ``DataAsset``（或实现 ``build_embedding_text`` 的对象）。

        Returns:
            embedding 向量（浮点数列表）。
        """
        text = asset.build_embedding_text()
        return self.embedding_service.embed(text)
