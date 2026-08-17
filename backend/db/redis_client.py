"""
Redis 异步连接管理
- 未配置 REDIS_URL 时优雅降级（返回 None）
- 提供 ping、get_redis 等工具函数
- 连接池复用，避免每次请求重建连接
"""
from __future__ import annotations

import redis.asyncio as aioredis

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis | None:
    """获取 Redis 客户端，未配置时返回 None。"""
    global _redis
    if not settings.redis_url:
        return None
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("redis_closed")


async def ping_redis() -> bool:
    """健康检查：返回 Redis 是否可达。"""
    client = await get_redis()
    if client is None:
        return False
    try:
        return await client.ping()
    except Exception as exc:
        logger.warning("redis_ping_failed", error=str(exc))
        return False
