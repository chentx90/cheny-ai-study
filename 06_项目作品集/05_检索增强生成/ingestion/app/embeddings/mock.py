import hashlib
import random
from typing import List
from .base import BaseEmbedding


class MockEmbedding(BaseEmbedding):
    """模拟 Embedding 服务，用于本地开发和测试。

    实现策略：

    1. 对输入文本计算 MD5 哈希，取前 8 个十六进制字符转为整数作为随机种子。
    2. 使用该种子初始化 ``random.Random``，确保相同文本始终产出相同的向量。
    3. 生成 ``dimension`` 维的均匀随机浮点数，范围在 ``[-1, 1]`` 之间。

    注意：此实现与后端 ``backend/app/services/embeddings.py`` 中的
    ``MockEmbeddingService`` 逻辑一致，在两端可保持测试对齐。
    """

    def __init__(self, dimension: int = 1536):
        """初始化 MockEmbedding。

        Args:
            dimension: embedding 向量的维度，默认 1536（与 text-embedding-3-small 一致）。
        """
        self.dimension = dimension

    def embed(self, text: str) -> List[float]:
        """对输入文本生成确定性伪随机 embedding 向量。

        Args:
            text: 待编码的文本字符串。

        Returns:
            长度为 ``self.dimension`` 的浮点数向量。
        """
        seed = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed)
        return [rng.uniform(-1, 1) for _ in range(self.dimension)]
