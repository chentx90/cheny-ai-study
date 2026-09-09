from abc import ABC, abstractmethod


class BaseWriter(ABC):
    """所有写入器的抽象基类。

    定义通用的连接/关闭生命周期接口，确保不同后端写入器
    （Postgres、JSON 等）有一致的契约。
    """

    @abstractmethod
    def connect(self):
        """建立与目标存储的连接（如数据库连接池）。"""
        pass

    @abstractmethod
    def close(self):
        """关闭连接，释放资源（如关闭连接池）。"""
        pass
