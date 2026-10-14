"""Purchase-order and distribution PDFs share the configured supplier artwork."""

import base64
import re
from html import unescape
from unittest.mock import patch

import pytest

from app.mappers.orders_mapper import build_crossdocking_data
from app.models.order import Order
from app.models.organization import Organization
from app.models.order_line import OrderLine
from app.models.product import Product
from app.services.pdf_service import (
    _document_logo_source,
    render_crossdocking_html,
    render_order_html,
    render_order_footer_html,
    generate_pdf,
)


CDN = "https://uploads.example.test"
LOGO_URL = f"{CDN}/organizations/org/branding/logo.png"
LOGO_BYTES = b"supplier-logo-bytes"


@pytest.mark.parametrize("kind", ["purchase", "crossdocking"])
def test_order_documents_embed_the_organization_logo(kind):
    order = Order(company_id="org", document_number="PO-100")
    order.organization = Organization(
        id="org", name="Supplier & Company", slug="supplier", owner_id="owner",
        logo_url=LOGO_URL,
    )

    with patch("app.services.pdf_service.AppConfig.get_key", return_value=CDN), patch(
        "app.services.pdf_service.download_from_s3", return_value=LOGO_BYTES,
    ) as download:
        html = (
            render_order_html(order) if kind == "purchase"
            else render_crossdocking_html(order, build_crossdocking_data(order), "blue")
        )

    expected = "data:image/png;base64," + base64.b64encode(LOGO_BYTES).decode("ascii")
    assert f'src="{expected}"' in html
    assert 'class="supplier-logo"' in html
    assert 'alt="Supplier &amp; Company"' in html
    assert "width:80px; height:80px" not in html
    download.assert_called_once_with(LOGO_URL)


@pytest.mark.parametrize("logo_url", [None, "", "https://external.example/logo.png", CDN + ".external.example/logo.png"])
def test_absent_or_external_logos_do_not_trigger_s3_downloads(logo_url):
    with patch("app.services.pdf_service.AppConfig.get_key", return_value=CDN), patch(
        "app.services.pdf_service.download_from_s3",
    ) as download:
        assert _document_logo_source(logo_url) == (logo_url or "")
    download.assert_not_called()


def test_logo_download_failure_keeps_the_existing_url_fallback():
    with patch("app.services.pdf_service.AppConfig.get_key", return_value=CDN), patch(
        "app.services.pdf_service.download_from_s3", side_effect=RuntimeError("unavailable"),
    ):
        assert _document_logo_source(LOGO_URL) == LOGO_URL


def _rendered_item_rows(html):
    body = re.search(r"<tbody>(.*?)</tbody>", html, re.S).group(1)
    return [
        [unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)]
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S)
    ]


def test_pdf_preserves_order_line_codes_descriptions_and_discount_amounts():
    order = Order(document_number="2900679464", discounts=835, subtotal=26356, taxes=3317.73, grand_total=28838.73)
    product = Product(name="Catalog product", description="Changed catalog text", codes=[
        {"code_type_id": "04", "number": "different-item"},
        {"code_type_id": "03", "number": "different-barcode"},
    ])
    first = OrderLine(
        line_number=1, description="Order article & description", quantity_ordered=4,
        units_ordered=12, unit_price=4333, discount=549.11, tax=2181.78,
        line_total=18964.67, codes=[
            {"code_type_id": "04", "number": "2645516"},
            {"code_type_id": "03", "number": "7441119600652"},
        ],
    )
    first.product = product
    second = OrderLine(
        line_number=2, description="Manual article", quantity_ordered=4,
        units_ordered=12, unit_price=2256, discount=285.89, tax=1135.95,
        line_total=9874.06,
    )
    order.lines = [first, second]

    html = render_order_html(order)
    rows = _rendered_item_rows(html)

    assert rows == [
        ["2645516", "Order article & description", "4", "12", "₡4,333.00", "₡549.11", "₡2,181.78", "₡18,964.67"],
        ["", "Manual article", "4", "12", "₡2,256.00", "₡285.89", "₡1,135.95", "₡9,874.06"],
    ]
    assert '>₡835.00</td>' in html
    assert re.search(r'>Impuesto</td><td[^>]*>₡3,317\.73</td>', html)
    assert '>₡28,838.73</td>' in html
    assert "different-item" not in html and "Changed catalog text" not in html
    assert "7441119600652" not in html and "different-barcode" not in html
    # Rendering changes neither the amounts nor the order's own article data.
    assert first.discount == 549.11 and second.discount == 285.89 and order.discounts == 835


def test_legacy_order_line_keeps_catalog_fallback_and_zero_discount():
    line = OrderLine(quantity_ordered=1, units_ordered=1, unit_price=100, discount=0, tax=13, line_total=113)
    line.product = Product(name="Legacy product", description="Legacy article", codes=[
        {"code_type_id": "04", "number": "legacy-item"},
        {"code_type_id": "03", "number": "legacy-barcode"},
    ])
    order = Order(document_number="LEGACY", discounts=0)
    order.lines = [line]

    rows = _rendered_item_rows(render_order_html(order))

    assert rows == [["legacy-item", "Legacy article", "1", "1", "₡100.00", "₡0.00", "₡13.00", "₡113.00"]]
    assert "legacy-barcode" not in render_order_html(order)


def test_order_pdf_uses_the_actual_currency_for_non_colon_orders():
    line = OrderLine(description="Dollar article", quantity_ordered=1, units_ordered=1, unit_price=100, discount=5, tax=0, line_total=95)
    order = Order(document_number="USD-ORDER", currency_code="USD", discounts=5, subtotal=100, grand_total=95)
    order.lines = [line]

    html = render_order_html(order)

    assert _rendered_item_rows(html)[0][-4:] == ["$100.00", "$5.00", "$0.00", "$95.00"]
    assert '>$95.00</td>' in html
    assert "₡" not in html


def test_order_pdf_shows_the_full_totals_in_order_including_zero_tax():
    order = Order(document_number="TOTALS", subtotal=100, discounts=100, net_total=0, taxes=0, grand_total=0)
    html = render_order_html(order)
    labels = [html.index(f'>{label}</td>') for label in ['Subtotal', 'Descuento', 'Total neto', 'Impuesto', 'Total']]
    assert labels == sorted(labels)
    assert re.search(r'>Total neto</td><td[^>]*>₡0\.00</td>', html)
    assert re.search(r'>Impuesto</td><td[^>]*>₡0\.00</td>', html)


def test_order_footer_is_branded_escaped_and_contains_no_invoice_legal_claim():
    html = render_order_footer_html(Order(document_number='A&B<1>'))
    assert 'A&amp;B&lt;1&gt;' in html
    assert 'alt="Tsuru"' in html and 'data:image/png;base64,' in html
    assert 'class="page"' in html and 'class="topage"' in html
    assert '@font-face' not in html
    assert 'Factura Electrónica' not in html


def test_order_footer_reserves_space_and_cleans_up_its_temporary_file():
    from pathlib import Path

    captured = {}

    def render(html, output, *, options, configuration):
        captured.update(options)
        assert Path(options['footer-html']).read_text() == '<html>footer</html>'
        assert options['margin-bottom'] == '18'
        assert options['footer-spacing'] == '3'
        assert 'header-left' not in options and 'header-center' not in options
        return b'%PDF-test'

    with patch('app.services.pdf_service.pdfkit.configuration'), patch(
        'app.services.pdf_service.pdfkit.from_string', side_effect=render,
    ):
        assert generate_pdf('<html>body</html>', footer_html='<html>footer</html>') == b'%PDF-test'
    assert not Path(captured['footer-html']).exists()
