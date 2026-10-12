"""Purchase-order and distribution PDFs share the configured supplier artwork."""

import base64
from unittest.mock import patch

import pytest

from app.mappers.orders_mapper import build_crossdocking_data
from app.models.order import Order
from app.models.organization import Organization
from app.services.pdf_service import (
    _document_logo_source,
    render_crossdocking_html,
    render_order_html,
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
