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

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.enums.order_status import OrderStatus
from app.repositories.dashboard_repository import (
    EXCLUDED_STATUSES,
    GRANULARITIES,
    OPEN_STATUSES,
    REVENUE_STATUSES,
)
from app.services import dashboard_service


def _role_stub(is_admin: bool) -> SimpleNamespace:
    """Stand in for the role repository inside `dashboard_scope` only.

    Rebinding the NAME in `dashboard_scope` rather than setting an attribute on
    the shared module matters: mutating the module would also replace
    `caller_role_repository.is_admin` for the tests below that exercise the real
    one, and they would silently assert against the stub.
    """
    return SimpleNamespace(is_admin=lambda organization_id, user_id: is_admin)


@pytest.fixture(autouse=True)
def _admin(monkeypatch):
    """Default the caller to an admin so scope-agnostic tests stay readable.

    The enforcement tests below override it.
    """
    from app.repositories import caller_role_repository

    caller_role_repository.clear_cache()
    monkeypatch.setattr(
        "app.services.dashboard_scope.caller_role_repository", _role_stub(True))


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
        dashboard_service.get_sales_summary(
            "org-1", "admin-1", date_from="2026-09-01", date_to="2026-09-30")
        args, kwargs = repo.sales_summary.call_args
        assert args[:3] == ("org-1", "2026-09-01", "2026-09-30")
        assert kwargs["scope"].organization_id == "org-1"

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
        dashboard_service.get_top_products("org-1", "admin-1", limit=asked)
        assert repo.top_products.call_args[0][1] == expected


class TestSalesTrend:
    def test_maps_buckets_and_echoes_the_window(self, repo):
        repo.sales_trend.return_value = [
            {"bucket": "2026-09-01T00:00:00", "orders": 2, "revenue": 170128.28},
        ]
        result = dashboard_service.get_sales_trend(
            "org-1", "admin-1", granularity="day",
            date_from="2026-09-01", date_to="2026-09-30")

        assert result.points[0].bucket == "2026-09-01T00:00:00"
        # The response states what it is, so a chart cannot mislabel its axis.
        assert result.granularity == "day"
        assert (result.date_from, result.date_to) == ("2026-09-01", "2026-09-30")

    @pytest.mark.parametrize("granularity", list(GRANULARITIES))
    def test_every_granularity_reaches_the_repository(self, repo, granularity):
        repo.sales_trend.return_value = []
        dashboard_service.get_sales_trend("org-1", "admin-1", granularity=granularity)
        assert repo.sales_trend.call_args[0][1] == granularity

    def test_granularity_is_whitelisted_at_the_repository(self):
        """The real guard lives in SQL-building, not in the route.

        `date_trunc`'s first argument cannot be a bind parameter, so it is
        interpolated — an unvalidated value there is injection. The repository
        raises rather than formatting whatever it was handed.
        """
        from app.repositories.dashboard_repository import DashboardRepository

        with pytest.raises(ValueError, match="granularity must be one of"):
            DashboardRepository.sales_trend(
                MagicMock(), "org-1", "day'; DROP TABLE crossdocking_orders--")


class TestScopeEnforcement:
    """A non-admin must not be able to widen their view by asking.

    This is the test the feature exists for: the frontend already sends the right
    filters, but anyone can call the endpoint directly, so a restriction applied
    only in the client is decoration.
    """

    @pytest.fixture
    def cashier(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.dashboard_scope.caller_role_repository", _role_stub(False))

    def test_cashier_asking_for_another_user_gets_themselves(self, repo, cashier):
        repo.sales_summary.return_value = _summary()
        result = dashboard_service.get_sales_summary(
            "org-1", "cashier-1", session_id="s-1", user_id="somebody-else")

        scope = repo.sales_summary.call_args[1]["scope"]
        assert scope.user_id == "cashier-1"       # not "somebody-else"
        assert scope.session_id == "s-1"          # the session itself is allowed
        assert result.scope.scope == "session_user"
        assert result.scope.is_admin is False

    def test_cashier_asking_for_a_whole_session_is_narrowed(self, repo, cashier):
        repo.order_status_breakdown.return_value = []
        dashboard_service.get_order_status("org-1", "cashier-1", session_id="s-1")

        scope = repo.order_status_breakdown.call_args[1]["scope"]
        assert scope.user_id == "cashier-1"

    def test_cashier_without_a_session_still_sees_only_their_own(self, repo, cashier):
        """"What have I sold" is the honest answer when not in a session."""
        repo.sales_summary.return_value = _summary()
        dashboard_service.get_sales_summary("org-1", "cashier-1")
        assert repo.sales_summary.call_args[1]["scope"].user_id == "cashier-1"

    def test_admin_may_see_the_whole_session(self, repo):
        repo.sales_summary.return_value = _summary()
        result = dashboard_service.get_sales_summary("org-1", "admin-1", session_id="s-1")

        scope = repo.sales_summary.call_args[1]["scope"]
        assert scope.user_id is None
        assert result.scope.scope == "session"

    def test_admin_may_look_at_one_person(self, repo):
        """A legitimate question about their own staff."""
        repo.sales_summary.return_value = _summary()
        dashboard_service.get_sales_summary(
            "org-1", "admin-1", session_id="s-1", user_id="cashier-2")
        assert repo.sales_summary.call_args[1]["scope"].user_id == "cashier-2"

    def test_an_unresolvable_role_fails_closed(self, monkeypatch):
        """A lookup failure must narrow the view, never widen it.

        Asserted on the role repository itself rather than through the service:
        this is the decision point, and defaulting to admin when the check breaks
        would turn a database blip into a data leak.
        """
        from app.repositories import caller_role_repository

        caller_role_repository.clear_cache()
        monkeypatch.setattr(
            caller_role_repository, "_lookup",
            lambda organization_id, user_id: (_ for _ in ()).throw(RuntimeError("db down")),
        )
        assert caller_role_repository.is_admin("org-1", "someone") is False

    def test_a_failed_lookup_is_not_cached(self, monkeypatch):
        """A transient failure must not pin the caller to non-admin for 5 minutes."""
        from app.repositories import caller_role_repository

        caller_role_repository.clear_cache()
        calls = {"n": 0}

        def flaky(organization_id, user_id):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db down")
            return True

        monkeypatch.setattr(caller_role_repository, "_lookup", flaky)
        assert caller_role_repository.is_admin("org-1", "someone") is False
        assert caller_role_repository.is_admin("org-1", "someone") is True
        assert calls["n"] == 2

    def test_a_resolved_role_is_cached(self, monkeypatch):
        from app.repositories import caller_role_repository

        caller_role_repository.clear_cache()
        calls = {"n": 0}

        def counted(organization_id, user_id):
            calls["n"] += 1
            return True

        monkeypatch.setattr(caller_role_repository, "_lookup", counted)
        caller_role_repository.is_admin("org-1", "someone")
        caller_role_repository.is_admin("org-1", "someone")
        assert calls["n"] == 1


class TestSessionSales:
    """Pending/processing/shipped, plus deliveries from today only."""

    def test_reports_the_rule_it_used(self, repo):
        repo.session_sales.return_value = {
            "orders": 4, "revenue": 373069.5,
            "average_ticket": 93267.375, "delivered_rule": "delivery_date_today",
        }
        result = dashboard_service.get_session_sales("org-1", "admin-1")
        assert result.orders == 4
        # The real rule now that `delivery_date` is a date column (migration
        # d3e4f5a6b7c8). It read `created_today` while the column was a
        # two-format string that could not be compared to today without
        # misreading the month.
        assert result.delivered_rule == "delivery_date_today"


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
