from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, Index, Integer, String, false, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StatusMixin, TimestampMixin


class BranchType(Base, TimestampMixin, StatusMixin):
    """Per-organization catalog of branch types.

    Replaces the hardcoded `stand`/`restaurant` enum that used to live in a CHECK
    constraint on `branches.type`. `code` is the stable key stored on `branches.type`,
    so it is assigned at creation and never edited afterwards — only the presentation
    fields (name/icon/color/sort_order) are mutable.
    """

    __tablename__ = "branch_types"

    branch_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Presentation hints consumed by the POS: an Icon name from the design-system
    # icon set and a CSS-var color token name (e.g. "primary", "info").
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    created_by: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        Index("idx_branch_types_org", "organization_id"),
        Index("idx_branch_types_status", "organization_id", "status"),
        Index("idx_branch_types_org_code", "organization_id", "code", unique=True),
        Index("uq_branch_types_default", "organization_id", unique=True,
              postgresql_where=text("is_default AND deleted_on IS NULL"),
              sqlite_where=text("is_default AND deleted_on IS NULL")),
    )
