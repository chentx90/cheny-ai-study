"""Embedding 服务子包。

提供文本向量化能力，定义标准抽象接口 ``BaseEmbedding``，
并提供 ``MockEmbedding`` 本地实现用于开发和测试。

生产环境可替换为 OpenAI / Azure OpenAI / Cohere 等第三方 embedding SDK。
"""
from .base import BaseEmbedding
from .mock import MockEmbedding

__all__ = ["BaseEmbedding", "MockEmbedding"]
