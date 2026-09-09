from pathlib import Path

from pydantic import AliasChoices, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings


BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    postgres_dsn: str = Field(
        default="postgresql://rag_user:rag_pass@localhost:5433/rag_db",
        validation_alias="POSTGRES_DSN",
    )
    api_prefix: str = "/api"
    debug: bool = True
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:3001,http://localhost:3002,http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:3002",
        validation_alias="CORS_ORIGINS",
    )

    minio_endpoint: str = Field(default="localhost:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", validation_alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="rag-raw-files", validation_alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")
    local_object_storage: str = Field(
        default=str(BACKEND_DIR / "object_storage"),
        validation_alias="LOCAL_OBJECT_STORAGE",
    )

    ocr_base_url: str = Field(default="", validation_alias=AliasChoices("OCR_BASE_URL", "OCR_API_URL", "OCR_URL"))
    ocr_api_key: str = Field(default="", validation_alias=AliasChoices("OCR_API_KEY", "OCR_KEY"))
    ocr_model: str = Field(default="", validation_alias="OCR_MODEL")

    llm_api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    llm_base_url: str = Field(default="http://localhost:3000/v1", validation_alias="LLM_BASE_URL")
    llm_model: str = Field(default="gpt-4o-mini", validation_alias="LLM_MODEL")

    embedding_api_key: str = Field(default="", validation_alias="EMBEDDING_API_KEY")
    embedding_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="EMBEDDING_BASE_URL")
    embedding_model: str = Field(default="text-embedding-3-small", validation_alias="EMBEDDING_MODEL")
    embedding_dimension: int = Field(default=1536, validation_alias="EMBEDDING_DIMENSION")

    reranker_api_key: str = Field(default="", validation_alias=AliasChoices("RERANKER_API_KEY", "RERANKER_KEY"))
    reranker_base_url: str = Field(default="", validation_alias=AliasChoices("RERANKER_BASE_URL", "RERANKER_URL"))
    reranker_model: str = Field(default="", validation_alias="RERANKER_MODEL")

    @property
    def database_url(self) -> str:
        return self.postgres_dsn

    @property
    def local_object_storage_path(self) -> Path:
        path = Path(self.local_object_storage)
        return path if path.is_absolute() else BACKEND_DIR / path

    @property
    def resolved_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.llm_api_key

    @property
    def resolved_ocr_api_key(self) -> str:
        return self.ocr_api_key or self.llm_api_key

    @property
    def resolved_reranker_api_key(self) -> str:
        return self.reranker_api_key or self.llm_api_key

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() not in ("false", "0", "no", "off")
        return bool(v)


settings = Settings()
