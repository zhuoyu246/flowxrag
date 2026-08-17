"""
任务状态查询路由
- GET /api/v1/tasks/{task_id}   — 查询单个 Celery 任务状态
- GET /api/v1/tasks             — 查询最近任务列表（从 DB）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db_optional
from backend.core.exceptions import AppError, ErrorCode

router = APIRouter(prefix="/tasks", tags=["异步任务"])


@router.get("/{task_id}")
async def get_task_status(task_id: str, current_user=Depends(get_current_user)) -> dict:
    """
    查询 Celery 任务执行状态。
    返回: {task_id, status, result, error}
    status: PENDING / STARTED / SUCCESS / FAILURE / RETRY
    """
    try:
        from backend.tasks.celery_app import celery_app
        task_result = celery_app.AsyncResult(task_id)
        status = task_result.status

        response: dict[str, Any] = {"task_id": task_id, "status": status}

        if status == "SUCCESS":
            response["result"] = task_result.result
        elif status == "FAILURE":
            response["error"] = str(task_result.info)
        elif status in ("STARTED", "RETRY"):
            response["info"] = str(task_result.info) if task_result.info else None

        return response
    except Exception as exc:
        raise AppError(ErrorCode.TASK_NOT_FOUND, f"任务 {task_id} 查询失败: {exc}", 404)


@router.get("")
async def list_recent_tasks(
    limit: int = 20,
    current_user=Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
) -> dict:
    """查询最近的文档处理任务记录（来自数据库）。"""
    if db is None:
        return {"tasks": [], "note": "数据库未配置，任务记录不可用"}

    from backend.models.document_record import DocumentRecord
    result = await db.execute(
        select(DocumentRecord)
        .order_by(DocumentRecord.created_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()
    return {
        "tasks": [
            {
                "id": r.id,
                "filename": r.filename,
                "status": r.status,
                "pages": r.pages,
                "chunks": r.chunks,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
    }
