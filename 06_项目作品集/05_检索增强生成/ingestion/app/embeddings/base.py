from abc import ABC, abstractmethod
from typing import List


class BaseEmbedding(ABC):
    """所有 Embedding 服务的抽象基类。

    定义了统一的文本向量化接口，确保不同 embedding 后端（OpenAI、
    自部署模型、模拟服务等）能够无缝替换。
    """

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """将一段文本编码为 embedding 向量。

        Args:
            text: 待编码的文本字符串。

        Returns:
            浮点数列表，表示文本的向量表示。
        """
        pass
