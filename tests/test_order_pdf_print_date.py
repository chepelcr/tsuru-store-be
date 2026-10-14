"""Printed dates follow Costa Rica's calendar, including UTC midnight."""
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app.models.order import Order
from app.services.pdf_service import (
    _document_print_date,
    create_crossdocking_pdf,
    create_order_pdf,
    render_order_html,
)


@pytest.mark.parametrize("instant,expected", [
    ("2026-10-13T00:30:00+00:00", "12/10/2026"),
    ("2026-10-13T05:59:59+00:00", "12/10/2026"),
    ("2026-10-13T06:00:00+00:00", "13/10/2026"),
    ("2027-01-01T02:00:00+00:00", "31/12/2026"),
])
def test_print_date_changes_at_costa_rica_midnight(instant, expected):
    assert _document_print_date(datetime.fromisoformat(instant)) == expected


@pytest.mark.parametrize("kind", ["purchase", "crossdocking"])
def test_both_order_documents_use_the_local_print_date(kind):
    order = Order(company_id="org", document_number="2900679500")
    instant = datetime(2026, 10, 13, 0, 30, tzinfo=timezone.utc)
    with patch("app.services.pdf_service.datetime") as clock, patch(
        "app.services.pdf_service.render_order_html", return_value="<html>order</html>",
    ), patch(
        "app.services.pdf_service.render_crossdocking_html", return_value="<html>distribution</html>",
    ), patch(
        "app.services.pdf_service.generate_pdf", return_value=b"current-pdf",
    ) as render_pdf, patch(
        "app.services.pdf_service.upload_file_to_s3", return_value="https://files.example/current.pdf",
    ):
        clock.now.return_value = instant
        if kind == "purchase":
            create_order_pdf(order)
        else:
            create_crossdocking_pdf(order, None, "blue")

    clock.now.assert_called_once_with(timezone.utc)
    assert render_pdf.call_args.kwargs["header_left"] == "12/10/2026"


@pytest.mark.parametrize('creation,delivery', [
    ('2026-09-21', '2026-10-12'),
    ('21/09/2026', '12/10/2026'),
    (date(2026, 9, 21), date(2026, 10, 12)),
])
def test_creation_and_delivery_dates_share_the_day_month_year_print_format(creation, delivery):
    html = render_order_html(Order(document_number='DATES', creation_date=creation, delivery_date=delivery))
    assert '21/09/2026' in html and '12/10/2026' in html
    assert '2026-09-21' not in html and '2026-10-12' not in html
