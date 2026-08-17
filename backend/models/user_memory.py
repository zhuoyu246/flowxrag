"""Long-term user memory records."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class UserMemory(Base, TimestampMixin):
    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scope_key: Mapped[str] = mapped_column(String(100), default="anonymous", nullable=False, index=True)
    memory_key: Mapped[str] = mapped_column(String(120), default="general", nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), default="preference", nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), default="explicit_user_request", nullable=False)
    source_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    user: Mapped["User | None"] = relationship(back_populates="memories")

    def __repr__(self) -> str:
        return f"<UserMemory id={self.id} user_id={self.user_id} category={self.category}>"
