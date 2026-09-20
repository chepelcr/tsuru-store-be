from __future__ import annotations

import base64
import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.utils.order_dates import as_display
from app.configuration.app_config import AppConfig
from app.models.order import Order
from app.services.pdf_service import (
    _jinja_env,
    _s3_key,
    upload_file_to_s3,
)

logger = logging.getLogger(__name__)

#: Hacienda payment codes → the label a customer reads on the slip.
PAYMENT_LABELS: Dict[str, str] = {
    "01": "Efectivo",
    "02": "Tarjeta",
    "03": "Cheque",
    "04": "Transferencia",
    "05": "Recaudado por terceros",
    "06": "SINPE Móvil",
    "07": "Plataforma digital",
    "99": "Otros",
}

DEFAULT_FOOTER = "¡Gracias por su compra!"


def _ticket_pdf(html: str) -> bytes:
    """Render an 80mm ticket.

    Deliberately NOT `pdf_service.generate_pdf`: that one is Letter, portrait,
    with a page header and a "# [page]" footer — all wrong on a receipt roll.
    A ticket is one continuous slip of a fixed narrow width, so the page is
    sized to the paper and every header option is off.
    """
    import pdfkit

    wkhtmltopdf_path = AppConfig.get_key("path.to.wkhtmltopdf", "/usr/local/bin/wkhtmltopdf")
    config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)

    options = {
        "page-width": "72mm",
        # No page-height: the roll is continuous, so the slip is as long as it
        # needs to be. Fixing a height would pad short tickets with blank paper.
        "margin-top": "0",
        "margin-right": "0",
        "margin-bottom": "0",
        "margin-left": "0",
        "print-media-type": None,
        "enable-local-file-access": None,
        "encoding": "UTF-8",
        "no-outline": None,
        "disable-smart-shrinking": None,
    }
    return pdfkit.from_string(html, False, options=options, configuration=config)


def _qr_data_uri(payload: str) -> Optional[str]:
    """QR for the Hacienda document key, inlined as a data URI.

    Inlined rather than linked because wkhtmltopdf renders offline inside the
    Lambda — an external image URL would silently come out blank.
    """
    if not payload:
        return None
    try:
        import qrcode

        buf = io.BytesIO()
        qrcode.make(payload).save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # pragma: no cover - QR is a nicety, never a blocker
        logger.warning(f"QR generation failed: {e}")
        return None


def _heading_for(order: Order) -> str:
    """What this slip calls itself.

    A proforma must say so: it is not a fiscal document, and a slip that looks
    like a receipt invites it being treated as one.
    """
    if order.order_status == "quote":
        return "PROFORMA"
    if order.order_type == "work_order":
        return "ORDEN DE TRABAJO"
    if order.source == "manual":
        return "PEDIDO"
    return "ORDEN DE COMPRA"


def build_order_ticket_context(order: Order, **overrides: Any) -> Dict[str, Any]:
    """Flatten an order into the ticket template's inputs."""
    org = order.organization
    client = order.client

    lines: List[Dict[str, Any]] = []
    for ln in order.lines or []:
        product = ln.product
        lines.append(
            {
                "description": ln.description or (product.description if product else "") or "",
                "quantity": ln.quantity_ordered or 0,
                "unit_price": float(ln.unit_price or 0),
                "discount": float(ln.discount or 0),
                "line_total": float(ln.line_total or 0),
                "modifiers": None,
            }
        )

    payments = []
    for p in order.payments or []:
        code = str(p.get("type") or "")
        payments.append(
            {
                "label": p.get("other_type") or PAYMENT_LABELS.get(code, code),
                "amount": float(p.get("amount") or 0),
            }
        )

    paid = sum(p["amount"] for p in payments)
    grand_total = float(order.grand_total or 0)

    delivery_location = order.delivery_location_name or order.delivery_address
    if not delivery_location and order.deliver_to_store:
        store = order.deliver_to_store
        delivery_location = store.store_name or store.store_code

    asset_label = None
    if order.asset:
        a = order.asset
        asset_label = " ".join(x for x in [a.identifier, a.brand, a.model] if x)

    context = {
        "org_name": org.name if org else "",
        "org_id_number": getattr(org, "internal_code", None) if org else None,
        "logo_url": getattr(org, "logo_url", None) if org else None,
        "branch_name": None,
        "heading": _heading_for(order),
        "is_quote": order.order_status == "quote",
        "document_number": order.document_number,
        "issued_on": order.creation_date or datetime.now().strftime("%Y-%m-%d"),
        "cashier": order.created_by,
        "terminal": order.terminal_number,
        "client_name": (client.client_name if client else None) or order.customer_name,
        "table_name": None,
        "asset_label": asset_label,
        "odometer": order.odometer,
        "lines": lines,
        "subtotal": float(order.subtotal or 0),
        "discounts": float(order.discounts or 0),
        "service_charge": None,
        "taxes": float(order.taxes or 0),
        "grand_total": grand_total,
        "currency": order.currency_code or "CRC",
        "payments": payments,
        # Only meaningful when the customer actually overpaid in cash.
        "change": max(0.0, paid - grand_total) if payments else 0.0,
        "delivery_date": as_display(order.delivery_date),
        "delivery_location": delivery_location,
        "department": order.department_rel.name if order.department_rel else None,
        "comment": order.comment,
        # The document that billed this order, when one has. Written by the
        # order-link consumer (TSR-317), so a ticket printed before Hacienda
        # accepts simply has no consecutive and no QR — which is honest: there
        # is no accepted document to point a QR at yet.
        "consecutive_number": _document_info(order).get("consecutive_number"),
        "document_key": _document_info(order).get("document_key"),
        "qr_data_uri": _qr_data_uri(_document_info(order).get("document_key") or ""),
        "footer": DEFAULT_FOOTER,
    }
    context.update(overrides)
    return context


def _document_info(order: Order) -> dict:
    """The order's document snapshot, or an empty dict when it is not billed."""
    return order.document_info or {}


def render_ticket_html(order: Order, **overrides: Any) -> str:
    template = _jinja_env.get_template("ticket.html")
    return template.render(**build_order_ticket_context(order, **overrides))


def create_order_ticket(order: Order) -> str:
    """Render the order's 80mm ticket and store it beside its other documents.

    Same shape as `create_order_pdf`: HTML → wkhtmltopdf → S3 → URL. The ticket
    is a document FORMAT of the order, not a browser-side print view, so it is
    identical however it is opened and can be re-printed or emailed later.
    """
    html = render_ticket_html(order)
    pdf_bytes = _ticket_pdf(html)
    last4 = (order.document_number or "")[-4:]
    key = _s3_key(order.company_id, order.document_number, f"{last4}-TICKET.pdf")
    return upload_file_to_s3(pdf_bytes, key)
