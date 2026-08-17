"""文档记录表 ORM 模型（记录每个上传 PDF 的元数据和处理状态）"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class DocumentRecord(Base, TimestampMixin):
    __tablename__ = "document_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # pending / processing / success / failed
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    def __repr__(self) -> str:
        return f"<DocumentRecord id={self.id} filename={self.filename!r} status={self.status}>"
