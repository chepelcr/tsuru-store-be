"""The one place that knows how an order's dates are shaped.

`crossdocking_orders.creation_date` / `.delivery_date` and
`crossdocking_confirmations.delivery_date` are becoming real `DATE` columns
(migration `d3e4f5a6b7c8`). Until that migration has run in every environment they
may still arrive as strings, and in **two** formats, because the writers never
agreed:

    Excel import   DD/MM/YYYY
    manual / POS   YYYY-MM-DD
    storefront     YYYY-MM-DD

Every reader therefore goes through `as_date`, which accepts a `date`, a
`datetime`, or either string, and `as_display` / `as_iso`, which format one for a
template or a wire payload. Written once so the code works on both sides of the
migration and so no caller has to remember which format it is holding — the
parsing scattered across `confirmation_service`, `search_utils`, `pdf_service` and
`ticket_service` is exactly how "09/02/2026" came to mean two different days
depending on which file read it.

**Never `date.fromisoformat` or a bare cast on these values.** Postgres's default
DateStyle here is MDY, so `'09/02/2026'::date` is 2 September, not 9 February —
silently, on a quarter of the live rows.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional, Union

logger = logging.getLogger(__name__)

#: How an order date is rendered for a person: PDFs, tickets, emails, and the
#: spreadsheet cells the chain reads back.
DISPLAY_FORMAT = "%d/%m/%Y"

#: The two string shapes that exist in the data, most common first.
_STRING_FORMATS = (DISPLAY_FORMAT, "%Y-%m-%d")

DateLike = Union[date, datetime, str, None]


def as_date(value: DateLike) -> Optional[date]:
    """Coerce anything the columns have ever held into a `date`.

    Returns None for an empty value or one matching neither format — a date
    nobody can parse is better absent than invented, and the caller decides what
    an absent date means.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None
    # An ISO datetime ("2026-09-14T00:00:00") reduces to its date part first.
    if "T" in text:
        text = text.split("T", 1)[0]

    for fmt in _STRING_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    logger.warning("Unparseable order date %r; treating as absent", value)
    return None


def as_display(value: DateLike, default: str = "") -> str:
    """`DD/MM/YYYY` for a template, a ticket, an email or a spreadsheet cell."""
    parsed = as_date(value)
    return parsed.strftime(DISPLAY_FORMAT) if parsed else default


def as_iso(value: DateLike) -> Optional[str]:
    """`YYYY-MM-DD` for a JSON payload — one format on the wire, always."""
    parsed = as_date(value)
    return parsed.isoformat() if parsed else None
