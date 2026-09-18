"""Response DTOs for the dashboard panels (one per question).

The dashboard used to be a single `/dashboard` call returning one object with
everything in it. That coupling was the bug: sales figures were gated on there
being an open cashier session, so 45 real orders rendered as zeros. Splitting the
payloads splits the failure modes too — a station panel that cannot load no
longer blanks the revenue figure beside it.

Authors: jcampos
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ScopeInfo(BaseModel):
    """What slice the server actually answered for.

    Returned on every panel because the request does not decide it — a non-admin
    asking for a whole session is narrowed to their own rows. The client needs to
    know which it got, or it will label one as the other.
    """

    scope: str = Field(
        ...,
        description="organization | session | session_user",
        examples=["session_user"],
    )
    session_id: Optional[str] = Field(None, description="Session the figures cover")
    user_id: Optional[str] = Field(None, description="Set when narrowed to one person")
    is_admin: bool = Field(False, description="Whether the caller may widen the scope")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SalesSummaryResponse(BaseModel):
    """What the organization has actually sold."""

    orders: int = Field(..., description="Orders counted as revenue", examples=[33])
    revenue: float = Field(..., description="Sum of grand totals", examples=[2553498.17])
    average_ticket: float = Field(
        ...,
        description="Revenue divided by order count; 0 when there are no orders",
        examples=[77378.73],
    )
    units: float = Field(0, description="Total quantities sold", examples=[529])
    last_order_at: Optional[datetime] = Field(
        None, description="When the most recent counted order was created")
    scope: Optional[ScopeInfo] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrderStatusCount(BaseModel):
    """One `order_status` with its count and value."""

    status: str = Field(..., examples=["processing"])
    orders: int = Field(..., examples=[4])
    value: float = Field(..., description="Sum of grand totals in this status",
                         examples=[373069.5])
    is_open: bool = Field(
        ..., description="Whether this status means the order is still in flight")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrderStatusResponse(BaseModel):
    """Every status the organization's orders are currently in."""

    statuses: List[OrderStatusCount] = Field(default_factory=list)
    open_orders: int = Field(0, description="Total orders in an in-flight status")
    open_value: float = Field(0, description="Value of those in-flight orders")
    scope: Optional[ScopeInfo] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TopProductItem(BaseModel):
    """One product in the ranking."""

    product_id: Optional[str] = None
    name: str = Field(..., examples=["ALMOHADA BEBE SENCILLA"])
    image_url: str = Field("", description="Empty when the product has no image")
    units: float = Field(..., examples=[296])
    revenue: float = Field(..., examples=[731663.28])

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TopProductsResponse(BaseModel):
    """Best sellers by revenue."""

    products: List[TopProductItem] = Field(default_factory=list)
    scope: Optional[ScopeInfo] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SalesTrendPoint(BaseModel):
    """Revenue for one bucket of the requested granularity."""

    bucket: Optional[str] = Field(
        None,
        description=(
            "Start of the bucket, ISO 8601. Always carries a time component so "
            "hour buckets are unambiguous and one format covers every "
            "granularity."
        ),
        examples=["2026-09-14T00:00:00"],
    )
    orders: int = Field(..., examples=[3])
    revenue: float = Field(..., examples=[125000.0])

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SalesTrendResponse(BaseModel):
    """Revenue per bucket, oldest first.

    Buckets with no sales are ABSENT rather than zero: a missing bucket and a
    zero bucket are different facts, and the caller knows the window it asked
    for.
    """

    granularity: str = Field(..., description="hour | day | week | month",
                             examples=["day"])
    date_from: Optional[str] = Field(None, description="Window start, if given")
    date_to: Optional[str] = Field(None, description="Window end, if given")
    points: List[SalesTrendPoint] = Field(default_factory=list)
    scope: Optional[ScopeInfo] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SessionSalesResponse(BaseModel):
    """"Ventas de la sesión" — what is on the books right now."""

    orders: int = Field(..., examples=[4])
    revenue: float = Field(..., examples=[373069.5])
    average_ticket: float = Field(..., examples=[93267.37])
    delivered_rule: str = Field(
        ...,
        description=(
            "Which rule decided whether a DELIVERED order counted. "
            "`delivery_date_today` once that column is a real date; "
            "`created_today` while it is still a two-format string that cannot "
            "be compared safely."
        ),
        examples=["created_today"],
    )
    scope: Optional[ScopeInfo] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class StationItem(BaseModel):
    """One open till and what has been rung up on it."""

    assignment_id: str
    branch_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: str
    session_name: str = ""
    session_context: str = ""
    started_at: Optional[datetime] = None
    orders: int = 0
    revenue: float = 0
    last_order_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class StationsResponse(BaseModel):
    """Who is on a till right now.

    An empty list means nobody is working — a real answer, and no longer one that
    takes the organization's sales figures down with it.
    """

    stations: List[StationItem] = Field(default_factory=list)
    active_sessions: int = Field(0, description="Distinct sessions represented")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
