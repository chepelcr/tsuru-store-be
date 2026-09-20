"""80mm ticket rendering (TSR-127).

Generated server-side like the order's other documents, so a reprint is
identical to the original. These lock the parts a customer or an auditor
actually reads.
"""
from app.models.order import Order
from app.models.order_line import OrderLine
from app.services.ticket_service import (
    PAYMENT_LABELS,
    build_order_ticket_context,
    render_ticket_html,
)


def _order(**kw) -> Order:
    o = Order(
        company_id="org",
        document_number=kw.get("document_number", "PM-000001"),
        source=kw.get("source", "manual"),
        order_type=kw.get("order_type"),
        order_status=kw.get("order_status", "pending"),
        creation_date="2026-09-07",
        currency_code="CRC",
        subtotal=7000, discounts=0, taxes=910, grand_total=7910,
        payments=kw.get("payments"),
        comment=kw.get("comment"),
    )
    o.lines = kw.get("lines", [
        OrderLine(line_number=1, description="Café molido 500 g",
                  quantity_ordered=2, unit_price=3500, discount=0, line_total=7910)
    ])
    o.crossdocking_sale_points = []
    o.odometer = kw.get("odometer")
    o.document_info = {
        "consecutive_number": kw.get("consecutive"),
        "document_key": kw.get("key"),
    }
    return o


def test_heading_names_what_the_slip_is():
    assert build_order_ticket_context(_order())["heading"] == "PEDIDO"
    assert build_order_ticket_context(_order(order_status="quote"))["heading"] == "PROFORMA"
    assert build_order_ticket_context(_order(order_type="work_order"))["heading"] == "ORDEN DE TRABAJO"
    assert build_order_ticket_context(_order(source="import"))["heading"] == "ORDEN DE COMPRA"


def test_a_proforma_says_it_is_not_a_fiscal_document():
    """A slip that looks like a receipt invites being treated as one."""
    html = render_ticket_html(_order(order_status="quote"))
    assert "PROFORMA" in html
    assert "No es un comprobante fiscal" in html


def test_a_real_order_carries_no_such_disclaimer():
    assert "No es un comprobante fiscal" not in render_ticket_html(_order())


def test_change_is_computed_only_when_overpaid():
    paid = build_order_ticket_context(_order(payments=[{"type": "01", "amount": 8000}]))
    assert paid["change"] == 90.0

    exact = build_order_ticket_context(_order(payments=[{"type": "01", "amount": 7910}]))
    assert exact["change"] == 0.0

    unpaid = build_order_ticket_context(_order(payments=None))
    assert unpaid["change"] == 0.0


def test_payment_codes_become_readable_labels():
    ctx = build_order_ticket_context(_order(payments=[{"type": "06", "amount": 100}]))
    assert ctx["payments"][0]["label"] == PAYMENT_LABELS["06"] == "SINPE Móvil"


def test_free_text_other_payment_wins_over_the_code_label():
    ctx = build_order_ticket_context(
        _order(payments=[{"type": "99", "amount": 100, "other_type": "Vale interno"}])
    )
    assert ctx["payments"][0]["label"] == "Vale interno"


def test_hacienda_block_only_appears_once_invoiced():
    plain = render_ticket_html(_order())
    assert "Comprobante electrónico" not in plain

    billed = render_ticket_html(_order(consecutive="00100001010000000001", key="506..."))
    assert "Comprobante electrónico" in billed
    assert "00100001010000000001" in billed


def test_lines_and_totals_reach_the_slip():
    html = render_ticket_html(_order())
    assert "Café molido 500 g" in html
    assert "7,910.00" in html   # grand total, formatted
    assert "TOTAL" in html


def test_work_order_shows_the_asset_details():
    ctx = build_order_ticket_context(_order(order_type="work_order", odometer=123456))
    assert ctx["odometer"] == 123456
