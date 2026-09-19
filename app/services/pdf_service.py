import logging
import os
import uuid
from datetime import datetime

import boto3
import pdfkit
from jinja2 import Environment, FileSystemLoader

from app.utils.order_dates import as_display
from app.configuration.app_config import AppConfig
from app.enums.report_color import get_color_palette
from app.models.order import Order

logger = logging.getLogger(__name__)


def _format_currency(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


from app.utils.product_codes import find_code_number as _get_code_from_array  # noqa: E402


# Jinja2 setup
_template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
_jinja_env = Environment(
    loader=FileSystemLoader(_template_dir),
    autoescape=False,
)
_jinja_env.filters["format_currency"] = _format_currency


def render_order_html(order: Order) -> str:
    lines_data = order.lines or []
    total_units_ordered = sum(ln.units_ordered or 0 for ln in lines_data)
    subtotal = float(order.subtotal or 0)
    total_discounts = float(order.discounts or 0)
    net_total = float(order.net_total or 0)
    total_taxes = float(order.taxes or 0)
    grand_total = float(order.grand_total or 0)

    lines = []
    for ln in lines_data:
        p = ln.product
        # Extract codes from JSONB array
        internal_code = _get_code_from_array(p.codes if p else [], "04")
        code = _get_code_from_array(p.codes if p else [], "03")
        
        lines.append({
            "internal_code": internal_code,
            "code": code,
            "description": (p.description if p else "") or "",
            "quantity_ordered": ln.quantity_ordered or 0,
            "units_ordered": ln.units_ordered or 0,
            "unit_price": float(ln.unit_price or 0),
            "discount": float(ln.discount or 0),
            "tax": float(ln.tax or 0),
            "line_total": float(ln.line_total or 0),
        })

    # Use relationship data
    org = order.organization
    supplier_name = (org.name if org else "") or ""
    supplier_logo_url = (org.logo_url if org else "") or ""
    client_name = (order.client.client_name if order.client else "") or ""
    client_gln = (order.client.client_gln if order.client else "") or ""

    dept = order.department_rel
    dept_code = (dept.department_code if dept else "") or ""
    dept_name = (dept.name if dept else "") or ""
    # vendor number (NUM_VENDEDOR) lives on the department
    supplier_internal_code = (dept.supplier_code if dept else "") or ""
    department_value = f"{dept_code} - {dept_name}" if dept_code and dept_name else dept_code

    store = order.deliver_to_store
    if store:
        deliver_to = f"{store.store_code} - {store.store_name}"
        deliver_to_gln = store.gln or ""
        if deliver_to_gln:
            deliver_to += f" - {deliver_to_gln}"
    else:
        deliver_to = ""
        deliver_to_gln = ""

    template_model = {
        "supplier_name": supplier_name,
        "supplier_internal_code": supplier_internal_code,
        "supplier_logo_url": supplier_logo_url,
        "document_number": order.document_number or "",
        "creation_date_formatted": order.creation_date or "",
        # Formatted here, at the point of display: the column is a real date now.
        "delivery_date_formatted": as_display(order.delivery_date),
        "client_name": client_name,
        "client_gln": client_gln,
        "deliver_to": deliver_to,
        "deliver_to_gln": deliver_to_gln,
        "order_type": order.order_type or "",
        "comment": order.comment or "",
        "department": department_value,
        "lines": lines,
        "line_count": order.line_count or len(lines_data),
        "total_quantities": order.total_quantities or 0,
        "total_units_ordered": total_units_ordered,
        "subtotal": subtotal,
        "total_discounts": total_discounts,
        "net_total": net_total,
        "total_taxes": total_taxes,
        "grand_total": grand_total,
    }

    template = _jinja_env.get_template("order.html")
    return template.render(**template_model)


def generate_pdf(html: str, header_left: str = "", header_center: str = "") -> bytes:
    wkhtmltopdf_path = AppConfig.get_key("path.to.wkhtmltopdf", "/usr/local/bin/wkhtmltopdf")
    config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)

    options = {
        "orientation": "Portrait",
        "page-size": "Letter",
        "print-media-type": None,
        "enable-local-file-access": None,
        "header-left": header_left,
        "header-center": header_center,
        "header-right": "# [page]",
        "header-font-size": "8",
        "header-spacing": "5",
        "no-header-line": None,
        "margin-top": "12",
        "margin-right": "10",
        "margin-left": "10",
        "margin-bottom": "0",
        "encoding": "UTF-8",
        "no-outline": None,
    }
    pdf_bytes = pdfkit.from_string(html, False, options=options, configuration=config)
    return pdf_bytes


def _get_s3_session():
    region = AppConfig.get_key("aws.region", "us-east-1")
    return boto3.Session(
        profile_name=AppConfig.get_key("aws.profile"),
        region_name=region,
    ), region


def upload_file_to_s3(
    file_bytes: bytes,
    key: str,
    content_type: str = "application/pdf",
) -> str:
    bucket = AppConfig.get_key("s3.bucket")
    pdf_domain = (AppConfig.get_key("pdf.domain", "") or "").rstrip("/")

    if not bucket:
        raise ValueError("S3_BUCKET environment variable is not set")

    session, region = _get_s3_session()
    s3_client = session.client("s3")

    s3_client.put_object(
        Body=file_bytes,
        Bucket=bucket,
        Key=key,
        ContentType=content_type,
    )
    logger.info(f"Uploaded file to s3://{bucket}/{key}")

    distribution_id = AppConfig.get_key("cloudfront.distribution.id")
    try:
        cf_client = session.client("cloudfront")
        cf_client.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": [f"/{key}"]},
                "CallerReference": str(uuid.uuid4()),
            },
        )
        logger.info(f"CloudFront invalidation created for /{key}")
    except Exception as e:
        logger.warning(f"CloudFront invalidation failed: {e}")

    url = f"{pdf_domain}/{key}" if pdf_domain else f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    return url


def _s3_key(company_id: str, document_number: str, filename: str) -> str:
    return f"organizations/{company_id}/orders/{document_number}/{filename}"


def create_order_pdf(order: Order) -> str:
    html = render_order_html(order)
    pdf_bytes = generate_pdf(
        html,
        header_left=datetime.now().strftime("%d/%m/%Y"),
        header_center="Orden de Compra",
    )
    last4 = (order.document_number or "")[-4:]
    key = _s3_key(order.company_id, order.document_number, f"{last4}-OC.pdf")
    return upload_file_to_s3(pdf_bytes, key)


def render_crossdocking_html(order: Order, crossdocking_data, color=None) -> str:
    """Render the crossdocking distribution PDF template."""
    sale_points = crossdocking_data.sale_points
    item_summary = crossdocking_data.item_summary
    box_summary = crossdocking_data.box_summary
    totals = crossdocking_data.totals

    # Build labels: one label per sale point
    all_labels = []
    for idx, sp in enumerate(sale_points, start=1):
        all_labels.append({"sp": sp, "box_num": idx})
    total_boxes_all = len(all_labels)


    # Build faltantes lists
    faltantes_parciales = []
    faltantes_completos = []
    for sp in sale_points:
        items_with_missing = [it for it in sp.items if (it.missing or 0) > 0]
        if not items_with_missing:
            continue
        if len(items_with_missing) == len(sp.items):
            target = faltantes_completos
        else:
            target = faltantes_parciales
        for it in items_with_missing:
            target.append({
                "store_number": sp.store_number,
                "store_name": sp.store_name,
                "internal_code": it.internal_code,
                "description": it.description,
                "original_code": it.original_code,
                "units_per_box": it.units_per_box,
                "quantity": it.quantity,
                "sent": it.sent,
                "missing": it.missing,
            })

    # Use relationship data
    org = order.organization
    supplier_name = (org.name if org else "") or ""

    dept = order.department_rel
    dept_code = (dept.department_code if dept else "") or ""
    dept_name = (dept.name if dept else "") or ""
    # vendor number (NUM_VENDEDOR) lives on the department
    supplier_internal_code = (dept.supplier_code if dept else "") or ""
    department_value = f"{dept_code} - {dept_name}" if dept_code and dept_name else dept_code

    store = order.deliver_to_store
    if store:
        deliver_to = f"{store.store_code} - {store.store_name}"
        deliver_to_gln = store.gln or ""
        if deliver_to_gln:
            deliver_to += f" - {deliver_to_gln}"
    else:
        deliver_to = ""
        deliver_to_gln = ""

    context = {
        "deliver_to": deliver_to,
        "deliver_to_gln": deliver_to_gln,
        "supplier_name": supplier_name,
        "supplier_internal_code": supplier_internal_code,
        "document_number": order.document_number or "",
        "confirmation": order.confirmation_number or order.bgm011 or "",
        "department": department_value,
        "sale_points": sale_points,
        "item_summary": item_summary,
        "box_summary": box_summary,
        "totals": totals,
        "all_labels": all_labels,
        "total_boxes_all": total_boxes_all,
        "faltantes_parciales": faltantes_parciales,
        "faltantes_completos": faltantes_completos,
        "colors": get_color_palette(color),
    }

    template = _jinja_env.get_template("crossdocking.html")
    return template.render(**context)


def download_from_s3(url: str) -> bytes:
    """Download a file from S3 given its CloudFront or S3 URL."""
    bucket = AppConfig.get_key("s3.bucket")
    pdf_domain = (AppConfig.get_key("pdf.domain", "") or "").rstrip("/")

    if pdf_domain and url.startswith(pdf_domain):
        key = url[len(pdf_domain):].lstrip("/")
    else:
        key = url.split(".amazonaws.com/", 1)[-1]

    session, _ = _get_s3_session()
    s3_client = session.client("s3")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def create_crossdocking_pdf(order: Order, crossdocking_data, color=None) -> str:
    """Generate crossdocking distribution PDF and upload to S3."""
    html = render_crossdocking_html(order, crossdocking_data, color)
    pdf_bytes = generate_pdf(
        html,
        header_left=datetime.now().strftime("%d/%m/%Y"),
        header_center="Hoja de distribución",
    )
    last4 = (order.document_number or "")[-4:]
    key = _s3_key(order.company_id, order.document_number, f"{last4}.pdf")
    return upload_file_to_s3(pdf_bytes, key)
