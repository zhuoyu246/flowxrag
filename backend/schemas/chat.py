"""问答相关 Pydantic 模型（向后兼容原有接口格式）"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: int | None = None    # 可选，绑定会话历史


class ChatResponse(BaseModel):
    answer: str
    agent_trace: List[str]
    trigger_web_fallback: bool
    sources: List[dict] = []
    reasoning_summary: List[str] = []
    cached: bool = False              # 是否命中 Redis 缓存
    duration_ms: int = 0              # 后端处理耗时（毫秒）


class EmbeddingRequest(BaseModel):
    input: str | List[str]
    model: str | None = None


class RerankRequest(BaseModel):
    query: str
    documents: List[str]
    top_n: int = 5
    model: str | None = None
