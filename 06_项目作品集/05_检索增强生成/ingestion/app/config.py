from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """ingestion 模块的配置类。

    通过 ``pydantic_settings``（基于 Pydantic V2 的 Settings 管理）从环境
    变量或 ``.env`` 文件中加载配置。

    默认值专为本地开发和演示设计，生产环境应通过环境变量覆盖。

    Attributes:
        database_url: PostgreSQL 连接字符串。
        embedding_model: 用于生成向量时指定的 embedding 模型名称。
        embedding_dimension: 期望的 embedding 向量维度。
    """

    database_url: str = "postgresql://rag_user:rag_pass@localhost:5432/rag_db"
    """PostgreSQL 连接字符串。"""

    embedding_model: str = "text-embedding-3-small"
    """Embedding 模型名称，用于标识每条向量记录所使用的模型。"""

    embedding_dimension: int = 1536
    """Embedding 向量维度，应与所选 embedding 模型的输出维度一致。"""

    class Config:
        env_file = ".env"


settings = Settings()