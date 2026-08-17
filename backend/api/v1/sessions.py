"""会话路由：创建、列表、历史、删除"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db_optional
from backend.core.exceptions import AppError, ErrorCode
from backend.models.session import ChatSession
from backend.models.user import User
from backend.schemas.session import SessionCreate, SessionDetail, SessionResponse

router = APIRouter(prefix="/sessions", tags=["会话管理"])


@router.get("", response_model=List[SessionResponse])
async def list_sessions(
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
):
    """获取当前用户的所有会话列表。"""
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "数据库未配置", 503)
    user_id = current_user.id if current_user else None
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()
    return [SessionResponse.model_validate(s) for s in sessions]


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    req: SessionCreate,
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
):
    """创建新会话。"""
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "数据库未配置", 503)
    session = ChatSession(
        user_id=current_user.id if current_user else None,
        title=req.title,
    )
    db.add(session)
    await db.flush()
    return SessionResponse.model_validate(session)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: int,
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
):
    """获取会话详情（含历史消息）。"""
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "数据库未配置", 503)
    session = await db.get(ChatSession, session_id)
    if not session:
        raise AppError(ErrorCode.SESSION_NOT_FOUND, f"会话 {session_id} 不存在", 404)
    # 权限：只有创建者或 Admin 可查看
    if current_user and session.user_id and session.user_id != current_user.id:
        from backend.models.user import UserRole
        if current_user.role != UserRole.ADMIN:
            raise AppError(ErrorCode.SESSION_FORBIDDEN, "无权访问此会话", 403)
    return SessionDetail.model_validate(session)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
):
    """删除会话（含所有历史消息）。"""
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "数据库未配置", 503)
    session = await db.get(ChatSession, session_id)
    if not session:
        raise AppError(ErrorCode.SESSION_NOT_FOUND, f"会话 {session_id} 不存在", 404)
    await db.delete(session)
