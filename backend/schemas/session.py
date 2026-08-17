"""会话相关 Pydantic 模型"""
from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel


class SessionCreate(BaseModel):
    title: str = "新会话"


class SessionResponse(BaseModel):
    id: int
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatHistoryItem(BaseModel):
    id: int
    question: str
    answer: str
    route: str | None
    sources: List[dict]
    duration_ms: int
    web_fallback: bool
    cached: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionDetail(SessionResponse):
    messages: List[ChatHistoryItem] = []
