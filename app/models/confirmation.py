from __future__ import annotations

import uuid
from typing import List, Optional

from datetime import date

from sqlalchemy import Date, BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base


class Confirmation(Base, AuditMixin):
    __tablename__ = "crossdocking_confirmations"

    confirmation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(50), nullable=False)
    confirmation_number: Mapped[str] = mapped_column(String(100), nullable=False)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    confirmation_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="processing")

    # Normalized FK
    deliver_to_store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.store_id"), nullable=True
    )

    # Relationships
    deliver_to_store: Mapped[Optional["Store"]] = relationship(foreign_keys=[deliver_to_store_id])
    orders: Mapped[List["Order"]] = relationship(
        back_populates="confirmation"
    )

    __table_args__ = (
        Index("idx_confirmation_company_number", "company_id", "confirmation_number", unique=True),
        Index("idx_confirmation_company_id", "company_id"),
    )
