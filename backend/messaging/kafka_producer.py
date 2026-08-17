"""Kafka document-change producer with W3C trace header propagation."""
from __future__ import annotations

import asyncio
import json
import time

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def publish_document_change(
    document_id: str,
    operation: str,
    source: str,
    file_path: str = "",
) -> bool:
    """Publish an at-least-once document event when Kafka is configured.

    Indexing has already completed in the legacy endpoint, so a Kafka outage is
    reported in logs but never turns a completed upload into an API failure.
    The consumer's upsert operation makes the event safe to replay.
    """
    if not settings.kafka_bootstrap_servers:
        return False
    try:
        from aiokafka import AIOKafkaProducer
        from opentelemetry.propagate import inject

        carrier: dict[str, str] = {}
        inject(carrier)
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
            acks="all",
            request_timeout_ms=10_000,
        )
        await producer.start()
        try:
            payload = {
                "document_id": str(document_id),
                "operation": operation.upper(),
                "timestamp": int(time.time()),
                "source": source,
                "file_path": file_path,
            }
            headers = [(key, value.encode("utf-8")) for key, value in carrier.items()]
            await producer.send_and_wait(
                settings.kafka_document_topic,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                key=str(document_id).encode("utf-8"),
                headers=headers,
            )
            logger.info("kafka_document_change_published", document_id=document_id, operation=operation)
            return True
        finally:
            await producer.stop()
    except Exception as exc:
        logger.warning("kafka_document_change_publish_failed", error=str(exc), document_id=document_id)
        return False


def publish_document_change_sync(**kwargs) -> bool:
    """Celery-friendly adapter for the synchronous worker process."""
    return asyncio.run(publish_document_change(**kwargs))
