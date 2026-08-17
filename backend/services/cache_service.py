"""
Redis 缓存服务
- 问答缓存：相同问题直接返回，减少 LLM 调用费用
- 接口限流：每 IP 每分钟最多 N 次 /chat
- 分布式锁：防止同一 PDF 并发重复入库
"""
from __future__ import annotations

import hashlib
import json

import redis.asyncio as aioredis

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


def _cache_key(question: str) -> str:
    digest = hashlib.md5(question.strip().lower().encode()).hexdigest()
    return f"crag:chat:cache:{digest}"


def _rate_key(client_ip: str) -> str:
    return f"crag:rate:{client_ip}:chat"


def _lock_key(resource: str) -> str:
    return f"crag:lock:{resource}"


# ── 问答缓存 ──────────────────────────────────────────────
async def get_cached_answer(redis: aioredis.Redis, question: str) -> dict | None:
    """命中缓存返回 dict，未命中返回 None。"""
    if not settings.cache_enabled:
        return None
    try:
        raw = await redis.get(_cache_key(question))
        if raw:
            logger.debug("cache_hit", question_preview=question[:50])
            return json.loads(raw)
    except Exception as exc:
        logger.warning("cache_get_error", error=str(exc))
    return None


async def set_cached_answer(redis: aioredis.Redis, question: str, answer: dict) -> None:
    """写入缓存，TTL 由配置决定。"""
    if not settings.cache_enabled:
        return
    try:
        await redis.setex(
            _cache_key(question),
            settings.cache_ttl_seconds,
            json.dumps(answer, ensure_ascii=False),
        )
        logger.debug("cache_set", question_preview=question[:50], ttl=settings.cache_ttl_seconds)
    except Exception as exc:
        logger.warning("cache_set_error", error=str(exc))


async def invalidate_cache(redis: aioredis.Redis, question: str) -> None:
    """手动使某个问题的缓存失效。"""
    try:
        await redis.delete(_cache_key(question))
    except Exception:
        pass


# ── 接口限流 ──────────────────────────────────────────────
async def check_rate_limit(redis: aioredis.Redis, client_ip: str) -> bool:
    """返回 True 表示未超速，False 表示已超限。"""
    try:
        key = _rate_key(client_ip)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 60)
        allowed = count <= settings.rate_limit_per_minute
        if not allowed:
            logger.warning("rate_limited", client_ip=client_ip, count=count)
        return allowed
    except Exception as exc:
        logger.warning("rate_limit_check_error", error=str(exc))
        return True   # Redis 不可用时放行，避免雪崩


# ── 分布式锁 ──────────────────────────────────────────────
async def acquire_lock(redis: aioredis.Redis, resource: str, timeout: int = 30) -> bool:
    """尝试获取分布式锁，成功返回 True。"""
    try:
        return bool(await redis.set(_lock_key(resource), "1", ex=timeout, nx=True))
    except Exception:
        return True   # Redis 不可用时允许操作，降级处理


async def release_lock(redis: aioredis.Redis, resource: str) -> None:
    try:
        await redis.delete(_lock_key(resource))
    except Exception:
        pass
