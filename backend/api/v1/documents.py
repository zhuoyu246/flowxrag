"""
文档管理路由 v2（向后兼容 + 新增异步上传）
- GET  /documents                  — 知识库统计
- POST /documents/upload           — 同步 PDF 上传（小文件）
- POST /api/v1/documents/upload/async — 异步 PDF 上传（大文件，返回 task_id）
- DELETE /documents                — 清空（需 Admin）
- DELETE /documents/source         — 按文件名删除
- POST /documents/reindex          — 重建索引
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile

from backend.api.deps import get_current_user, get_db_optional, require_admin
from backend.core.exceptions import AppError, ErrorCode
from backend.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["文档管理"])


# ── 公共工具 ─────────────────────────────────────────────
async def _get_redis():
    from backend.db.redis_client import get_redis
    return await get_redis()


def _save_file(file: UploadFile):
    from backend.retriever import knowledge_base
    return knowledge_base.save_upload(file)


# ── 路由 ─────────────────────────────────────────────────
@router.get("/documents")
def documents():
    from backend.retriever import knowledge_base
    return knowledge_base.stats()


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db_optional),
):
    """同步上传（推荐小于 5MB 的 PDF）。大文件请使用 /api/v1/documents/upload/async。"""
    from backend.retriever import knowledge_base

    if not file.filename.lower().endswith(".pdf"):
        raise AppError(ErrorCode.DOC_INVALID_FORMAT, "仅支持 PDF 文件", 400)

    redis = await _get_redis()
    if redis:
        from backend.services.cache_service import acquire_lock, release_lock
        if not await acquire_lock(redis, f"upload:{file.filename}"):
            raise AppError(ErrorCode.DOC_UPLOAD_FAILED, "文件正在处理中，请稍后", 409)

    try:
        saved_path = knowledge_base.save_upload(file)
        result = knowledge_base.add_pdf(saved_path, file.filename)

        if db is not None:
            from backend.models.document_record import DocumentRecord
            record = DocumentRecord(
                filename=file.filename,
                pages=result.get("pages", 0),
                chunks=result.get("chunks_added", 0),
                status="success",
                uploaded_by=current_user.id if current_user else None,
            )
            db.add(record)
            await db.flush()

        from backend.core.metrics import METRICS
        METRICS.kb_chunks_total.set(knowledge_base.stats().get("total_chunks", 0))
        METRICS.rag_documents_total.set(knowledge_base.stats().get("source_count", 0))

        document_id = str(record.id) if db is not None else file.filename
        from backend.messaging.mysql_cdc import upsert_document_record
        cdc_persisted = await upsert_document_record(
            document_id=document_id, source=file.filename, file_path=str(saved_path)
        )
        if not cdc_persisted:
            from backend.messaging.kafka_producer import publish_document_change
            kafka_event_published = await publish_document_change(
                document_id=document_id,
                operation="INSERT",
                source=file.filename,
                file_path=str(saved_path),
            )
        else:
            kafka_event_published = True

        logger.info("document_uploaded_sync", filename=file.filename, result=result)
        return {"status": "ok", "cdc_persisted": cdc_persisted, "kafka_event_published": kafka_event_published, **result}

    except AppError:
        raise
    except Exception as exc:
        logger.error("document_upload_failed", filename=file.filename, error=str(exc))
        raise AppError(ErrorCode.DOC_UPLOAD_FAILED, f"文件入库失败：{exc}", 500)
    finally:
        if redis:
            from backend.services.cache_service import release_lock
            await release_lock(redis, f"upload:{file.filename}")


@router.post("/api/v1/documents/upload/async")
async def upload_document_async(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db_optional),
):
    """
    异步上传（推荐大 PDF，立即返回 task_id）。
    前端通过 GET /api/v1/tasks/{task_id} 轮询状态。
    """
    from backend.retriever import knowledge_base

    if not file.filename.lower().endswith(".pdf"):
        raise AppError(ErrorCode.DOC_INVALID_FORMAT, "仅支持 PDF 文件", 400)

    # 先保存文件到磁盘
    saved_path = knowledge_base.save_upload(file)

    # 创建数据库记录（pending 状态）
    if db is not None:
        from backend.models.document_record import DocumentRecord
        record = DocumentRecord(
            filename=file.filename,
            status="pending",
            uploaded_by=current_user.id if current_user else None,
        )
        db.add(record)
        await db.flush()

    # 派发 Celery 任务
    try:
        from backend.tasks.document_tasks import process_pdf_task
        task = process_pdf_task.delay(
            saved_path,
            file.filename,
            current_user.id if current_user else None,
        )
        logger.info("document_upload_queued", filename=file.filename, task_id=task.id)
        return {
            "status": "queued",
            "task_id": task.id,
            "filename": file.filename,
            "message": f"文件已加入处理队列，请通过 GET /api/v1/tasks/{task.id} 查询进度",
        }
    except Exception as exc:
        logger.error("celery_dispatch_failed", error=str(exc))
        # Celery 不可用时降级为同步处理
        from backend.retriever import knowledge_base
        result = knowledge_base.add_pdf(saved_path, file.filename)
        return {"status": "ok", "note": "Celery 不可用，已同步处理", **result}


@router.delete("/documents")
async def clear_documents(_admin=Depends(require_admin)):
    """清空全部知识库（仅 Admin）。"""
    from backend.retriever import knowledge_base
    knowledge_base.clear()
    logger.warning("knowledge_base_cleared")
    return {"status": "ok", **knowledge_base.stats()}


@router.delete("/documents/source")
async def delete_document(
    source: str = Query(..., min_length=1),
    current_user=Depends(get_current_user),
):
    from backend.retriever import knowledge_base
    result = knowledge_base.delete_source(source)
    from backend.messaging.mysql_cdc import delete_document_record
    cdc_persisted = await delete_document_record(source=source)
    if not cdc_persisted:
        from backend.messaging.kafka_producer import publish_document_change
        kafka_event_published = await publish_document_change(
            document_id=source,
            operation="DELETE",
            source=source,
        )
    else:
        kafka_event_published = True
    status = "ok" if result["chunks_removed"] or result["uploads_deleted"] else "not_found"
    return {"status": status, "cdc_persisted": cdc_persisted, "kafka_event_published": kafka_event_published, **result}


@router.post("/documents/reindex")
async def reindex_documents(current_user=Depends(get_current_user)):
    from backend.retriever import knowledge_base
    return {"status": "ok", **knowledge_base.rebuild_from_uploads()}
