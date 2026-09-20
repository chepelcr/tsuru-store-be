from __future__ import annotations

import uuid
from typing import List, Optional

from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base


class Order(Base, AuditMixin):
    __tablename__ = "crossdocking_orders"

    order_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("organizations.id"), nullable=False
    )
    document_number: Mapped[str] = mapped_column(String(50), nullable=False)
    # Real dates since migration d3e4f5a6b7c8. They were VARCHAR(20) holding TWO
    # formats — DD/MM/YYYY from the Excel import, YYYY-MM-DD from the POS — which
    # made every range filter a lexicographic string compare and every read a
    # guess. Anything touching them goes through `app.utils.order_dates`.
    creation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    order_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="pending")
    subtotal: Mapped[Optional[float]] = mapped_column(Numeric(18, 5), nullable=True, default=0)
    discounts: Mapped[Optional[float]] = mapped_column(Numeric(18, 5), nullable=True, default=0)
    net_total: Mapped[Optional[float]] = mapped_column(Numeric(18, 5), nullable=True, default=0)
    taxes: Mapped[Optional[float]] = mapped_column(Numeric(18, 5), nullable=True, default=0)
    grand_total: Mapped[Optional[float]] = mapped_column(Numeric(18, 5), nullable=True, default=0)
    total_quantities: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, default=0)
    line_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, default=0)
    document_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bgm011: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    order_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    event: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    latitude: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    longitude: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    crossdocking_pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    nuevo_reporte_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    excel_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    #: 80mm thermal ticket (TSR-127). A document FORMAT of the order alongside
    #: its PDF and Excel, so it is identical however it is opened and can be
    #: re-printed or emailed later.
    ticket_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    crossdocking_excel_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    confirmation_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("crossdocking_confirmations.confirmation_id"), nullable=True
    )
    confirmation_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    report_color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="green")

    # --- Manual orders / pedidos manuales (TSR-152) -----------------------
    # A pedido captured by hand in the POS editor by an organization that does
    # not (or cannot yet) issue electronic documents. `source` keeps them apart
    # from Excel-imported and storefront orders, and lets the IVA report
    # exclude them: a pedido is not a fiscal document.
    source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, default="import")
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # POS attribution — which cashier, on which branch/terminal.
    assignment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    branch_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    terminal_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # The editor is multi-currency, so the order has to carry the rate it was
    # captured at rather than assuming colones.
    currency_code: Mapped[Optional[str]] = mapped_column(String(3), nullable=True, default="CRC")
    exchange_rate: Mapped[Optional[float]] = mapped_column(Numeric(18, 5), nullable=True, default=1)

    # Label for a delivery point the client has NOT registered as a Store.
    delivery_location_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Captured at the till so billing the order later reuses the same choices
    # instead of asking again.
    activity_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    sale_condition: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    credit_term: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Hacienda payment codes; may be empty — a pedido is settled after delivery.
    payments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Outbox replay dedup. The POS reuses the same key on every retry, so a
    # pedido captured offline cannot become two orders.
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # --- Taller / work orders (TSR-163) -----------------------------------
    asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_assets.asset_id"), nullable=True
    )
    odometer: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reported_issue: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # --- Billing link (TSR-152 §3.4, reshaped TSR-317) --------------------
    # Without this a delivered pedido can be invoiced twice: the FE can only
    # hide the button when the BE says it is already billed.
    #
    # One id plus one snapshot, replacing the five flat `invoice_*` columns.
    # `document_id` is sales-be's `Sale.sale_id` UUID — the identifier the POS
    # routes a document by (`/dashboard/documents/{saleId}`), so the order links
    # straight to it. `document_info` is the rest of the document, denormalised
    # deliberately: store-be does not own `billing_sales` and cannot join to it,
    # so an order that could only name a foreign id would have nothing to show
    # on its badge without a second service call per row.
    #
    # Written by the SQS consumer: claimed at emission with `status` 0
    # (PROCESSING) so the order cannot be billed twice while the document is
    # in flight, then confirmed to 1 when Hacienda accepts it. Not by the
    # checkout. See `services/order_service.link_order_document`.
    document_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    document_info: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # --- Storefront (anonymous) pedido fields (TSR-118 / W11) --------------
    # A tracked order placed from a public storefront. The customer is a guest
    # (no user account / no Client row required), so name/phone are captured
    # inline alongside the structured CR address (W9: provincia / cantón /
    # distrito / barrio + dirección exacta) and a public tracking number.
    tracking_number: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    delivery_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Structured Costa Rica location cascade (data-be catalog ids).
    state_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    county_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    district_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    neighborhood_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Normalized FK columns
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.client_id"), nullable=True
    )
    deliver_to_store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.store_id"), nullable=True
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.department_id"), nullable=True
    )

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(foreign_keys=[company_id])
    client: Mapped[Optional["Client"]] = relationship(foreign_keys=[client_id])
    deliver_to_store: Mapped[Optional["Store"]] = relationship(foreign_keys=[deliver_to_store_id])
    department_rel: Mapped[Optional["Department"]] = relationship(foreign_keys=[department_id])
    asset: Mapped[Optional["ClientAsset"]] = relationship(foreign_keys=[asset_id])
    lines: Mapped[List["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    crossdocking_sale_points: Mapped[List["CrossDockingSalePoint"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    confirmation: Mapped[Optional["Confirmation"]] = relationship(
        back_populates="orders"
    )

    __table_args__ = (
        Index("idx_order_company_id", "company_id"),
        Index("idx_order_document_number", "document_number"),
        Index("idx_order_company_document", "company_id", "document_number", unique=True),
        Index("idx_order_source", "company_id", "source"),
        Index("idx_order_document_id", "company_id", "document_id"),
        Index(
            "idx_order_idempotency",
            "company_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )
