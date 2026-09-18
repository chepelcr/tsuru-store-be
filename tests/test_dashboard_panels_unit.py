"""Unit tests for the dashboard panels.

These replace `test_dashboard_service_unit.py` and
`test_dashboard_repository_unit.py`, which pinned the design this change
removed — including a case asserting that the whole dashboard correctly returns
zeros when no cashier session is open. That was the reported bug: an
organization with 45 orders showed 0 orders and a 0 average ticket, because
sales were only ever counted through active session -> active assignment.

So the first test here is the inverse of the one that was deleted: sales figures
must survive having nobody on a till.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.enums.order_status import OrderStatus
from app.repositories.dashboard_repository import (
    EXCLUDED_STATUSES,
    OPEN_STATUSES,
    REVENUE_STATUSES,
)
from app.services import dashboard_service


@pytest.fixture
def repo():
    """The repository, mocked at its context-manager boundary."""
    with patch("app.services.dashboard_service.DashboardRepository") as repo_class:
        instance = MagicMock()
        repo_class.return_value.__enter__.return_value = instance
        yield instance


def _summary(**over):
    base = {"orders": 33, "revenue": 2553498.17, "average_ticket": 77378.73,
            "units": 529.0, "last_order_at": None}
    base.update(over)
    return base


class TestStatusBuckets:
    """The guard that the hand-written version of these sets needed and lacked.

    The first implementation spelled the statuses out as literals and invented
    five that do not exist, while omitting `shipped` — which is real. A shipped
    order was in neither bucket, so it disappeared from the dashboard, and no
    test noticed because dev had no shipped orders.
    """

    def test_every_status_is_classified_exactly_once(self):
        """A status added to the enum must fail this until someone places it."""
        revenue, open_, excluded = set(REVENUE_STATUSES), set(OPEN_STATUSES), set(EXCLUDED_STATUSES)
        all_statuses = {status.value for status in OrderStatus}

        unclassified = all_statuses - (revenue | open_ | excluded)
        assert not unclassified, f"statuses in no bucket: {sorted(unclassified)}"

        invented = (revenue | open_ | excluded) - all_statuses
        assert not invented, f"not OrderStatus values: {sorted(invented)}"

        # Excluded is exclusive of the other two; revenue and open deliberately
        # overlap on `shipped`.
        assert not excluded & (revenue | open_)

    def test_shipped_counts_as_both(self):
        """The regression itself: shipped is revenue AND still in flight."""
        assert OrderStatus.SHIPPED.value in REVENUE_STATUSES
        assert OrderStatus.SHIPPED.value in OPEN_STATUSES

    def test_quote_and_cancelled_are_neither(self):
        assert OrderStatus.QUOTE.value not in REVENUE_STATUSES + OPEN_STATUSES
        assert OrderStatus.CANCELLED.value not in REVENUE_STATUSES + OPEN_STATUSES


class TestSalesSummary:
    def test_reports_sales_with_no_open_session(self, repo):
        """THE regression. Revenue is a property of the orders, not of who is working."""
        repo.sales_summary.return_value = _summary()
        repo.active_stations.return_value = []

        result = dashboard_service.get_sales_summary("org-1")

        assert result.orders == 33
        assert result.revenue == pytest.approx(2553498.17)
        assert result.average_ticket == pytest.approx(77378.73)
        # Nothing in this path consults sessions or assignments at all.
        repo.active_stations.assert_not_called()

    def test_zero_orders_does_not_divide(self, repo):
        repo.sales_summary.return_value = _summary(
            orders=0, revenue=0.0, average_ticket=0.0, units=0.0)
        result = dashboard_service.get_sales_summary("org-1")
        assert result.orders == 0
        assert result.average_ticket == 0.0

    def test_passes_the_date_window_through(self, repo):
        repo.sales_summary.return_value = _summary()
        dashboard_service.get_sales_summary("org-1", "2026-09-01", "2026-09-30")
        repo.sales_summary.assert_called_once_with("org-1", "2026-09-01", "2026-09-30")

    def test_cancelled_is_not_revenue(self):
        """A cancelled order is not income and must not enter the average ticket."""
        assert "cancelled" not in REVENUE_STATUSES
        assert "delivered" in REVENUE_STATUSES


class TestOrderStatus:
    def test_rolls_up_the_in_flight_orders(self, repo):
        repo.order_status_breakdown.return_value = [
            {"status": "delivered", "orders": 33, "value": 2553498.17, "is_open": False},
            {"status": "cancelled", "orders": 8, "value": 588684.8, "is_open": False},
            {"status": "processing", "orders": 4, "value": 373069.5, "is_open": True},
        ]
        result = dashboard_service.get_order_status("org-1")

        assert len(result.statuses) == 3
        # Only the open ones, which is what the operator acts on.
        assert result.open_orders == 4
        assert result.open_value == pytest.approx(373069.5)

    def test_no_orders_reports_nothing_open(self, repo):
        repo.order_status_breakdown.return_value = []
        result = dashboard_service.get_order_status("org-1")
        assert result.statuses == []
        assert result.open_orders == 0

    def test_processing_counts_as_open(self):
        assert "processing" in OPEN_STATUSES
        assert "delivered" not in OPEN_STATUSES


class TestTopProducts:
    def test_maps_rows(self, repo):
        repo.top_products.return_value = [{
            "product_id": "p-1", "name": "ALMOHADA", "image_url": "",
            "units": 296.0, "revenue": 731663.28,
        }]
        result = dashboard_service.get_top_products("org-1")
        assert result.products[0].name == "ALMOHADA"
        assert result.products[0].revenue == pytest.approx(731663.28)

    # 0 means "unspecified" and falls back to the default; the route's `ge=1`
    # rejects it before this anyway. A negative clamps to 1, a huge one to 50.
    @pytest.mark.parametrize("asked,expected", [(0, 10), (-5, 1), (10, 10), (999, 50)])
    def test_clamps_the_limit(self, repo, asked, expected):
        """A client-supplied limit is clamped, not trusted."""
        repo.top_products.return_value = []
        dashboard_service.get_top_products("org-1", asked)
        assert repo.top_products.call_args[0][1] == expected


class TestSalesTrend:
    def test_maps_days(self, repo):
        repo.sales_by_day.return_value = [
            {"day": "2026-09-01", "orders": 2, "revenue": 170128.28},
        ]
        result = dashboard_service.get_sales_trend("org-1")
        assert result.days[0].day == "2026-09-01"

    @pytest.mark.parametrize("asked,expected", [(0, 14), (-1, 1), (14, 14), (365, 90)])
    def test_clamps_the_window(self, repo, asked, expected):
        repo.sales_by_day.return_value = []
        dashboard_service.get_sales_trend("org-1", asked)
        assert repo.sales_by_day.call_args[0][1] == expected


class TestStations:
    def test_counts_distinct_sessions(self, repo):
        repo.active_stations.return_value = [
            {"assignment_id": "a-1", "branch_id": "b-1", "user_id": "u-1",
             "session_id": "s-1", "session_name": "Caja 1", "session_context": "caja",
             "started_at": None, "orders": 3, "revenue": 1000.0, "last_order_at": None},
            {"assignment_id": "a-2", "branch_id": "b-2", "user_id": "u-2",
             "session_id": "s-1", "session_name": "Caja 1", "session_context": "caja",
             "started_at": None, "orders": 1, "revenue": 500.0, "last_order_at": None},
        ]
        result = dashboard_service.get_stations("org-1")
        assert len(result.stations) == 2
        # Two tills, one session between them.
        assert result.active_sessions == 1

    def test_nobody_working_is_an_empty_list(self, repo):
        repo.active_stations.return_value = []
        result = dashboard_service.get_stations("org-1")
        assert result.stations == []
        assert result.active_sessions == 0


class TestDeprecatedComposition:
    def test_reports_real_totals_with_no_station(self, repo):
        """The legacy payload is composed now, so it stopped returning zeros too."""
        repo.sales_summary.return_value = _summary()
        repo.active_stations.return_value = []
        repo.top_products.return_value = []

        result = dashboard_service.get_dashboard_data("org-1", "user-1")

        assert result.total_sales == 33
        assert result.total_revenue == pytest.approx(2553498.17)
        assert result.avg_ticket == pytest.approx(77378.73)
        assert result.stands == []
