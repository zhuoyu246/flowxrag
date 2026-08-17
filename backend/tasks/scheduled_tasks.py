"""
Celery Beat 定时任务
- rebuild_index_task:        每天凌晨重建向量索引
- cleanup_old_tasks_task:    清理 N 天前的过期文档记录
- report_health_metrics:     每 5 分钟上报系统健康指标
"""
from __future__ import annotations

import os
import time
from celery.utils.log import get_task_logger

from backend.tasks.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(name="backend.tasks.scheduled_tasks.rebuild_index_task")
def rebuild_index_task() -> dict:
    """每日凌晨重建 FAISS + BM25 索引，确保索引与磁盘 PDF 一致。"""
    logger.info("[SCHEDULED] Starting daily index rebuild")
    start = time.perf_counter()
    try:
        from backend.retriever import knowledge_base
        result = knowledge_base.rebuild_from_uploads()
        duration = round(time.perf_counter() - start, 2)
        logger.info(f"[SCHEDULED] Index rebuild done | duration={duration}s | result={result}")
        return {**result, "duration_seconds": duration}
    except Exception as exc:
        logger.error(f"[SCHEDULED] Index rebuild failed: {exc}")
        return {"error": str(exc)}


@celery_app.task(name="backend.tasks.scheduled_tasks.cleanup_old_tasks_task")
def cleanup_old_tasks_task(days: int = 7) -> dict:
    """清理 N 天前的失败任务记录，防止数据库膨胀。"""
    logger.info(f"[SCHEDULED] Cleaning up task records older than {days} days")
    try:
        import os
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import create_engine, delete
        from sqlalchemy.orm import Session
        from backend.models.document_record import DocumentRecord

        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            logger.warning("[SCHEDULED] DATABASE_URL not configured, skip cleanup")
            return {"skipped": True}

        sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(sync_url, pool_pre_ping=True)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with Session(engine) as session:
            result = session.execute(
                delete(DocumentRecord).where(
                    DocumentRecord.status == "failed",
                    DocumentRecord.created_at < cutoff,
                )
            )
            deleted = result.rowcount
            session.commit()

        engine.dispose()
        logger.info(f"[SCHEDULED] Cleanup done | deleted={deleted} records")
        return {"deleted_records": deleted, "cutoff_days": days}
    except Exception as exc:
        logger.error(f"[SCHEDULED] Cleanup failed: {exc}")
        return {"error": str(exc)}


@celery_app.task(name="backend.tasks.scheduled_tasks.report_health_metrics")
def report_health_metrics() -> dict:
    """每 5 分钟采集健康指标并写入日志（可对接 Prometheus Pushgateway）。"""
    try:
        from backend.retriever import knowledge_base
        stats = knowledge_base.stats()
        logger.info(
            "[METRICS] knowledge_base_health",
            extra={
                "total_chunks": stats.get("total_chunks", 0),
                "total_documents": stats.get("total_documents", 0),
            },
        )
        return stats
    except Exception as exc:
        logger.warning(f"[METRICS] Report failed: {exc}")
        return {"error": str(exc)}
