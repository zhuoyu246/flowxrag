"""
Pydantic Settings 配置管理
- 支持 .env 文件自动加载
- 多环境支持：development / production / test
- 所有配置均有默认值，无 DB/Redis 时降级运行
"""
from __future__ import annotations

from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────
    app_env: str = "development"
    app_title: str = "CRAG Expert System"
    app_version: str = "2.0.0"
    log_level: str = "INFO"

    # ── LLM (OpenAI-compatible) ──────────────────────────
    openai_api_key: str = ""
    openai_api_base: str = "https://api.deepseek.com"
    openai_model: str = "deepseek-chat"
    openai_max_tokens: int = 4096

    # ── Embedding ────────────────────────────────────────
    embedding_provider: str = "api"
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"

    # ── Tavily Web Search ────────────────────────────────
    tavily_api_key: str = ""

    # ── LangSmith Observability ──────────────────────────
    langchain_api_key: str = ""
    langsmith_api_key: str = ""
    langchain_project: str = "crag-expert-system"
    langchain_endpoint: str = ""
    langsmith_tracing: str = "false"

    # ── PostgreSQL ───────────────────────────────────────
    # 示例: postgresql+asyncpg://crag:secret@localhost:5432/crag
    database_url: str = ""

    # ── Redis ────────────────────────────────────────────
    # 示例: redis://localhost:6379/0
    redis_url: str = ""

    # ── JWT 认证 ──────────────────────────────────────────
    jwt_secret_key: str = "change-me-in-production-32chars!!"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440          # 24 小时

    # ── 功能开关 ──────────────────────────────────────────
    require_auth: bool = False              # 生产环境设为 True
    cache_enabled: bool = True             # Redis 问答缓存
    cache_ttl_seconds: int = 3600          # 缓存 1 小时
    rate_limit_per_minute: int = 20        # 每 IP 每分钟最多 20 次 /chat

    # ── CORS ──────────────────────────────────────────────
    cors_origins: list[str] = ["*"]

    # ── CRAG 调优 ─────────────────────────────────────────
    auto_local_score_threshold: float = 0.55
    local_first_mode: bool = True

    # The repository intentionally supports the local FAISS implementation only.
    # Fail fast if an environment accidentally asks for a different store.
    vector_store: str = "faiss"
    kafka_bootstrap_servers: str = ""
    kafka_document_topic: str = "rag-document-change"
    kafka_document_dlq_topic: str = "rag-document-dlq"
    mysql_cdc_enabled: bool = False
    mysql_cdc_database_url: str = ""
    otel_enabled: bool = False
    otel_exporter: str = "console"
    otel_exporter_otlp_endpoint: str = ""

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level 必须是 {allowed} 之一")
        return upper

    @field_validator("vector_store")
    @classmethod
    def validate_vector_store(cls, v: str) -> str:
        if v.lower() != "faiss":
            raise ValueError("Only VECTOR_STORE=faiss is supported by this project")
        return "faiss"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def db_enabled(self) -> bool:
        return bool(self.database_url)

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
