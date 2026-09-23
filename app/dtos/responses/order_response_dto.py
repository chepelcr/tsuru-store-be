"""Order DTO - Main order information."""
"""Order DTO - Main order information."""

from typing import List, Optional
from datetime import date

from pydantic import BaseModel, Field, ConfigDict

from .crossdocking_data_dto import CrossDockingDataDTO
from .department_dto import DepartmentDTO
from .order_detail_line_dto import OrderDetailLineResponse
from .order_detail_totals_dto import OrderDetailTotals
from .party_dto import PartyDTO
from .location_dto import LocationDTO
from .order_attachments_dto import OrderAttachmentsDTO


class OrderResponse(BaseModel):
    """
    Order response.
    
    Represents a complete order with header information, line items,
    crossdocking data, and totals. Used for both single order retrieval
    and order list responses.
    
    Order Types:
        - Standard order
        - Crossdocking order
        - Direct delivery order
    
    Document Types:
        - Purchase order
        - Sales order
        - Transfer order
    """
    
    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True
    )
    
    order_id: int = Field(
        ...,
        description="Internal order identifier",
        examples=[1, 100, 5000]
    )
    
    company_id: str = Field(
        ...,
        description="Company identifier",
        examples=["COMP-001", "ABC123"]
    )
    
    document_number: str = Field(
        ...,
        description="Order document number",
        examples=["ORD-2024-001", "PO-123456"]
    )
    
    document_type: Optional[str] = Field(
        None,
        description="Document type code",
        examples=["PO", "SO", "TO"]
    )
    
    bgm011: Optional[str] = Field(
        None,
        description="BGM 011 code (EDI reference)",
        examples=["220", "231"]
    )
    
    confirmation_id: Optional[int] = Field(
        None,
        description="Confirmation group identifier",
    )

    confirmation_number: Optional[str] = Field(
        None,
        description="User-provided confirmation number",
    )

    order_type: Optional[str] = Field(
        None,
        description="Order type",
        examples=["Standard", "Crossdocking", "Direct"]
    )
    
    # ISO on the wire, always. These were VARCHAR columns holding both
    # DD/MM/YYYY and YYYY-MM-DD, so a client had to sniff which it got; now the
    # column is a real date and `date` serialises as ISO, so there is one shape.
    creation_date: Optional[date] = Field(
        None,
        description="Order creation date (ISO `YYYY-MM-DD`)",
        examples=["2026-01-15"]
    )

    delivery_date: Optional[date] = Field(
        None,
        description="Expected delivery date (ISO `YYYY-MM-DD`)",
        examples=["2026-01-20"]
    )
    
    order_status: Optional[str] = Field(
        "pending",
        description="Order status (pending, processing, shipped, delivered, cancelled)",
        examples=["pending", "processing", "shipped", "delivered", "cancelled"]
    )
    
    client: Optional[PartyDTO] = Field(
        None,
        description="Client information"
    )

    # The catalog client row, not just its name. Billing a pedido has to select
    # the very same customer the order was captured for — and departments and
    # delivery points are scoped to that client id, so without it the invoice
    # cannot offer either. It was omitted here while `client` (a display-only
    # name/GLN pair) was returned, so every order looked like it had no client.
    client_id: Optional[str] = Field(
        None,
        description="Catalog client id this order belongs to",
    )
    
    supplier: Optional[PartyDTO] = Field(
        None,
        description="Supplier information"
    )
    
    delivery_location: Optional[LocationDTO] = Field(
        None,
        description="Delivery location information"
    )
    
    source: Optional[str] = Field(
        None,
        description=(
            "Where the order came from: 'import' (Excel), 'manual' (POS pedido "
            "manual) or 'storefront'. The IVA report excludes manual orders — "
            "a pedido is not a fiscal document."
        ),
        examples=["import", "manual", "storefront"]
    )

    currency_code: Optional[str] = Field(
        None,
        description="Currency the order was captured in",
        examples=["CRC", "USD"]
    )

    exchange_rate: Optional[float] = Field(
        None,
        description="Exchange rate at capture time",
        examples=[1, 512.35]
    )

    is_quote: Optional[bool] = Field(
        None,
        description="True while order_status is 'quote' (a proforma awaiting approval)",
    )

    document_id: Optional[str] = Field(
        None,
        description=(
            "Identifier of the electronic document that billed this order, once "
            "linked — the sale UUID, which is what the POS routes a document by. "
            "Its presence is what lets the UI hide 'Facturar pedido' and stop a "
            "second factura being issued."
        ),
    )

    document_info: Optional[dict] = Field(
        None,
        description=(
            "That document, reduced to what the order needs to show: "
            "`document_id`, `document_number`, `document_type`, "
            "`consecutive_number`, `document_key`, `issued_on`, `status` "
            "(Hacienda verdict), `total_amount`, `currency_code`. Written when "
            "Hacienda accepts the document, not at checkout time, so it is "
            "absent while a document is still being validated."
        ),
    )

    credit_notes: Optional[List[dict]] = Field(
        None,
        description=(
            "Credit notes issued against the order's invoice (TSR-340), each "
            "`document_id`, `document_type`, `consecutive_number`, `document_key`, "
            "`issued_on`, `status`, `total_amount`, `currency_code`, `tipo_nota` "
            "(e.g. NCprontopago). They never replace `document_id`."
        ),
    )

    event: Optional[str] = Field(
        None,
        description="Event identifier",
        examples=["EVENT-001", "PROMO-2024"]
    )
    
    department: Optional[DepartmentDTO] = Field(
        None,
        description="Department"
    )
    
    comment: Optional[str] = Field(
        None,
        description="Additional comments",
        examples=["Urgent delivery", "Handle with care"]
    )
    
    line_count: Optional[int] = Field(
        0,
        description="Number of line items",
        ge=0,
        examples=[5, 10, 25]
    )
    
    total_quantities: Optional[int] = Field(
        0,
        description="Total quantities (boxes)",
        ge=0,
        examples=[10, 50, 100]
    )
    
    subtotal: Optional[float] = Field(
        0,
        description="Subtotal amount",
        ge=0,
        examples=[1000.00, 5000.00, 10000.00]
    )
    
    discounts: Optional[float] = Field(
        0,
        description="Total discounts applied",
        ge=0,
        examples=[0.0, 50.00, 100.00]
    )
    
    net_total: Optional[float] = Field(
        0,
        description="Net total (subtotal - discounts)",
        ge=0,
        examples=[950.00, 4950.00, 9900.00]
    )
    
    taxes: Optional[float] = Field(
        0,
        description="Total taxes",
        ge=0,
        examples=[0.0, 130.00, 500.00]
    )
    
    grand_total: Optional[float] = Field(
        0,
        description="Grand total (net_total + taxes)",
        ge=0,
        examples=[1000.00, 5000.00, 10000.00]
    )
    
    attachments: Optional[OrderAttachmentsDTO] = Field(
        None,
        description="Document attachments (PDF, Excel)"
    )
    
    lines: list[OrderDetailLineResponse] = Field(
        default_factory=list,
        description="Order line items"
    )
    
    order_totals: Optional[OrderDetailTotals] = Field(
        None,
        description="Order totals summary"
    )
    
    crossdocking: Optional[CrossDockingDataDTO] = Field(
        None,
        description="Crossdocking information if applicable"
    )
