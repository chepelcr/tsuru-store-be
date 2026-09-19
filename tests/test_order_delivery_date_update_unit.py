"""Editing an order's delivery date.

Before this, the only way to change a delivery date was to delete the order and
re-upload its spreadsheet — the PATCH endpoint accepted `{status: int}` and
nothing else. Two things make the edit safe rather than merely possible:

1. **The guards.** Moving a delivery date changes a commitment to the customer,
   unlike a status change, which records what already happened. So it is allowed
   only while the order is `pending` or `processing` — still being prepared — and
   is not billed, and the new date is not past.

2. **The spreadsheet rewrite.** `reprocess_order` re-parses the stored Excel and
   `_update_order_from_parsed` assigns `delivery_date` from it, so a
   database-only change is reverted the next time anyone reprocesses — and
   Reprocess is an item in the order's own menu in the POS. That is the test at
   the bottom of this file.

Run: `python -m pytest tests/test_order_delivery_date_update_unit.py -q`
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.enums.order_status import OrderStatus
from app.services.order_service import (
    DELIVERY_DATE_EDITABLE_STATUSES,
    _assert_delivery_date_editable,
    update_order,
)

TOMORROW = date.today() + timedelta(days=1)
YESTERDAY = date.today() - timedelta(days=1)


def order(**overrides):
    """A pending, unbilled order — the only state the date may be changed in."""
    stub = MagicMock()
    stub.document_number = "4500123456"
    stub.order_status = OrderStatus.PENDING.value
    stub.invoice_sale_id = None
    stub.invoice_consecutive_number = None
    stub.excel_url = "https://files.example/4500123456-DT.xlsx"
    stub.crossdocking_excel_url = None
    for key, value in overrides.items():
        setattr(stub, key, value)
    return stub


class TestTheGuards:
    @pytest.mark.parametrize("status", list(DELIVERY_DATE_EDITABLE_STATUSES))
    def test_an_unbilled_order_still_being_prepared_may_move_its_date(self, status):
        _assert_delivery_date_editable(order(order_status=status), TOMORROW)

    def test_today_is_allowed(self):
        """"Not in the past" means not before today, not "after today"."""
        _assert_delivery_date_editable(order(), date.today())

    @pytest.mark.parametrize("status", [
        # Shipped: the date has been acted on and the customer has been told.
        OrderStatus.SHIPPED.value,
        OrderStatus.DELIVERED.value,
        OrderStatus.CANCELLED.value,
        # A quote is not a placed order yet.
        OrderStatus.QUOTE.value,
    ])
    def test_an_order_past_preparation_may_not_move(self, status):
        with pytest.raises(ValueError, match="only be changed while"):
            _assert_delivery_date_editable(order(order_status=status), TOMORROW)

    def test_a_billed_order_refuses(self):
        """The date is on the fiscal document; changing it here would diverge."""
        with pytest.raises(ValueError, match="has been billed"):
            _assert_delivery_date_editable(
                order(invoice_sale_id="sale-1",
                      invoice_consecutive_number="00100001010000000123"),
                TOMORROW,
            )

    def test_the_error_names_the_document_that_blocks_it(self):
        with pytest.raises(ValueError, match="00100001010000000123"):
            _assert_delivery_date_editable(
                order(invoice_sale_id="sale-1",
                      invoice_consecutive_number="00100001010000000123"),
                TOMORROW,
            )

    def test_a_past_date_refuses(self):
        # Same rule `_validate_order_dates` applies when a confirmation is built,
        # so the two cannot disagree about what a valid date is.
        with pytest.raises(ValueError, match="in the past"):
            _assert_delivery_date_editable(order(), YESTERDAY)


class TestUpdateOrder:
    @pytest.fixture
    def repo(self):
        with patch("app.services.order_service.OrderRepository") as repo_class:
            instance = MagicMock()
            repo_class.return_value.__enter__.return_value = instance
            yield instance

    @pytest.fixture
    def rewrite(self):
        with patch("app.services.order_service.rewrite_delivery_date") as spy:
            yield spy

    @pytest.fixture(autouse=True)
    def _response(self):
        with patch("app.services.order_service.order_to_response",
                   side_effect=lambda o: o):
            yield

    def test_rewrites_the_spreadsheets(self, repo, rewrite):
        """THE test. Without this the next reprocess silently undoes the edit."""
        existing = order()
        repo.find_by_company_and_document.return_value = existing
        repo.save.return_value = existing

        update_order("org-1", "4500123456", delivery_date=TOMORROW)

        assert existing.delivery_date == TOMORROW
        rewrite.assert_called_once_with(existing, TOMORROW)

    def test_does_not_touch_the_spreadsheets_for_a_status_change(self, repo, rewrite):
        existing = order()
        repo.find_by_company_and_document.return_value = existing
        repo.save.return_value = existing

        update_order("org-1", "4500123456", status_code=2)

        assert existing.order_status == OrderStatus.PROCESSING.value
        rewrite.assert_not_called()

    def test_a_refused_date_is_not_saved(self, repo, rewrite):
        existing = order(invoice_sale_id="sale-1")
        repo.find_by_company_and_document.return_value = existing

        with pytest.raises(ValueError, match="has been billed"):
            update_order("org-1", "4500123456", delivery_date=TOMORROW)

        repo.save.assert_not_called()
        rewrite.assert_not_called()

    def test_every_editable_status_is_a_real_one(self):
        """Guards against the invented-status mistake made once already today."""
        assert set(DELIVERY_DATE_EDITABLE_STATUSES) <= {s.value for s in OrderStatus}

    def test_an_illegal_status_transition_is_refused(self, repo):
        existing = order(order_status=OrderStatus.DELIVERED.value)
        repo.find_by_company_and_document.return_value = existing

        with pytest.raises(ValueError, match="Cannot move order"):
            update_order("org-1", "4500123456", status_code=2)
        repo.save.assert_not_called()

    def test_a_missing_order_is_a_lookup_error(self, repo):
        repo.find_by_company_and_document.return_value = None
        with pytest.raises(LookupError):
            update_order("org-1", "nope", status_code=2)

    def test_both_fields_apply_in_one_transaction(self, repo, rewrite):
        existing = order()
        repo.find_by_company_and_document.return_value = existing
        repo.save.return_value = existing

        # pending -> processing is legal, and the date is set while still pending.
        update_order("org-1", "4500123456", status_code=2, delivery_date=TOMORROW)

        assert existing.delivery_date == TOMORROW
        assert existing.order_status == OrderStatus.PROCESSING.value
        assert repo.save.call_count == 1
