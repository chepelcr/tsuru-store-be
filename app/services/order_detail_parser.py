from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Optional

import openpyxl

from app.utils.order_dates import as_date
from app.enums.excel_headers import ExcelHeader
from app.exceptions import ExcelParsingException
from app.dtos.responses.order_dto import (
    OrderDetailLineResponse,
    OrderDetailTotals,
)


def _safe_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(value) -> int:
    if value is None:
        return 0
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def _format_date(value) -> Optional[date]:
    """A real `date` from whatever the spreadsheet cell held.

    openpyxl hands back a `datetime` for a cell formatted as a date and a string
    for one formatted as text, and the sheets contain both. This used to return a
    `DD/MM/YYYY` STRING, which is how the column came to hold two formats — the
    import wrote day-first while the POS wrote ISO into the same varchar.

    The name is kept because every call site reads `_format_date(...)`; what it
    formats now is a date object rather than text.
    """
    return as_date(value)


def _split_deliver_to(deliver_to: str) -> tuple[str, str]:
    """Split 'CODE NAME' into (code, name). Returns ('', deliver_to) if no space found."""
    if not deliver_to:
        return "", ""
    parts = deliver_to.split(" ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", deliver_to.strip()


def _parse_description(descripcion: str) -> tuple[str, int]:
    if " :: " in descripcion:
        parts = descripcion.rsplit(" :: ", maxsplit=1)
        name = parts[0].strip()
        try:
            units = int(parts[1].strip())
        except (ValueError, TypeError):
            return name, 0
        return name, units
    return descripcion.strip(), 0


def _get(row: tuple, hmap: dict[ExcelHeader, int], header: ExcelHeader):
    """Get a value from a row using the header map. Returns None if header not mapped."""
    idx = hmap.get(header)
    if idx is None or idx >= len(row):
        return None
    return row[idx]


class OrderDetailParseResult:
    """Intermediate result from parsing a DETALLES Excel file."""

    def __init__(
        self,
        document_number: str,
        client_name: str,
        creation_date: str,
        delivery_date: str,
        deliver_to_code: str,
        deliver_to_name: str,
        subtotal: float,
        discounts: float,
        net_total: float,
        taxes: float,
        grand_total: float,
        total_quantities: int,
        supplier_name: str,
        client_gln: str,
        line_count: int,
        dispatch_gln: str,
        document_type: str,
        supplier_gln: str,
        supplier_internal_code: str,
        bgm011: str | None,
        order_type: str,
        event: str,
        department: str,
        latitude: str | None,
        longitude: str | None,
        comment: str | None,
        lines: list[OrderDetailLineResponse],
        totals: OrderDetailTotals,
    ):
        self.document_number = document_number
        self.client_name = client_name
        self.creation_date = creation_date
        self.delivery_date = delivery_date
        self.deliver_to_code = deliver_to_code
        self.deliver_to_name = deliver_to_name
        self.subtotal = subtotal
        self.discounts = discounts
        self.net_total = net_total
        self.taxes = taxes
        self.grand_total = grand_total
        self.total_quantities = total_quantities
        self.supplier_name = supplier_name
        self.client_gln = client_gln
        self.line_count = line_count
        self.dispatch_gln = dispatch_gln
        self.document_type = document_type
        self.supplier_gln = supplier_gln
        self.supplier_internal_code = supplier_internal_code
        self.bgm011 = bgm011
        self.order_type = order_type
        self.event = event
        self.department = department
        self.latitude = latitude
        self.longitude = longitude
        self.comment = comment
        self.lines = lines
        self.totals = totals


def parse_order_detail_file(file: BytesIO) -> OrderDetailParseResult:
    try:
        wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    except Exception as e:
        raise ExcelParsingException(f"Could not open Excel file: {e}")

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if len(rows) < 2:
        raise ExcelParsingException("File must have at least a header row and one data row")

    headers = [_safe_str(h) for h in rows[0]]

    # Build header map from ExcelHeader enum aliases
    hmap = ExcelHeader.build_header_map(headers)

    if ExcelHeader.DOCUMENT_NUMBER not in hmap:
        raise ExcelParsingException(
            f"Expected header 'Numero Doc' not found in file headers: {headers[:5]}..."
        )

    first = rows[1]

    # Parse line items from all data rows
    lines: list[OrderDetailLineResponse] = []
    for row in rows[1:]:
        descripcion_raw = _safe_str(_get(row, hmap, ExcelHeader.DESCRIPTION))
        description, units_per_box = _parse_description(descripcion_raw)

        line = OrderDetailLineResponse(
            line_number=_safe_int(_get(row, hmap, ExcelHeader.LINE_NUMBER)),
            internal_code=_safe_str(_get(row, hmap, ExcelHeader.INTERNAL_CODE)),
            code=_safe_str(_get(row, hmap, ExcelHeader.CODE)),
            client_article_code=_safe_str(_get(row, hmap, ExcelHeader.CLIENT_ARTICLE_CODE)),
            description=description,
            units_per_box=units_per_box,
            quantity_ordered=_safe_int(_get(row, hmap, ExcelHeader.QUANTITY_ORDERED)),
            units_ordered=_safe_int(_get(row, hmap, ExcelHeader.UNITS_ORDERED)),
            unit_price=_safe_float(_get(row, hmap, ExcelHeader.UNIT_PRICE)),
            discount=_safe_float(_get(row, hmap, ExcelHeader.DISCOUNT)),
            line_total=_safe_float(_get(row, hmap, ExcelHeader.LINE_TOTAL)),
            tax=_safe_float(_get(row, hmap, ExcelHeader.TAX)),
            quantity_dispatched=_safe_int(_get(row, hmap, ExcelHeader.QUANTITY_DISPATCHED)),
            dispatch_rejection_reason=_safe_str(
                _get(row, hmap, ExcelHeader.DISPATCH_REJECTION_REASON)
            ) or None,
            quantity_received=_safe_int(_get(row, hmap, ExcelHeader.QUANTITY_RECEIVED)),
            article_code=_safe_str(_get(row, hmap, ExcelHeader.ARTICLE_CODE)),
        )
        lines.append(line)

    totals = OrderDetailTotals(
        total_lines=len(lines),
        total_quantity_ordered=sum(ln.quantity_ordered for ln in lines),
        total_units_ordered=sum(ln.units_ordered for ln in lines),
        total_quantity_dispatched=sum(ln.quantity_dispatched for ln in lines),
        total_quantity_received=sum(ln.quantity_received for ln in lines),
        subtotal=_safe_float(_get(first, hmap, ExcelHeader.GRAND_TOTAL)),
        net_total=_safe_float(_get(first, hmap, ExcelHeader.GRAND_TOTAL)) - _safe_float(_get(first, hmap, ExcelHeader.DISCOUNTS)),
        grand_total=_safe_float(_get(first, hmap, ExcelHeader.GRAND_TOTAL)),
    )

    deliver_to_raw = _safe_str(_get(first, hmap, ExcelHeader.DELIVER_TO))
    deliver_to_code, deliver_to_name = _split_deliver_to(deliver_to_raw)
    
    subtotal = _safe_float(_get(first, hmap, ExcelHeader.GRAND_TOTAL))
    discounts = _safe_float(_get(first, hmap, ExcelHeader.DISCOUNTS))
    net_total = subtotal - discounts
    taxes = _safe_float(_get(first, hmap, ExcelHeader.TAXES))
    grand_total = net_total + taxes

    return OrderDetailParseResult(
        document_number=_safe_str(_get(first, hmap, ExcelHeader.DOCUMENT_NUMBER)),
        client_name=_safe_str(_get(first, hmap, ExcelHeader.CLIENT_NAME)),
        creation_date=_format_date(_get(first, hmap, ExcelHeader.CREATION_DATE)),
        delivery_date=_format_date(_get(first, hmap, ExcelHeader.DELIVERY_DATE)),
        deliver_to_code=deliver_to_code,
        deliver_to_name=deliver_to_name,
        subtotal=subtotal,
        discounts=discounts,
        net_total=net_total,
        taxes=taxes,
        grand_total=grand_total,
        total_quantities=_safe_int(_get(first, hmap, ExcelHeader.TOTAL_QUANTITIES)),
        supplier_name=_safe_str(_get(first, hmap, ExcelHeader.SUPPLIER_NAME)),
        client_gln=_safe_str(_get(first, hmap, ExcelHeader.CLIENT_GLN)),
        line_count=_safe_int(_get(first, hmap, ExcelHeader.LINE_COUNT)),
        dispatch_gln=_safe_str(_get(first, hmap, ExcelHeader.DISPATCH_GLN)),
        document_type=_safe_str(_get(first, hmap, ExcelHeader.DOCUMENT_TYPE)),
        supplier_gln=_safe_str(_get(first, hmap, ExcelHeader.SUPPLIER_GLN)),
        supplier_internal_code=_safe_str(
            _get(first, hmap, ExcelHeader.SUPPLIER_INTERNAL_CODE)
        ),
        bgm011=_safe_str(_get(first, hmap, ExcelHeader.BGM011)) or None,
        order_type=_safe_str(_get(first, hmap, ExcelHeader.ORDER_TYPE)),
        event=_safe_str(_get(first, hmap, ExcelHeader.EVENT)),
        department=_safe_str(_get(first, hmap, ExcelHeader.DEPARTMENT)),
        latitude=_safe_str(_get(first, hmap, ExcelHeader.LATITUDE)) or None,
        longitude=_safe_str(_get(first, hmap, ExcelHeader.LONGITUDE)) or None,
        comment=_safe_str(_get(first, hmap, ExcelHeader.COMMENT)) or None,
        lines=lines,
        totals=totals,
    )
