from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Consecutive(Base, TimestampMixin):
    __tablename__ = "consecutives"

    consecutive_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[str] = mapped_column(String(255), nullable=False)
    terminal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("terminals.terminal_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("document_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    current_number: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)

    # View-only, never loaded: they exist so the search enum can name
    # `terminal.*` / `document_type.*` join fields (SearchUtils resolves the
    # target column through the relationship). The list query joins the tables
    # itself — see ConsecutiveRepository.find_all_paginated.
    terminal = relationship("Terminal", viewonly=True, lazy="noload")
    document_type = relationship("DocumentType", viewonly=True, lazy="noload")

    __table_args__ = (
        UniqueConstraint(
            "terminal_id", "document_type_id", name="uq_consecutives_terminal_doc_type"
        ),
        Index("idx_consecutives_org", "organization_id"),
        Index("idx_consecutives_terminal", "terminal_id"),
    )
