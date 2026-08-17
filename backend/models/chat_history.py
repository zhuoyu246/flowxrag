"""问答历史表 ORM 模型"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class ChatHistory(Base, TimestampMixin):
    __tablename__ = "chat_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    route: Mapped[str | None] = mapped_column(String(50), nullable=True)       # local/web/model
    sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    agent_trace: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    web_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatHistory id={self.id} session_id={self.session_id}>"
