"""Schemas for long-term user memories."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=2, max_length=1000)
    category: str = Field("preference", max_length=50)
    memory_key: str | None = Field(None, max_length=120)
    status: str = Field("active", max_length=30)


class MemoryUpdate(BaseModel):
    content: str | None = Field(None, min_length=2, max_length=1000)
    category: str | None = Field(None, max_length=50)
    memory_key: str | None = Field(None, max_length=120)
    status: str | None = Field(None, max_length=30)
    is_active: bool | None = None


class MemoryResponse(BaseModel):
    id: int
    memory_key: str
    category: str
    content: str
    status: str
    source: str
    source_session_id: int | None
    source_message_id: int | None
    confidence: float
    importance: float
    use_count: int
    is_sensitive: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
