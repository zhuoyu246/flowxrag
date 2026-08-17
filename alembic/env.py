"""
Alembic 迁移环境配置
- 从 DATABASE_URL 环境变量读取连接字符串
- 支持异步 asyncpg（自动转为同步 URL 供 Alembic 使用）
- 自动导入所有 ORM 模型，支持 --autogenerate
"""
from __future__ import annotations

import os
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 导入所有模型（触发 ORM 注册，支持 autogenerate）
from backend.models.base import Base
from backend.models.user import User  # noqa
from backend.models.session import ChatSession  # noqa
from backend.models.chat_history import ChatHistory  # noqa
from backend.models.document_record import DocumentRecord  # noqa

config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_sync_url() -> str:
    """从环境变量获取 DB URL，并转换为同步格式。"""
    url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))
    # asyncpg → psycopg2（Alembic 需要同步驱动）
    url = re.sub(r"postgresql\+asyncpg://", "postgresql://", url)
    return url


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不连接数据库。"""
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移。"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_sync_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
