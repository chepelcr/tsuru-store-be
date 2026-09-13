"""Order Detail Line DTO - Individual line item in an order."""

from typing import Optional
from pydantic import BaseModel, Field


class OrderDetailLineResponse(BaseModel):
    """
    Order detail line item.
    
    Represents a single product line in an order with quantities,
    pricing, and dispatch/receipt information.
    """
    
    line_number: int = Field(
        ...,
        description="Line number in the order",
        examples=[1, 2, 3]
    )
    
    internal_code: str = Field(
        ...,
        description="Internal product code",
        examples=["INT-001", "PROD-123"]
    )
    
    code: str = Field(
        ...,
        description="Product code",
        examples=["PROD-001", "SKU-456"]
    )
    
    client_article_code: str = Field(
        ...,
        description="Client's article code",
        examples=["CLIENT-001", "ART-789"]
    )
    
    description: str = Field(
        ...,
        description="Product description",
        examples=["Product Name", "Item Description"]
    )
    
    units_per_box: int = Field(
        ...,
        description="Number of units per box",
        ge=1,
        examples=[12, 24, 50]
    )
    
    quantity_ordered: int = Field(
        ...,
        description="Quantity ordered (in boxes)",
        ge=0,
        examples=[10, 20, 50]
    )
    
    units_ordered: int = Field(
        ...,
        description="Total units ordered",
        ge=0,
        examples=[120, 480, 2500]
    )
    
    unit_price: float = Field(
        ...,
        description="Price per unit",
        ge=0,
        examples=[10.50, 25.99, 100.00]
    )
    
    discount: float = Field(
        ...,
        description="Discount amount",
        ge=0,
        examples=[0.0, 5.50, 10.00]
    )
    
    line_total: float = Field(
        ...,
        description="Total amount for this line",
        ge=0,
        examples=[100.00, 500.50, 1000.00]
    )
    
    tax: float = Field(
        ...,
        description="Tax amount for this line",
        ge=0,
        examples=[13.00, 65.07, 130.00]
    )
    
    quantity_dispatched: int = Field(
        ...,
        description="Quantity dispatched (in boxes)",
        ge=0,
        examples=[10, 20, 50]
    )
    
    dispatch_rejection_reason: Optional[str] = Field(
        None,
        description="Reason for dispatch rejection if applicable",
        examples=["Out of stock", "Damaged goods", None]
    )
    
    quantity_received: int = Field(
        ...,
        description="Quantity received (in boxes)",
        ge=0,
        examples=[10, 20, 50]
    )
    
    article_code: str = Field(
        ...,
        description="Article code",
        examples=["ART-001", "ARTICLE-456"]
    )

    product_id: Optional[str] = Field(
        None,
        description=(
            "Catalog product this line came from. REQUIRED to rebuild a cart "
            "when billing the order later — lines are linked by product_id, "
            "never by description."
        ),
        examples=["7f3d…", None]
    )

    cabys: Optional[str] = Field(
        None,
        description=(
            "CABYS code captured with the line. Kept even though a pedido is "
            "not fiscal: fabricating one later would put the wrong tax rate on "
            "a real document."
        ),
        examples=["0161010150000", None]
    )

    net_price: Optional[float] = Field(
        None,
        description="Unit price before tax",
        ge=0,
        examples=[3500.00, None]
    )

    taxes: Optional[list] = Field(
        None,
        description=(
            "Per-line tax breakdown, canonical `ProductTaxDTO` shape: "
            "[{tax_type_id, tax_rate: {id, percentage, code}, tax_factor: "
            "{id, factor}, special_fields: {quantity, percentage, proportion, "
            "volume_consumption, tax_amount: {id, amount}}, exemption: {type, "
            "other_type, number, institution, percentage}, is_amount, amount}]. "
            "Rows written before this was unified are normalized on read; the "
            "flatter `{code, rate_code, rate}` request spelling is legacy."
        ),
    )

    discounts: Optional[list] = Field(
        None,
        description=(
            "Per-line discount cascade in Nota 20 order, canonical "
            "`ProductDiscountDTO` shape: [{discount_type_id, percentage, reason, "
            "is_amount, amount}]. Note `reason` is the Nota 20 free text — the "
            "request spelling calls the same field `nature`."
        ),
    )

    # ── The rest of the document line ────────────────────────────────────
    # An order line now mirrors `DetalleLinea` field for field, so billing a
    # pedido reads what the order says instead of guessing it back from the
    # catalog. Each of these was previously lost between the two.

    codes: Optional[list] = Field(
        None,
        description=(
            "The LINE's own product codes [{code_type_id, number}] — Nota 6: "
            "01 vendedor, 02 comprador, 03 fabricante, 04 uso interno, 99 otros. "
            "Distinct from the product's: a chain assigns its own buyer article "
            "code, and the product's array only holds the latest import's."
        ),
    )

    unit_measure: Optional[str] = Field(
        None,
        description="Hacienda UnidadMedida — required on every document line",
        examples=["Unid", "kg", "Sp"],
    )

    commercial_unit_measure: Optional[str] = Field(
        None,
        description="Free-text commercial unit shown to the customer",
        examples=["Caja de 12"],
    )

    customs_part: Optional[str] = Field(
        None,
        description="Partida arancelaria, for imported goods",
    )

    base_amount: Optional[float] = Field(
        None,
        description=(
            "Editable taxable base. Legal only for tax code 07 (IVA cálculo "
            "especial) or IVACobradoFabrica '01'; rejected elsewhere."
        ),
        ge=0,
    )

    iva_collected_factory: Optional[str] = Field(
        None,
        description="IVACobradoFabrica: '01' settled at factory, '02' exempt by regime",
        examples=["01", "02"],
    )
