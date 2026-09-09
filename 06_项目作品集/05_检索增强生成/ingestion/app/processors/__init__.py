"""文本处理器子包。

提供流水线中段的各类文本处理能力，包括：

- **Chunker**：文本分块，将长文切分为语义独立、长度适中的 Chunk 列表。
- **Summarizer**：规则化摘要生成，为 Chunk 生成前两句精简摘要。
- **QuestionGenerator**：规则化问题生成（已被 LLM 富化取代，保留实现）。
- **EmbeddingBuilder**：将 Chunk/DataAsset 文本交给 Embedding 服务编码为向量。
- **DataAssetBuilder**：将 Excel 行数据构建为 DataAsset 对象。
"""
from .chunker import Chunker
from .summarizer import Summarizer
from .question_generator import QuestionGenerator
from .embedding_builder import EmbeddingBuilder
from .data_asset_builder import DataAssetBuilder

__all__ = ["Chunker", "Summarizer", "QuestionGenerator", "EmbeddingBuilder", "DataAssetBuilder"]
