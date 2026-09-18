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
    ScopeInfo,
    SessionSalesResponse,
    StationItem,
    StationsResponse,
    TopProductItem,
    TopProductsResponse,
)
from app.repositories.dashboard_repository import (
    DEFAULT_GRANULARITY,
    DashboardRepository,
)
from app.services.dashboard_scope import DashboardScope, resolve as resolve_scope

logger = logging.getLogger(__name__)

MAX_TOP_PRODUCTS = 50
MAX_TREND_DAYS = 90


def _scope_info(scope: DashboardScope) -> ScopeInfo:
    """Echo the scope the server actually applied, not the one requested."""
    return ScopeInfo(
        scope=scope.describe(),
        session_id=scope.session_id,
        user_id=scope.user_id,
        is_admin=scope.is_admin,
    )


def get_sales_summary(
    organization_id: str,
    caller_user_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> SalesSummaryResponse:
    """Revenue, order count and average ticket, from the orders themselves."""
    scope = resolve_scope(organization_id, caller_user_id, session_id, user_id)
    with DashboardRepository() as repo:
        data = repo.sales_summary(organization_id, date_from, date_to, scope=scope)
    return SalesSummaryResponse(**data, scope=_scope_info(scope))


def get_order_status(
    organization_id: str,
    caller_user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> OrderStatusResponse:
    """Order counts per status, with the in-flight totals rolled up."""
    scope = resolve_scope(organization_id, caller_user_id, session_id, user_id)
    with DashboardRepository() as repo:
        rows = repo.order_status_breakdown(organization_id, scope=scope)

    statuses = [OrderStatusCount(**row) for row in rows]
    return OrderStatusResponse(
        statuses=statuses,
        open_orders=sum(s.orders for s in statuses if s.is_open),
        open_value=sum(s.value for s in statuses if s.is_open),
        scope=_scope_info(scope),
    )


def get_top_products(
    organization_id: str,
    caller_user_id: Optional[str] = None,
    limit: int = 10,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> TopProductsResponse:
    """Best sellers by revenue. `limit` is clamped, not trusted."""
    limit = max(1, min(int(limit or 10), MAX_TOP_PRODUCTS))
    scope = resolve_scope(organization_id, caller_user_id, session_id, user_id)
    with DashboardRepository() as repo:
        rows = repo.top_products(organization_id, limit, scope=scope)
    return TopProductsResponse(
        products=[TopProductItem(**row) for row in rows],
        scope=_scope_info(scope),
    )


def get_sales_trend(
    organization_id: str,
    caller_user_id: Optional[str] = None,
    granularity: str = DEFAULT_GRANULARITY,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> SalesTrendResponse:
    """Revenue per bucket for the chart, at the requested granularity."""
    scope = resolve_scope(organization_id, caller_user_id, session_id, user_id)
    with DashboardRepository() as repo:
        rows = repo.sales_trend(
            organization_id, granularity, date_from, date_to, scope=scope)
    return SalesTrendResponse(
        granularity=granularity,
        date_from=date_from,
        date_to=date_to,
        points=[SalesTrendPoint(**row) for row in rows],
        scope=_scope_info(scope),
    )


def get_session_sales(
    organization_id: str,
    caller_user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> SessionSalesResponse:
    """"Ventas de la sesión" — pending/processing/shipped, plus today's deliveries."""
    scope = resolve_scope(organization_id, caller_user_id, session_id, user_id)
    with DashboardRepository() as repo:
        data = repo.session_sales(organization_id, scope=scope)
    return SessionSalesResponse(**data, scope=_scope_info(scope))


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
    # The caller is passed through so the deprecated payload obeys the same
    # scope rules as the panels — a non-admin must not get wider figures by
    # calling the old endpoint instead of the new ones.
    summary = get_sales_summary(organization_id, user_id)
    stations = get_stations(organization_id, session_id)
    products = get_top_products(organization_id, user_id, limit=10)

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
