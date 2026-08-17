"""MySQL document metadata projection used as the Canal CDC source.

The original PostgreSQL records remain responsible for user-facing history.
This small MySQL table is an indexing outbox: its row-level binlog changes are
captured by Canal and delivered to the Kafka document-change topic.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


def enabled() -> bool:
    return settings.mysql_cdc_enabled and bool(settings.mysql_cdc_database_url)


async def upsert_document_record(
    *, document_id: str, source: str, file_path: str
) -> bool:
    """Persist a CDC row. Canal emits the corresponding INSERT/UPDATE event."""
    if not enabled():
        return False
    engine = create_async_engine(settings.mysql_cdc_database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO document_records (id, source, file_path, status)
                    VALUES (:id, :source, :file_path, 'ACTIVE')
                    ON DUPLICATE KEY UPDATE
                      source = VALUES(source),
                      file_path = VALUES(file_path),
                      status = 'ACTIVE',
                      updated_at = CURRENT_TIMESTAMP(3)
                    """
                ),
                {"id": document_id, "source": source, "file_path": file_path},
            )
        logger.info("mysql_cdc_document_upserted", document_id=document_id, source=source)
        return True
    except Exception as exc:
        logger.error("mysql_cdc_document_upsert_failed", document_id=document_id, error=str(exc))
        return False
    finally:
        await engine.dispose()


async def delete_document_record(*, source: str) -> bool:
    """Delete CDC rows for a source so Canal publishes DELETE events."""
    if not enabled():
        return False
    engine = create_async_engine(settings.mysql_cdc_database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM document_records WHERE source = :source"),
                {"source": source},
            )
        logger.info("mysql_cdc_document_deleted", source=source)
        return True
    except Exception as exc:
        logger.error("mysql_cdc_document_delete_failed", source=source, error=str(exc))
        return False
    finally:
        await engine.dispose()


def upsert_document_record_sync(**kwargs) -> bool:
    return asyncio.run(upsert_document_record(**kwargs))
