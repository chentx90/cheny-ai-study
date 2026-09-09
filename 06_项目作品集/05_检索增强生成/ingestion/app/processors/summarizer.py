"""摘要生成器。

对 ``Chunk`` 的内容进行规则化的文本摘要，策略为：

1. 将换行替换为空格，按句号（。）拆分句子。
2. 取前两句作为摘要。
3. 若总长度超过 200 字符，进行截断补 "..."。

注意：此规则摘要仅为管线中的轻量预处理步骤。
生产环境中通常会替换为 LLM 富化摘要，以获得更高质量的概括性描述。
"""
from ..schemas import Chunk


class Summarizer:
    """规则文本摘要器，基于句子拆分生成紧凑摘要。"""

    def summarize(self, chunk: Chunk) -> str:
        """为 ``Chunk`` 生成摘要。

        Args:
            chunk: 待摘要的 ``Chunk`` 对象。

        Returns:
            摘要字符串，最长不超过 200 字符。
        """
        text = chunk.content.strip()
        if not text:
            return ""
        sentences = text.replace("\n", " ").split("。")
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return text[:100] + ("..." if len(text) > 100 else "")
        summary = "。".join(sentences[:2]) + "。"
        if len(summary) > 200:
            summary = summary[:197] + "..."
        return summary
