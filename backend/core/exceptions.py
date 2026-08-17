"""
统一异常处理体系
- AppError: 业务异常基类，携带错误码
- ErrorCode: 枚举所有业务错误码
- setup_exception_handlers: 注册全局 FastAPI 异常处理器
- 统一响应格式: {code, message, request_id, data}
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from structlog.contextvars import get_contextvars

logger = structlog.get_logger(__name__)


# ── 业务异常基类 ──────────────────────────────────────────
class AppError(Exception):
    """所有业务异常继承此类，携带标准错误码。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


# ── 错误码表 ──────────────────────────────────────────────
class ErrorCode:
    # 认证 & 权限
    AUTH_INVALID_TOKEN  = "AUTH_INVALID_TOKEN"
    AUTH_EXPIRED_TOKEN  = "AUTH_EXPIRED_TOKEN"
    AUTH_UNAUTHORIZED   = "AUTH_UNAUTHORIZED"
    AUTH_FORBIDDEN      = "AUTH_FORBIDDEN"
    AUTH_USER_EXISTS    = "AUTH_USER_EXISTS"
    AUTH_INVALID_CREDS  = "AUTH_INVALID_CREDENTIALS"

    # 文档
    DOC_NOT_FOUND       = "DOC_NOT_FOUND"
    DOC_UPLOAD_FAILED   = "DOC_UPLOAD_FAILED"
    DOC_INVALID_FORMAT  = "DOC_INVALID_FORMAT"

    # LLM / Chat
    LLM_TIMEOUT         = "LLM_TIMEOUT"
    LLM_QUOTA_EXCEEDED  = "LLM_QUOTA_EXCEEDED"
    LLM_ERROR           = "LLM_ERROR"
    RATE_LIMITED        = "RATE_LIMITED"

    # 会话
    SESSION_NOT_FOUND   = "SESSION_NOT_FOUND"
    SESSION_FORBIDDEN   = "SESSION_FORBIDDEN"
    TASK_NOT_FOUND      = "TASK_NOT_FOUND"

    # 通用
    VALIDATION_ERROR    = "VALIDATION_ERROR"
    NOT_FOUND           = "NOT_FOUND"
    INTERNAL_ERROR      = "INTERNAL_ERROR"


def _make_error_body(code: str, message: str, data=None) -> dict:
    ctx = get_contextvars()
    return {
        "code": code,
        "message": message,
        "request_id": ctx.get("request_id", ""),
        "data": data,
    }


def setup_exception_handlers(app: FastAPI) -> None:
    """在 app 创建后调用，注册全局异常处理器。"""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error",
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            path=str(request.url.path),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_make_error_body(exc.code, exc.message, exc.details or None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning("validation_error", errors=exc.errors(), path=str(request.url.path))
        return JSONResponse(
            status_code=422,
            content=_make_error_body(
                ErrorCode.VALIDATION_ERROR,
                "请求参数校验失败",
                exc.errors(),
            ),
        )

    @app.exception_handler(Exception)
    async def _generic_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            exc_type=type(exc).__name__,
            exc_info=exc,
            path=str(request.url.path),
        )
        return JSONResponse(
            status_code=500,
            content=_make_error_body(ErrorCode.INTERNAL_ERROR, "服务器内部错误，请稍后重试"),
        )
