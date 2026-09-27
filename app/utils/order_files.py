"""How an order's generated files are named.

Walmart's portal identifies an order's attachments by the last four digits of
its document number (`1234-OC.pdf`, `1234-DT.xlsx`, `1234-RN.xlsx`…), so orders
for Walmart keep that short form. Every other customer gets the full document
number — for an order like `PLC-001` the last four characters (`-001`) are
not a usable name.
"""

from __future__ import annotations

from typing import Optional

from app.models.client import Client
from app.models.order import Order

#: GS1 company prefix of Wal-Mart Centroamérica; every GLN it issues starts with it.
WALMART_GLN_PREFIX = "7407001"

#: Name fragments that identify Walmart when the client has no GLN.
WALMART_NAME_MARKERS = ("WALMART", "WAL-MART", "WAL MART")


def is_walmart_client(client: Optional[Client]) -> bool:
    """True when the client is Walmart, by GLN prefix or, failing that, by name."""
    if client is None:
        return False
    gln = (client.client_gln or "").strip()
    if gln:
        return gln.startswith(WALMART_GLN_PREFIX)
    name = (client.client_name or "").upper()
    return any(marker in name for marker in WALMART_NAME_MARKERS)


def file_prefix(document_number: Optional[str], client: Optional[Client]) -> str:
    """The name an order's files start with: last four digits for Walmart, else the full number."""
    number = (document_number or "").strip()
    return number[-4:] if is_walmart_client(client) else number


def order_file_prefix(order: Order) -> str:
    """`file_prefix` for an order, using its linked client."""
    return file_prefix(order.document_number, order.client)
