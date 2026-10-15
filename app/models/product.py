from __future__ import annotations

import uuid as _uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.enums.product_status import ProductStatus
from app.enums.product_type import ProductType


class Product(Base, TimestampMixin):
    """Maps to the existing BeautyMarket products table.

    Product codes are stored in the JSONB 'codes' array with Hacienda code types.
    Existing BeautyMarket columns are preserved.
    """
    __tablename__ = "products"

    # Existing BeautyMarket columns
    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 5), nullable=False)
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=False
    )
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=ProductStatus.ACTIVE, index=True)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    track_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_service: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # First-class product kind: product | service | program. ``is_service`` is
    # kept for backward compatibility (mirrors ``type == 'service'``).
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProductType.PRODUCT.value, index=True
    )
    on_sale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Storefront "Oferta" flag — independent of the ``on_sale`` discount
    # mechanic; flags a product/service the store wants to feature as an offer.
    is_offer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    original_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 5), nullable=True
    )
    discount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # ── Vertical flags (TSR-154 / 155 / 159 / 162) ────────────────────────
    # A combo's price is its OWN price, never the sum of its parts; the parts
    # live in `combo_items` and the POS explodes the line so each keeps its
    # own CABYS and IVA rate.
    is_combo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Licor / cigarrillos — prompts the cashier once per cart.
    is_age_restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Pharmacy: needs a lot at the till, and/or a register entry before checkout.
    is_lot_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_controlled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Salón / taller: how long a service occupies a slot in the agenda.
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Cross-docking column (kept for units per box)
    units_per_box: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, default=0)

    # Fiscal / Hacienda e-invoicing columns
    cabys_id: Mapped[Optional[_uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cabys.id"), nullable=True
    )
    # Canonical Hacienda unit-of-measure code (e.g. "Unid", "Sp", "kg").
    # Replaces the old `unit_id INT` which referenced data-services across
    # service boundaries and was always wrong in practice.
    unit_measure: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    commercial_unit_measure: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_packaged: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=False)
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True, default=1)
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 5), nullable=True)
    customs_part: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    codes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    discounts: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    taxes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    base_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 5), nullable=True)
    sale_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 5), nullable=True)

    # Hacienda v4.4 Exoneracion block + IVACobradoFabrica indicator.
    exemption_authorization_code: Mapped[Optional[str]] = mapped_column(
        String(2), nullable=True
    )
    exempted_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 2), nullable=True)
    exemption_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 5), nullable=True
    )
    iva_collected_factory: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    # data-services FK for the factory-tax-charge catalog row.
    factory_tax_charge_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(foreign_keys=[organization_id])
    category: Mapped[Optional["Category"]] = relationship(foreign_keys=[category_id])
    cabys: Mapped[Optional["Cabys"]] = relationship(foreign_keys=[cabys_id])
    
    @property
    def is_active(self) -> bool:
        """Backward compatibility property for is_active."""
        return self.status == ProductStatus.ACTIVE
    
    @is_active.setter
    def is_active(self, value: bool) -> None:
        """Backward compatibility setter for is_active."""
        self.status = ProductStatus.ACTIVE if value else ProductStatus.INACTIVE
