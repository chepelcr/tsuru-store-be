from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ConsecutiveAdjustment(Base):
    """One manual change to a consecutive counter — append-only.

    A consecutive is the fiscal numbering Hacienda keys every document on, so a
    hand edit is the one write to it that is not a sale. Each one is recorded
    with who made it, why, and the value it replaced, so a rejected clave can be
    traced back to the edit that caused it. Rows are never updated or deleted.

    `previous_number` is NULL when the edit created the counter (a document type
    the terminal had never issued).
    """

    __tablename__ = "consecutive_adjustments"

    adjustment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[str] = mapped_column(String(255), nullable=False)
    consecutive_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consecutives.consecutive_id", ondelete="CASCADE"),
        nullable=False,
    )
    terminal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_number: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    new_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    changed_on: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )

    __table_args__ = (
        Index("idx_consecutive_adjustments_consecutive", "consecutive_id", "changed_on"),
        Index("idx_consecutive_adjustments_org", "organization_id"),
    )
