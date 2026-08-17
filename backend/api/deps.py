"""
FastAPI 依赖注入集合
- get_db_optional: 数据库 Session（可选，无 DB 时返回 None）
- get_redis_optional: Redis 客户端（可选，无 Redis 时返回 None）
- get_current_user: JWT 解码 + 用户查询（require_auth=False 时返回 None）
- require_admin: 要求 Admin 角色
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.exceptions import AppError, ErrorCode
from backend.db.database import get_db
from backend.db.redis_client import get_redis
from backend.models.user import User, UserRole
from backend.services.auth_service import decode_token, get_user_by_id


# ── 数据库依赖（可选）────────────────────────────────────
async def get_db_optional():
    """数据库未配置时 yield None，已配置时 yield AsyncSession。"""
    if not settings.db_enabled:
        yield None
    else:
        async for session in get_db():
            yield session


# ── Redis 依赖（可选）────────────────────────────────────
async def get_redis_optional():
    """Redis 未配置时返回 None。"""
    if not settings.redis_enabled:
        return None
    return await get_redis()


# ── JWT 认证依赖 ──────────────────────────────────────────
async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Optional[AsyncSession] = Depends(get_db_optional),
) -> User | None:
    """
    从 Authorization: Bearer <token> 中提取用户。
    - require_auth=False（默认）：无 Token 时返回 None，不报错
    - require_auth=True：无 Token 或无效 Token 均抛 401
    """
    if not authorization:
        if settings.require_auth:
            raise AppError(ErrorCode.AUTH_UNAUTHORIZED, "请先登录", 401)
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError(ErrorCode.AUTH_INVALID_TOKEN, "Authorization 格式应为 Bearer <token>", 401)

    payload = decode_token(token)
    user_id = int(payload.get("sub", 0))

    if db is None:
        # 数据库未配置，仅解码 Token，返回虚拟用户信息
        return _mock_user_from_payload(payload, user_id)

    user = await get_user_by_id(db, user_id)
    if not user:
        raise AppError(ErrorCode.AUTH_INVALID_TOKEN, "用户不存在", 401)
    if not user.is_active:
        raise AppError(ErrorCode.AUTH_FORBIDDEN, "账号已被禁用", 403)
    return user


def _mock_user_from_payload(payload: dict, user_id: int) -> User:
    """无 DB 时从 Token payload 构造临时 User 对象（只读）。"""
    u = User.__new__(User)
    u.id = user_id
    u.email = payload.get("email", "")
    u.username = payload.get("username", "user")
    u.role = UserRole(payload.get("role", "user"))
    u.is_active = True
    return u


async def require_admin(current_user: User | None = Depends(get_current_user)) -> User:
    """路由依赖：要求 Admin 角色。"""
    if current_user is None:
        raise AppError(ErrorCode.AUTH_UNAUTHORIZED, "请先登录", 401)
    if current_user.role != UserRole.ADMIN:
        raise AppError(ErrorCode.AUTH_FORBIDDEN, "需要管理员权限", 403)
    return current_user
