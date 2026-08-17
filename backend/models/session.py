"""会话表 ORM 模型（一个用户可有多个会话）"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), default="新会话", nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped["User | None"] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatHistory"]] = relationship(
        back_populates="session",
        lazy="selectin",
        order_by="ChatHistory.created_at",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} user_id={self.user_id}>"
