"""Dashboard panels — one function per question the dashboard asks.

Previously this was a single `get_dashboard_data` that answered everything or
nothing, and it chose nothing: the sales figures were computed by walking active
session -> active assignment -> orders-for-that-assignment, so an organization
with 45 orders and no open till reported zero revenue, zero orders and a zero
average ticket. The tables it aggregated from (`sales_orders`, `order_items`) did
not even exist in this database, and the failure was swallowed.

Each function here is independent, so a panel that has nothing to show says so
without silencing the others.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.dtos.responses.dashboard_data_dto import (
    DashboardDataResponse,
    ProductRanking,
    StandData,
)
from app.dtos.responses.dashboard_panels_dto import (
    OrderStatusCount,
    OrderStatusResponse,
    SalesSummaryResponse,
    SalesTrendPoint,
    SalesTrendResponse,
    StationItem,
    StationsResponse,
    TopProductItem,
    TopProductsResponse,
)
from app.repositories.dashboard_repository import DashboardRepository

logger = logging.getLogger(__name__)

MAX_TOP_PRODUCTS = 50
MAX_TREND_DAYS = 90


def get_sales_summary(
    organization_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> SalesSummaryResponse:
    """Revenue, order count and average ticket, from the orders themselves."""
    with DashboardRepository() as repo:
        return SalesSummaryResponse(**repo.sales_summary(organization_id, date_from, date_to))


def get_order_status(organization_id: str) -> OrderStatusResponse:
    """Order counts per status, with the in-flight totals rolled up."""
    with DashboardRepository() as repo:
        rows = repo.order_status_breakdown(organization_id)

    statuses = [OrderStatusCount(**row) for row in rows]
    return OrderStatusResponse(
        statuses=statuses,
        open_orders=sum(s.orders for s in statuses if s.is_open),
        open_value=sum(s.value for s in statuses if s.is_open),
    )


def get_top_products(organization_id: str, limit: int = 10) -> TopProductsResponse:
    """Best sellers by revenue. `limit` is clamped, not trusted."""
    limit = max(1, min(int(limit or 10), MAX_TOP_PRODUCTS))
    with DashboardRepository() as repo:
        rows = repo.top_products(organization_id, limit)
    return TopProductsResponse(products=[TopProductItem(**row) for row in rows])


def get_sales_trend(organization_id: str, days: int = 14) -> SalesTrendResponse:
    """Daily revenue for the chart."""
    days = max(1, min(int(days or 14), MAX_TREND_DAYS))
    with DashboardRepository() as repo:
        rows = repo.sales_by_day(organization_id, days)
    return SalesTrendResponse(days=[SalesTrendPoint(**row) for row in rows])


def get_stations(organization_id: str,
                 session_id: Optional[str] = None) -> StationsResponse:
    """Who is on a till right now, and their takings on it."""
    with DashboardRepository() as repo:
        rows = repo.active_stations(organization_id, session_id)

    stations = [StationItem(**row) for row in rows]
    return StationsResponse(
        stations=stations,
        active_sessions=len({s.session_id for s in stations}),
    )


def get_dashboard_data(
    organization_id: str,
    user_id: str,
    session_id: Optional[str] = None,
) -> DashboardDataResponse:
    """DEPRECATED — the old single-payload dashboard, composed from the panels.

    Kept for one release so a deployed client does not break the moment the
    panels ship; new callers should use the five panel endpoints, which each
    load and fail independently.

    It is composed rather than left as it was, so it now reports the
    organization's REAL totals instead of the zeros it returned whenever no
    cashier had a till open.
    """
    summary = get_sales_summary(organization_id)
    stations = get_stations(organization_id, session_id)
    products = get_top_products(organization_id, limit=10)

    return DashboardDataResponse(
        stands=[
            StandData(
                id=station.branch_id or station.assignment_id,
                name=station.session_name or "",
                # The old shape wanted a cashier NAME; only the id is available
                # here, and inventing a lookup for a deprecated payload is not
                # worth a join. The panel endpoint carries `user_id`.
                cashier_name=station.user_id or "",
                context=station.session_context,
                total_revenue=station.revenue,
                sales_count=station.orders,
                # Payment-method splits are not part of the panels: nothing read
                # them, and `payments` on an order is a JSON column that would
                # need its own aggregate to be meaningful.
                cash=0.0,
                sinpe=0.0,
                card=0.0,
                last_sync_at=int(station.last_order_at.timestamp() * 1000)
                if station.last_order_at else 0,
            )
            for station in stations.stations
        ],
        total_revenue=summary.revenue,
        total_sales=summary.orders,
        avg_ticket=summary.average_ticket,
        product_ranking=[
            ProductRanking(
                name=item.name,
                emoji=item.image_url,
                units=int(item.units),
                revenue=item.revenue,
            )
            for item in products.products
        ],
    )
