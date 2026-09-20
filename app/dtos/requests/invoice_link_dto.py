"""Repair-path body for linking an order to the document that billed it.

The same snapshot the `LINK_ORDER_DOCUMENT` event carries, so the repair path
and the queue path write identical rows. Only `document_id` — the sale UUID —
is required; the rest is what the order's badge and detail page display.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LinkOrderInvoiceDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    #: sales-be's `Sale.sale_id` — the UUID the POS routes a document by.
    document_id: str = Field(..., min_length=1, max_length=255)
    #: sales-be's `Sale.document_id`, the internal bigint. Display only.
    document_number: Optional[int] = None
    document_type: Optional[str] = Field(None, max_length=8)
    consecutive_number: Optional[str] = Field(None, max_length=50)
    document_key: Optional[str] = Field(None, max_length=100)
    issued_on: Optional[str] = Field(None, max_length=40)
    #: Hacienda verdict: 1 ACCEPTED, 2 PARTIAL, 3 REJECTED.
    status: Optional[int] = None
    total_amount: Optional[float] = None
    currency_code: Optional[str] = Field(None, max_length=10)
