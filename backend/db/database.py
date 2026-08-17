"""
SQLAlchemy 2.0 异步数据库引擎
- 支持 PostgreSQL（asyncpg 驱动）
- 未配置 DATABASE_URL 时优雅降级，不影响其他功能
- init_db() 在 app startup 时自动建表（开发用，生产用 Alembic）
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_engine = None
_session_factory: async_sessionmaker | None = None


def _get_engine():
    global _engine
    if _engine is None and settings.database_url:
        _engine = create_async_engine(
            settings.database_url,
            echo=not settings.is_production,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def _get_factory() -> async_sessionmaker | None:
    global _session_factory
    if _session_factory is None:
        engine = _get_engine()
        if engine:
            _session_factory = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：async with get_db() as db"""
    factory = _get_factory()
    if factory is None:
        raise RuntimeError("数据库未配置，请在 .env 中设置 DATABASE_URL")
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def db_context() -> AsyncGenerator[AsyncSession, None]:
    """服务层直接使用的上下文管理器。"""
    async for session in get_db():
        yield session


async def init_db() -> None:
    """启动时建表（开发环境直接建，生产环境建议用 Alembic）。"""
    from backend.models.base import Base  # noqa: avoid circular
    import backend.models.chat_history  # noqa: F401
    import backend.models.document_record  # noqa: F401
    import backend.models.session  # noqa: F401
    import backend.models.user  # noqa: F401
    import backend.models.user_memory  # noqa: F401

    engine = _get_engine()
    if engine is None:
        logger.warning("db_init_skipped", reason="DATABASE_URL not configured")
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_memory_schema(conn)
    logger.info("db_initialized")


async def _ensure_memory_schema(conn) -> None:
    """Add memory columns for existing development databases."""
    statements = [
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS memory_key VARCHAR(120) NOT NULL DEFAULT 'general'",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'active'",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS source_session_id INTEGER NULL",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS source_message_id INTEGER NULL",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS importance FLOAT NOT NULL DEFAULT 0.7",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS use_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP WITH TIME ZONE NULL",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE NULL",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS is_sensitive BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS extra JSON NOT NULL DEFAULT '{}'",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_memory_key ON user_memories (memory_key)",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_status ON user_memories (status)",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_source_session_id ON user_memories (source_session_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_source_message_id ON user_memories (source_message_id)",
    ]
    for statement in statements:
        await conn.execute(text(statement))


async def close_db() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("db_closed")
