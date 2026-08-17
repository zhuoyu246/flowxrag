"""认证路由：注册 / 登录 / 获取当前用户"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db_optional
from backend.core.config import settings
from backend.core.exceptions import AppError, ErrorCode
from backend.models.user import User
from backend.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from backend.services.auth_service import login_user, register_user

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    req: RegisterRequest,
    db: AsyncSession | None = Depends(get_db_optional),
):
    """注册新用户。需要配置 DATABASE_URL。"""
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "数据库未配置，无法注册", 503)
    user = await register_user(db, req)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    db: AsyncSession | None = Depends(get_db_optional),
):
    """登录并返回 JWT Token。"""
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "数据库未配置，无法登录", 503)
    _, token = await login_user(db, req)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User | None = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    if current_user is None:
        raise AppError(ErrorCode.AUTH_UNAUTHORIZED, "请先登录", 401)
    return UserResponse.model_validate(current_user)
