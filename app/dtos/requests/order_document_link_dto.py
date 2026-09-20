"""Inbound order↔document link contract: what sales-be publishes, as we read it.

Mirror of `jbiller_common.hacienda.dtos.events.order_document_link_event` in the
sales-be repo. Two repos, one wire format — the pairing is pinned by a contract
test there, the same way the branch-sync contract is.

Deliberately permissive about the document block's contents and strict about its
identity: `document_id` is the link and must be present, everything else is
display material that a future sales-be may add to. `extra="ignore"` means a
field added upstream does not start rejecting messages here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LinkEventDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class LinkedDocumentDTO(LinkEventDTO):
    #: sales-be's `Sale.sale_id` — the UUID the POS routes a document by.
    document_id: str = Field(min_length=1, max_length=255)
    #: sales-be's `Sale.document_id`, the internal bigint. Display only.
    document_number: Optional[int] = None
    document_type: Optional[str] = Field(None, max_length=8)
    consecutive_number: Optional[str] = Field(None, max_length=50)
    document_key: Optional[str] = Field(None, max_length=100)
    issued_on: Optional[str] = Field(None, max_length=40)
    #: Hacienda verdict at publish time. Always 1 (ACCEPTED) today.
    status: Optional[int] = None
    total_amount: Optional[float] = None
    currency_code: Optional[str] = Field(None, max_length=10)


class OrderDocumentLinkPayload(LinkEventDTO):
    organization_id: str = Field(min_length=1, max_length=255)
    #: The order's own number — `PM-000123`, or a chain's purchase order.
    order_document_number: str = Field(min_length=1, max_length=50)
    #: `manual` | `import` | `storefront`. Not needed to resolve the order.
    order_source: Optional[str] = Field(None, max_length=16)
    document: LinkedDocumentDTO


class OrderDocumentLinkEvent(LinkEventDTO):
    id: str = Field(min_length=1)
    occurred_at: datetime
    # The one alias that stays: `_type` is a discriminator, not a data field,
    # and a leading underscore cannot be a pydantic attribute name.
    type_: Literal["OrderDocumentLinkEvent"] = Field(alias="_type")
    event_type: Literal["LINK_ORDER_DOCUMENT"]
    data: OrderDocumentLinkPayload
