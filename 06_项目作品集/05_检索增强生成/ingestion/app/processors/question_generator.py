"""问题生成器（基于规则）。

根据 ``Chunk`` 中的关键词匹配来生成预设问题，用于在检索结果中推荐
相关问题，提升检索命中率和用户引导体验。

⚠️ 注意：
    此模块已被 LLM 富化取代，当前为保留实现，供独立运行和测试时参考。
    在生产运行时，预设问题由大语言模型根据 Chunk 内容动态生成。
"""
from typing import List
from ..schemas import Chunk


class QuestionGenerator:
    """基于规则关键词的预设问题生成器。"""

    def generate(self, chunk: Chunk) -> List[str]:
        """根据 Chunk 内容的关键词匹配生成预设问题。

        当前支持的匹配规则：

        - "怎么"、"如何"、"怎样" → 问题："这个问题应该如何解决？"
        - "是什么"、"定义"     → 问题："这到底是什么？"
        - "为什么"             → 问题："为什么会这样？"
        - "注意"、"重要"       → 问题："有哪些注意事项？"
        - 长度 > 50 字符        → 问题："能简要概括一下吗？"

        最多返回 3 个问题。

        Args:
            chunk: 待生成问题的 ``Chunk``。

        Returns:
            预设问题字符串列表。
        """
        questions: List[str] = []
        content = chunk.content

        if "怎么" in content or "如何" in content or "怎样" in content:
            questions.append("这个问题应该如何解决？")
        if "是什么" in content or "定义" in content:
            questions.append("这到底是什么？")
        if "为什么" in content:
            questions.append("为什么会这样？")
        if "注意" in content or "重要" in content:
            questions.append("有哪些注意事项？")
        if len(content) > 50:
            questions.append("能简要概括一下吗？")

        return questions[:3]
