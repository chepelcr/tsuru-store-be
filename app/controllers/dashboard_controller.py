"""Dashboard endpoints — one route per panel.

There used to be a single `/dashboard` returning everything. It reported zeros
for an organization with 45 real orders, because the sales figures were derived
by walking active session -> active assignment -> that assignment's orders: no
open till meant no revenue, no order count and no average ticket. (It also
aggregated from `sales_orders`/`order_items`, tables that do not exist here, and
swallowed the error.)

One route per question instead, so each panel is honest on its own and a panel
with nothing to show cannot blank the ones beside it:

    /dashboard/sales-summary   what we have sold
    /dashboard/order-status    what is in flight  (the "4 in process" panel)
    /dashboard/top-products    what is selling
    /dashboard/sales-trend     the chart, at hour / day / week / month
    /dashboard/session-sales   "ventas de la sesión" — open plus today's deliveries
    /dashboard/stations        who is on a till right now

Every panel accepts an optional `session_id` and `user_id`, and **the server
decides what they mean**: only an admin may see past their own rows, so a
cashier asking for session-wide figures is narrowed to their own rather than
refused. The scope actually applied comes back on the response, so the client can
label the figures instead of guessing. See `services/dashboard_scope.py`.
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import FastAPI, Header, HTTPException, Path, Query

from app.dtos.responses.dashboard_data_dto import DashboardDataResponse
from app.dtos.responses.dashboard_panels_dto import (
    OrderStatusResponse,
    SalesSummaryResponse,
    SalesTrendResponse,
    SessionSalesResponse,
    StationsResponse,
    TopProductsResponse,
)
from app.repositories.dashboard_repository import DEFAULT_GRANULARITY, GRANULARITIES
from app.services import dashboard_service

logger = logging.getLogger(__name__)

ORG = "/api/organizations/{organization_id}/dashboard"


class DashboardController:
    """Controller for the dashboard panel endpoints."""

    def __init__(self, app: FastAPI):
        self.register_routes(app)

    def register_routes(self, app: FastAPI):

        @app.get(
            f"{ORG}/sales-summary",
            response_model=SalesSummaryResponse,
            tags=["dashboard"],
            summary="Revenue, order count and average ticket",
            description=(
                "Counted from the organization's orders, so the figures are "
                "correct whether or not a cashier has a session open. Cancelled "
                "orders are excluded — they are not revenue, and including them "
                "would drag the average ticket toward a meaningless number.\n\n"
                "Optional `date_from`/`date_to` (ISO dates, inclusive) narrow the "
                "window. Filtering uses the `created_on` timestamp, never the "
                "`creation_date` string."
            ),
        )
        async def get_sales_summary(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
            date_from: Optional[str] = Query(None, description="ISO date, inclusive"),
            date_to: Optional[str] = Query(None, description="ISO date, inclusive"),
            session_id: Optional[str] = Query(None, description="Scope to one session"),
            user_id: Optional[str] = Query(
                None, description="Scope to one person (admins only; ignored otherwise)"),
        ):
            return _guard(
                lambda: dashboard_service.get_sales_summary(
                    organization_id, x_user_id, date_from, date_to, session_id, user_id),
                "sales summary",
            )

        @app.get(
            f"{ORG}/order-status",
            response_model=OrderStatusResponse,
            tags=["dashboard"],
            summary="Order counts and value per status",
            description=(
                "Every status the organization's orders are in, busiest first, "
                "with the in-flight ones rolled up into `open_orders` / "
                "`open_value`. This is what answers \"I have orders in process\" — "
                "the single-revenue-total dashboard could not show it at all."
            ),
        )
        async def get_order_status(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
            session_id: Optional[str] = Query(None, description="Scope to one session"),
            user_id: Optional[str] = Query(
                None, description="Scope to one person (admins only; ignored otherwise)"),
        ):
            return _guard(
                lambda: dashboard_service.get_order_status(
                    organization_id, x_user_id, session_id, user_id),
                "order status breakdown",
            )

        @app.get(
            f"{ORG}/top-products",
            response_model=TopProductsResponse,
            tags=["dashboard"],
            summary="Best-selling products by revenue",
            description=(
                "Ranked from the order lines, filtered to revenue statuses so a "
                "cancelled order cannot recommend restocking something nobody "
                "bought. `limit` is clamped server-side."
            ),
        )
        async def get_top_products(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
            limit: int = Query(10, ge=1, le=50, description="How many products"),
            session_id: Optional[str] = Query(None, description="Scope to one session"),
            user_id: Optional[str] = Query(
                None, description="Scope to one person (admins only; ignored otherwise)"),
        ):
            return _guard(
                lambda: dashboard_service.get_top_products(
                    organization_id, x_user_id, limit, session_id, user_id),
                "top products",
            )

        @app.get(
            f"{ORG}/sales-trend",
            response_model=SalesTrendResponse,
            tags=["dashboard"],
            summary="Revenue per hour, day, week or month",
            description=(
                "Revenue and order count per bucket, oldest first.\n\n"
                "`granularity` is one of `hour`, `day`, `week`, `month`. Combine "
                "it with `date_from`/`date_to` (ISO dates, inclusive) for a chosen "
                "period — `hour` over a single day, `month` over a year.\n\n"
                "Buckets with no sales are ABSENT rather than zero: a missing "
                "bucket and a zero bucket are different facts, and the caller "
                "knows the window it asked for. Bucket starts are ISO 8601 with a "
                "time component at every granularity, so a client never has to "
                "guess which shape it received."
            ),
        )
        async def get_sales_trend(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
            granularity: str = Query(
                DEFAULT_GRANULARITY,
                description=f"One of: {', '.join(GRANULARITIES)}",
            ),
            date_from: Optional[str] = Query(None, description="ISO date, inclusive"),
            date_to: Optional[str] = Query(None, description="ISO date, inclusive"),
            session_id: Optional[str] = Query(None, description="Scope to one session"),
            user_id: Optional[str] = Query(
                None, description="Scope to one person (admins only; ignored otherwise)"),
        ):
            # Rejected here as a 400 rather than reaching the repository's
            # ValueError, which `_guard` would also turn into a 400 — this just
            # says which values are legal.
            if granularity not in GRANULARITIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"granularity must be one of: {', '.join(GRANULARITIES)}",
                )
            return _guard(
                lambda: dashboard_service.get_sales_trend(
                    organization_id, x_user_id, granularity,
                    date_from, date_to, session_id, user_id),
                "sales trend",
            )

        @app.get(
            f"{ORG}/session-sales",
            response_model=SessionSalesResponse,
            tags=["dashboard"],
            summary='"Ventas de la sesión" — what is on the books now',
            description=(
                "A different question from revenue, and a different set of "
                "statuses: `pending`, `processing` and `shipped` always count, and "
                "`delivered` counts only when it was delivered TODAY. A pedido "
                "delivered last week is finished business and should not still be "
                "inflating today's figure.\n\n"
                "`delivered_rule` says which rule was applied. It reads "
                "`created_today` for now: `delivery_date` is a VARCHAR holding two "
                "different formats, so it cannot be compared to today without "
                "misreading the month, and the response says so rather than "
                "implying a delivery-date rule it is not yet applying."
            ),
        )
        async def get_session_sales(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
            session_id: Optional[str] = Query(None, description="Scope to one session"),
            user_id: Optional[str] = Query(
                None, description="Scope to one person (admins only; ignored otherwise)"),
        ):
            return _guard(
                lambda: dashboard_service.get_session_sales(
                    organization_id, x_user_id, session_id, user_id),
                "session sales",
            )

        @app.get(
            f"{ORG}/stations",
            response_model=StationsResponse,
            tags=["dashboard"],
            summary="Tills currently open, and their takings",
            description=(
                "The only panel that legitimately depends on an open session — it "
                "is the question \"who is working\". An empty list means nobody is "
                "on a till, which no longer affects the sales figures.\n\n"
                "Per-station takings come from orders carrying that "
                "`assignment_id`; most orders do not carry one, which is exactly "
                "why organization-wide revenue is a separate endpoint."
            ),
        )
        async def get_stations(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
            session_id: Optional[str] = Query(None, description="Filter to one session"),
        ):
            return _guard(
                lambda: dashboard_service.get_stations(organization_id, session_id),
                "stations",
            )


        @app.get(
            ORG,
            response_model=DashboardDataResponse,
            tags=["dashboard"],
            deprecated=True,
            summary="DEPRECATED — the whole dashboard in one payload",
            description=(
                "Superseded by the five panel endpoints, which load and fail "
                "independently. Kept for one release so a deployed client does "
                "not break the moment the panels ship.\n\n"
                "It is now composed FROM those panels, so it reports the real "
                "organization totals rather than the zeros it returned whenever "
                "no cashier had a till open. `cash`/`sinpe`/`card` are always 0 "
                "here — nothing read them."
            ),
        )
        async def get_dashboard(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
            session_id: Optional[str] = Query(None, description="Filter to one session"),
        ):
            return _guard(
                lambda: dashboard_service.get_dashboard_data(
                    organization_id, x_user_id, session_id=session_id),
                "dashboard",
            )


def _guard(call, what: str):
    """Run a panel query, turning a failure into a 4xx/5xx rather than a zero.

    The old implementation returned empty results when its query failed, so a
    broken dashboard was indistinguishable from a quiet day — which is how a
    query against non-existent tables survived in production. A panel that cannot
    answer now says so.
    """
    try:
        return call()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting %s: %s", what, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not load {what}")
