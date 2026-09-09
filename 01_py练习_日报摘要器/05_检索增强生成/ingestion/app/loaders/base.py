from abc import ABC, abstractmethod


class BaseLoader(ABC):
    """所有数据加载器的抽象基类。

    定义了统一的数据加载接口，确保不同格式的文件（PDF、Markdown、Excel、
    TXT、DOCX、PPTX、JSON 种子文件等）都能以一致的方式被解析和转换。

    子类必须实现 ``load`` 方法，将原始文件路径转换为结构化数据对象。
    """

    @abstractmethod
    def load(self, file_path: str, **kwargs) -> object:
        """从指定文件路径加载并解析内容。

        Args:
            file_path: 待加载的文件路径。
            **kwargs: 扩展参数（具体取决于子类实现）。

        Returns:
            解析后的结构化数据对象（如 Document、LoadedDocument 或
            List[DataAsset]）。
        """
        pass
