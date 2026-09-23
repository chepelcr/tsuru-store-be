from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base


class Client(Base, AuditMixin):
    __tablename__ = "clients"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    client_gln: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Identification
    identification_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    identification_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Business info
    business_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Phone
    phone_country_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    phone_area_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    phone_description: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Residence
    state_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    county_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    district_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    neighborhood_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Free-text notes kept against the customer. The POS has shipped a notes
    # panel and a save button for it all along, against a column that did not
    # exist: `ClientRequestDTO` does not forbid extra keys, so the note was
    # accepted, ignored and lost, and the panel read back empty every time.
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    stores: Mapped[List["Store"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    departments: Mapped[List["Department"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    # The phone's country from data-be's catalog (no FK across services), so the
    # dialing code comes from the DB rather than from each client's lookup.
    phone_country: Mapped[Optional["Country"]] = relationship(
        "Country",
        primaryjoin="foreign(Client.phone_country_code) == Country.iso_code",
        viewonly=True,
        uselist=False,
        lazy="select",
    )
    assets: Mapped[List["ClientAsset"]] = relationship(back_populates="client", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_client_company_gln_nationality", "company_id", "client_gln", "nationality", unique=True),
        Index("idx_client_company_id", "company_id"),
    )
