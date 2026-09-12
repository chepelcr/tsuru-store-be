from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StatusMixin, TimestampMixin


class Terminal(Base, TimestampMixin, StatusMixin):
    __tablename__ = "terminals"

    terminal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[str] = mapped_column(String(255), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.branch_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[int] = mapped_column(Integer, nullable=False)
    device_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("idx_terminals_branch", "branch_id"),
        Index("idx_terminals_org", "organization_id"),
        Index("idx_terminals_status", "organization_id", "status"),
        # Hacienda numbers terminals WITHIN a branch — its consecutive is
        # branch(3) + terminal(5) — so the pair is what must be unique.
        # An organization-wide constraint here rejected branch 14/terminal 1
        # for an org that already had branch 1/terminal 1, which is a legal
        # upstream configuration (TSR-254).
        UniqueConstraint(
            "organization_id", "branch_id", "code",
            name="uq_terminals_org_branch_code",
        ),
        Index("idx_terminals_device_id", "device_id", unique=True),
    )
