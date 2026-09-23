from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, StatusMixin, TimestampMixin


class Branch(Base, TimestampMixin, StatusMixin):
    __tablename__ = "branches"

    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Location structure (matching clients)
    state_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    county_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    district_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    neighborhood_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Contact — structured like a client phone: the ISO numeric country (188,
    # a key into data-be's countries catalog) and the digits. The dialing code
    # (+506) is read from the catalog, never stored.
    phone_country_code: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    phone_country: Mapped[Optional["Country"]] = relationship(  # noqa: F821
        "Country",
        primaryjoin="foreign(Branch.phone_country_code) == Country.iso_code",
        viewonly=True,
        uselist=False,
        # Joined: branches are mapped after their repository session closes.
        lazy="joined",
    )
    
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        Index("idx_branches_org", "organization_id"),
        Index("idx_branches_status", "organization_id", "status"),
        Index("idx_branches_org_code", "organization_id", "code", unique=True),
    )
