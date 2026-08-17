"""Memory management routes."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db_optional
from backend.core.exceptions import AppError, ErrorCode
from backend.models.user import User
from backend.schemas.memory import MemoryCreate, MemoryResponse, MemoryUpdate
from backend.services.memory_service import (
    create_memory,
    deactivate_all_memories,
    delete_memory,
    get_memory,
    list_memories,
    update_memory,
)

router = APIRouter(prefix="/memories", tags=["memory"])


@router.get("", response_model=List[MemoryResponse])
async def get_memories(
    status: str | None = Query("active"),
    include_inactive: bool = False,
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
):
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Database is not configured", 503)
    memories = await list_memories(db, current_user, status=status, include_inactive=include_inactive)
    return [MemoryResponse.model_validate(memory) for memory in memories]


@router.post("", response_model=MemoryResponse, status_code=201)
async def add_memory(
    req: MemoryCreate,
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
):
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Database is not configured", 503)
    memory = await create_memory(
        db,
        current_user,
        req.content,
        category=req.category,
        memory_key=req.memory_key,
        status=req.status,
        source="manual",
    )
    await db.refresh(memory)
    return MemoryResponse.model_validate(memory)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def patch_memory(
    memory_id: int,
    req: MemoryUpdate,
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
):
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Database is not configured", 503)
    memory = await get_memory(db, memory_id, current_user)
    if memory is None:
        raise AppError(ErrorCode.NOT_FOUND, "Memory not found", 404)
    memory = await update_memory(
        db,
        memory,
        content=req.content,
        category=req.category,
        memory_key=req.memory_key,
        status=req.status,
        is_active=req.is_active,
    )
    await db.refresh(memory)
    return MemoryResponse.model_validate(memory)


@router.delete("/{memory_id}", status_code=204)
async def remove_memory(
    memory_id: int,
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
):
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Database is not configured", 503)
    deleted = await delete_memory(db, memory_id, current_user)
    if not deleted:
        raise AppError(ErrorCode.NOT_FOUND, "Memory not found", 404)


@router.delete("", response_model=dict)
async def clear_memories(
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
):
    if db is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Database is not configured", 503)
    count = await deactivate_all_memories(db, current_user)
    return {"status": "ok", "deactivated": count}
