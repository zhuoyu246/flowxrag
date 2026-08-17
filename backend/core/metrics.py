"""
Prometheus 自定义业务指标
- HTTP 指标由 prometheus-fastapi-instrumentator 自动采集
- 此模块补充 CRAG 业务维度指标：LLM耗时、缓存命中、路由分布
- 调用方式：from backend.core.metrics import METRICS; METRICS.llm_calls.inc()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from prometheus_client import Counter, Histogram, Gauge


@dataclass
class CRAGMetrics:
    # ── LLM 调用 ──────────────────────────────────────────
    llm_calls_total: Counter = field(default_factory=lambda: Counter(
        "crag_llm_calls_total",
        "LLM 调用总次数",
        ["model", "status"],          # status: success / error / timeout
    ))
    llm_duration_seconds: Histogram = field(default_factory=lambda: Histogram(
        "crag_llm_duration_seconds",
        "LLM 调用耗时（秒）",
        ["model"],
        buckets=[0.5, 1, 2, 5, 10, 20, 30, 60],
    ))

    # ── Redis 缓存 ────────────────────────────────────────
    cache_hits_total: Counter = field(default_factory=lambda: Counter(
        "crag_cache_hits_total",
        "Redis 问答缓存命中次数",
    ))
    cache_misses_total: Counter = field(default_factory=lambda: Counter(
        "crag_cache_misses_total",
        "Redis 问答缓存未命中次数",
    ))

    # ── 路由分布 ──────────────────────────────────────────
    route_total: Counter = field(default_factory=lambda: Counter(
        "crag_route_total",
        "CRAG 路由选择次数",
        ["route"],                     # route: local / web / model / auto
    ))

    # ── 文档知识库 ────────────────────────────────────────
    kb_chunks_total: Gauge = field(default_factory=lambda: Gauge(
        "crag_kb_chunks_total",
        "知识库当前 chunk 数量",
    ))
    kb_documents_total: Gauge = field(default_factory=lambda: Gauge(
        "crag_kb_documents_total",
        "知识库当前文档数量",
    ))

    # ── Celery 任务 ───────────────────────────────────────
    celery_tasks_total: Counter = field(default_factory=lambda: Counter(
        "crag_celery_tasks_total",
        "Celery 任务执行总次数",
        ["task_name", "status"],       # status: success / failure / retry
    ))
    celery_task_duration_seconds: Histogram = field(default_factory=lambda: Histogram(
        "crag_celery_task_duration_seconds",
        "Celery 任务耗时（秒）",
        ["task_name"],
        buckets=[1, 5, 10, 30, 60, 120, 300],
    ))

    # ── 问答总量 ──────────────────────────────────────────
    chat_requests_total: Counter = field(default_factory=lambda: Counter(
        "crag_chat_requests_total",
        "问答请求总次数",
        ["route", "cached"],           # cached: true / false
    ))
    chat_duration_seconds: Histogram = field(default_factory=lambda: Histogram(
        "crag_chat_duration_seconds",
        "问答端到端耗时（秒）",
        buckets=[0.5, 1, 2, 5, 10, 20, 30, 60],
    ))


# 全局单例
    retrieval_total: Counter = field(default_factory=lambda: Counter(
        "rag_retrieval_total", "Hybrid retrieval requests", ["status"]
    ))
    retrieval_duration_seconds: Histogram = field(default_factory=lambda: Histogram(
        "rag_retrieval_duration_seconds", "Hybrid retrieval duration", ["stage"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
    ))
    document_index_duration_seconds: Histogram = field(default_factory=lambda: Histogram(
        "rag_document_index_duration_seconds", "FAISS document indexing duration"
    ))
    llm_requests_total: Counter = field(default_factory=lambda: Counter(
        "rag_llm_requests_total", "LLM requests", ["model", "status"]
    ))
    llm_errors_total: Counter = field(default_factory=lambda: Counter(
        "rag_llm_errors_total", "LLM request errors", ["model"]
    ))
    rag_llm_duration_seconds: Histogram = field(default_factory=lambda: Histogram(
        "rag_llm_duration_seconds", "LLM request duration", ["model"]
    ))
    rag_documents_total: Gauge = field(default_factory=lambda: Gauge(
        "rag_documents_total", "Indexed FAISS source documents"
    ))


METRICS = CRAGMetrics()


def setup_prometheus(app) -> None:
    """在 FastAPI app 上挂载 Prometheus 指标采集器。"""
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            excluded_handlers=["/metrics", "/health", "/docs", "/redoc", "/openapi.json"],
        ).instrument(app).expose(app, endpoint="/metrics")
    except ImportError:
        import structlog
        structlog.get_logger(__name__).warning(
            "prometheus_not_installed",
            hint="pip install prometheus-fastapi-instrumentator",
        )
