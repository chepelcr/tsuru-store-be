"""The saved report palette must reach both order detail and list responses."""

import pytest

from app.mappers.orders_mapper import order_to_response, orders_to_list_response
from app.models.order import Order


@pytest.mark.parametrize("color", ["green", "orange", "blue", "green_alt", None])
def test_saved_report_color_survives_order_response_serialization(color):
    order = Order(
        order_id=1,
        company_id="org-1",
        document_number="PO-100",
        report_color=color,
    )

    detail = order_to_response(order).model_dump(mode="json")
    listing = orders_to_list_response([order], 1, 12, 1).model_dump(mode="json")

    assert detail["report_color"] == color
    assert listing["data"][0]["report_color"] == color
