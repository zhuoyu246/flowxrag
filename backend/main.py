"""
CRAG Expert System — FastAPI 应用入口 v2.0
重构要点：
  - 分层架构：main.py 只负责 app 创建、中间件、路由注册、生命周期
  - 所有业务逻辑下沉到 services/
  - 结构化日志、统一异常处理、request_id 中间件
  - Prometheus 指标采集（/metrics 端点）
  - Celery 任务查询路由（/api/v1/tasks/*）
  - 向后兼容原有所有 API 路径
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.core.exceptions import setup_exception_handlers
from backend.core.logging import setup_logging
from backend.core.telemetry import instrument_fastapi

# ── 初始化日志（最先执行）────────────────────────────────
setup_logging(log_level=settings.log_level, is_production=settings.is_production)
logger = structlog.get_logger(__name__)

# ── LangSmith 配置（保留原有逻辑）───────────────────────
import os
from dotenv import load_dotenv

load_dotenv(override=True)


def _configure_langsmith() -> dict:
    def _clean(name: str) -> str:
        return os.getenv(name, "").strip().strip('"').strip("'")

    def _valid(v: str) -> bool:
        return bool(v) and "your-" not in v.lower() and "placeholder" not in v.lower()

    key = _clean("LANGCHAIN_API_KEY") or _clean("LANGSMITH_API_KEY")
    if _valid(key):
        os.environ["LANGCHAIN_API_KEY"] = key
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_TRACING"] = "true"
        return {"enabled": True, "project": os.getenv("LANGCHAIN_PROJECT")}
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    return {"enabled": False}


LANGSMITH_STATUS = _configure_langsmith()


# ── 应用生命周期 ──────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_starting", env=settings.app_env, version=settings.app_version)

    # 初始化数据库
    from backend.db.database import init_db, close_db
    await init_db()

    # 检查 Redis 连通性
    from backend.db.redis_client import ping_redis
    redis_ok = await ping_redis()
    logger.info("redis_status", connected=redis_ok, url=settings.redis_url or "not configured")

    logger.info("app_started",
        db_enabled=settings.db_enabled,
        redis_enabled=settings.redis_enabled,
        require_auth=settings.require_auth,
        cache_enabled=settings.cache_enabled,
        langsmith=LANGSMITH_STATUS,
    )

    yield  # ← 应用运行中

    # 关闭清理
    await close_db()
    from backend.db.redis_client import close_redis
    await close_redis()
    logger.info("app_stopped")


# ── 创建 FastAPI 应用 ─────────────────────────────────────
app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description="企业级 CRAG 知识检索问答系统 — 含认证、缓存、历史记录、监控",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
instrument_fastapi(app)

# ── 异常处理器 ────────────────────────────────────────────
setup_exception_handlers(app)

# ── 中间件 ────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """为每个请求注入唯一 request_id，贯穿整个调用链。"""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ── 注册路由 ──────────────────────────────────────────────
from backend.api.v1.health import router as health_router
from backend.api.v1.chat import router as chat_router
from backend.api.v1.documents import router as documents_router
from backend.api.v1.auth import router as auth_router
from backend.api.v1.sessions import router as sessions_router
from backend.api.v1.tasks import router as tasks_router
from backend.api.v1.memories import router as memories_router

# 保持原有路径（向后兼容 Streamlit 前端）
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(documents_router)

# 新增路由（v1 命名空间）
app.include_router(auth_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(memories_router, prefix="/api/v1")

# ── Prometheus 指标采集（/metrics 端点）────────────────
from backend.core.metrics import setup_prometheus
setup_prometheus(app)
