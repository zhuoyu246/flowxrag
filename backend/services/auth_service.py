"""
JWT 认证服务
- 密码哈希：bcrypt（passlib）
- Token 生成/验证：python-jose
- 用户注册/登录业务逻辑
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.exceptions import AppError, ErrorCode
from backend.core.logging import get_logger
from backend.models.user import User, UserRole
from backend.schemas.auth import LoginRequest, RegisterRequest

logger = get_logger(__name__)

# ── 密码工具 ──────────────────────────────────────────────
def _truncate(password: str) -> str:
    """bcrypt 最大支持 72 字节，超出部分按字节截断。"""
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(plain), hashed.encode("utf-8"))
    except ValueError:
        logger.warning("invalid_password_hash")
        return False


# ── JWT 工具 ──────────────────────────────────────────────
def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """解码 JWT，失败时抛出 AppError。"""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise AppError(ErrorCode.AUTH_EXPIRED_TOKEN, "Token 已过期，请重新登录", 401)
    except JWTError:
        raise AppError(ErrorCode.AUTH_INVALID_TOKEN, "无效的 Token", 401)


# ── 用户业务逻辑 ──────────────────────────────────────────
async def register_user(db: AsyncSession, req: RegisterRequest) -> User:
    """注册新用户，邮箱唯一校验。"""
    existing = await db.scalar(select(User).where(User.email == req.email))
    if existing:
        raise AppError(ErrorCode.AUTH_USER_EXISTS, f"邮箱 {req.email} 已被注册", 409)

    user = User(
        email=req.email,
        username=req.username,
        hashed_password=hash_password(req.password),
        role=UserRole.USER,
    )
    db.add(user)
    await db.flush()
    logger.info("user_registered", user_id=user.id, email=user.email)
    return user


async def login_user(db: AsyncSession, req: LoginRequest) -> tuple[User, str]:
    """登录验证，返回 (user, access_token)。"""
    user = await db.scalar(select(User).where(User.email == req.email))
    if not user or not verify_password(req.password, user.hashed_password):
        raise AppError(ErrorCode.AUTH_INVALID_CREDS, "邮箱或密码错误", 401)
    if not user.is_active:
        raise AppError(ErrorCode.AUTH_FORBIDDEN, "账号已被禁用", 403)

    token = create_access_token(user.id, user.role.value)
    logger.info("user_login", user_id=user.id, email=user.email)
    return user, token


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    return await db.scalar(select(User).where(User.id == user_id))
