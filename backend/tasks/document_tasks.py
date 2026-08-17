"""
PDF 异步入库任务
- process_pdf_task: 异步处理 PDF 入库，支持失败自动重试（最多3次）
- update_task_status: 任务状态写回数据库（可选，无 DB 时跳过）
- 配合 /documents/upload/async 接口使用，接口立即返回 task_id
"""
from __future__ import annotations

import os
import time
from celery import Task
from celery.utils.log import get_task_logger

from backend.tasks.celery_app import celery_app

logger = get_task_logger(__name__)


class PdfTask(Task):
    """自定义 Task 基类，统一异常日志。"""
    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            f"[TASK FAILED] {task_id} | args={args} | error={exc}",
            exc_info=einfo,
        )

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning(f"[TASK RETRY] {task_id} | error={exc}")

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"[TASK SUCCESS] {task_id} | result={retval}")


@celery_app.task(
    bind=True,
    base=PdfTask,
    name="backend.tasks.document_tasks.process_pdf_task",
    max_retries=3,
    default_retry_delay=10,  # 10秒后重试
    soft_time_limit=300,     # 5分钟软超时
    time_limit=360,          # 6分钟强超时
)
def process_pdf_task(self, file_path: str, filename: str, uploaded_by: int | None = None) -> dict:
    """
    异步 PDF 入库任务。
    Args:
        file_path: 已保存的 PDF 文件路径
        filename:  原始文件名
        uploaded_by: 上传用户 ID（可选）
    Returns:
        dict: {pages, chunks_added, filename}
    """
    logger.info(f"[PDF TASK] Starting | file={filename} | task_id={self.request.id}")
    start = time.perf_counter()

    # 更新任务状态为 processing
    _update_db_status(self.request.id, filename, "processing", uploaded_by=uploaded_by)

    try:
        from backend.retriever import knowledge_base
        result = knowledge_base.add_pdf(file_path, filename)

        from backend.messaging.mysql_cdc import upsert_document_record_sync
        cdc_persisted = upsert_document_record_sync(
            document_id=self.request.id, source=filename, file_path=str(file_path)
        )
        if not cdc_persisted:
            from backend.messaging.kafka_producer import publish_document_change_sync
            publish_document_change_sync(
                document_id=self.request.id,
                operation="INSERT",
                source=filename,
                file_path=str(file_path),
            )

        duration = round(time.perf_counter() - start, 2)
        logger.info(f"[PDF TASK] Done | file={filename} | duration={duration}s | result={result}")

        _update_db_status(
            self.request.id, filename, "success",
            pages=result.get("pages", 0),
            chunks=result.get("chunks_added", 0),
            uploaded_by=uploaded_by,
        )
        return {**result, "duration_seconds": duration}

    except Exception as exc:
        logger.error(f"[PDF TASK] Error | file={filename} | error={exc}")
        _update_db_status(self.request.id, filename, "failed", error_message=str(exc))

        # 自动重试（网络/临时错误）
        raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1))


def _update_db_status(
    task_id: str,
    filename: str,
    status: str,
    pages: int = 0,
    chunks: int = 0,
    uploaded_by: int | None = None,
    error_message: str | None = None,
) -> None:
    """同步方式将任务状态写入数据库（Celery worker 不支持 asyncio）。"""
    try:
        import asyncio
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from backend.models.document_record import DocumentRecord

        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return

        # 将 asyncpg URL 转换为同步 psycopg2 格式
        sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(sync_url, pool_pre_ping=True)

        with Session(engine) as session:
            # 查找或创建记录
            record = session.query(DocumentRecord).filter_by(filename=filename).first()
            if record is None:
                record = DocumentRecord(filename=filename)
                session.add(record)

            record.status = status
            record.pages = pages
            record.chunks = chunks
            record.uploaded_by = uploaded_by
            record.error_message = error_message
            session.commit()

        engine.dispose()
    except Exception as e:
        logger.warning(f"[DB] Failed to update task status: {e}")
