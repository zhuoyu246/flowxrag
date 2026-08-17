"""gRPC façade for the existing Python CRAG application.

The implementation deliberately delegates to ``backend``: FAISS/BM25/RRF,
LangGraph, Redis cache and the existing persistence code stay authoritative.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from prometheus_client import Counter, Histogram, start_http_server

ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = Path(__file__).resolve().parent
# When this file is executed as ``python rag-service/server.py``, Python adds
# ``rag-service`` to sys.path. Its ``grpc/`` folder would then shadow grpcio.
# Remove that script directory before exposing the generated module directory.
try:
    sys.path.remove(str(SERVICE_DIR))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVICE_DIR / "grpc"))

import grpc
import rag_pb2  # type: ignore  # generated at build time
import rag_pb2_grpc  # type: ignore  # generated at build time

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.core.telemetry import instrument_grpc_server

logger = get_logger(__name__)
GRPC_REQUESTS = Counter("grpc_requests_total", "RAG gRPC requests", ["method", "status"])
GRPC_DURATION = Histogram("grpc_request_duration_seconds", "RAG gRPC request duration", ["method"])


def _source_message(source: dict) -> rag_pb2.Source:
    return rag_pb2.Source(
        source=str(source.get("source", "")),
        title=str(source.get("title", "")),
        url=str(source.get("url", "")),
        type=str(source.get("type", "local")),
        page=int(source.get("page") or 0),
        score=float(source.get("score") or 0.0),
    )


class RagServicer(rag_pb2_grpc.RagServiceServicer):
    """Thin, observable gRPC adapter around the pre-existing RAG workflow."""

    async def Chat(self, request, context):  # noqa: N802 - protobuf API
        with GRPC_DURATION.labels("Chat").time():
            try:
                from backend.services.chat_service import run_chat

                result = await run_chat(request.question, session_id=request.session_id or None)
                GRPC_REQUESTS.labels("Chat", "ok").inc()
                return rag_pb2.ChatResponse(
                    answer=result.get("answer", ""),
                    agent_trace=result.get("agent_trace", []),
                    trigger_web_fallback=bool(result.get("trigger_web_fallback", False)),
                    sources=[_source_message(item) for item in result.get("sources", [])],
                    reasoning_summary=result.get("reasoning_summary", []),
                    cached=bool(result.get("cached", False)),
                    duration_ms=int(result.get("duration_ms", 0)),
                )
            except Exception as exc:
                GRPC_REQUESTS.labels("Chat", "error").inc()
                logger.exception("grpc_chat_failed", error=str(exc))
                await context.abort(grpc.StatusCode.INTERNAL, "RAG chat failed")

    async def Search(self, request, context):  # noqa: N802 - protobuf API
        with GRPC_DURATION.labels("Search").time():
            try:
                from backend.retriever import knowledge_base

                top_k = min(max(int(request.top_k or 5), 1), 20)
                results = await asyncio.to_thread(knowledge_base.search, request.query, top_k)
                GRPC_REQUESTS.labels("Search", "ok").inc()
                return rag_pb2.SearchResponse(
                    hits=[
                        rag_pb2.SearchHit(
                            content=item.content,
                            source=item.source,
                            page=item.page,
                            score=item.score,
                        )
                        for item in results
                    ]
                )
            except Exception as exc:
                GRPC_REQUESTS.labels("Search", "error").inc()
                logger.exception("grpc_search_failed", error=str(exc))
                await context.abort(grpc.StatusCode.INTERNAL, "RAG search failed")

    async def IndexDocument(self, request, context):  # noqa: N802 - protobuf API
        """Apply a Kafka document-change event idempotently against FAISS."""
        with GRPC_DURATION.labels("IndexDocument").time():
            try:
                from backend.retriever import knowledge_base

                operation = request.operation.upper()
                if operation == "DELETE":
                    result = await asyncio.to_thread(knowledge_base.delete_source, request.source)
                    chunks = int(result.get("chunks", 0))
                elif operation in {"INSERT", "UPDATE"}:
                    path = Path(request.file_path)
                    if not path.is_file():
                        await context.abort(grpc.StatusCode.NOT_FOUND, "document file is unavailable to RAG service")
                    result = await asyncio.to_thread(knowledge_base.upsert_pdf, path, request.source)
                    chunks = int(result.get("total_chunks", 0))
                else:
                    await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "operation must be INSERT, UPDATE or DELETE")
                GRPC_REQUESTS.labels("IndexDocument", "ok").inc()
                return rag_pb2.IndexDocumentResponse(success=True, message="indexed", chunks=chunks)
            except Exception as exc:
                GRPC_REQUESTS.labels("IndexDocument", "error").inc()
                logger.exception("grpc_index_failed", error=str(exc), document_id=request.document_id)
                await context.abort(grpc.StatusCode.INTERNAL, "document indexing failed")

    async def Health(self, request, context):  # noqa: N802 - protobuf API
        from backend.retriever import knowledge_base

        stats = knowledge_base.stats()
        return rag_pb2.HealthResponse(status="ok", vector_store="faiss", chunks=int(stats["chunks"]))


async def serve() -> None:
    if settings.vector_store != "faiss":
        raise RuntimeError("This deployment only supports VECTOR_STORE=faiss")
    instrument_grpc_server()
    server = grpc.aio.server(options=[("grpc.max_receive_message_length", 32 * 1024 * 1024)])
    rag_pb2_grpc.add_RagServiceServicer_to_server(RagServicer(), server)
    address = os.getenv("RAG_GRPC_ADDR", "0.0.0.0:50051")
    server.add_insecure_port(address)
    metrics_port = int(os.getenv("RAG_METRICS_PORT", "9090"))
    start_http_server(metrics_port)
    await server.start()
    logger.info("rag_grpc_started", address=address, metrics_port=metrics_port, vector_store="faiss")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # Windows local development
            signal.signal(sig, lambda *_: stop_event.set())
    await stop_event.wait()
    await server.stop(grace=20)
    logger.info("rag_grpc_stopped")


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(serve())
