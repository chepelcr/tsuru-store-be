"""Order file naming, pinned.

Walmart orders name their files by the last four digits of the document number
(what its portal expects); every other customer gets the full number, because
the last four characters of `PLC-001` are `-001`.

Run: `python -m pytest tests/test_order_files_unit.py -q`
"""

import pytest

from app.models.client import Client
from app.models.order import Order
from app.utils.order_files import file_prefix, is_walmart_client, order_file_prefix


def _client(name=None, gln=None) -> Client:
    return Client(company_id="org", client_name=name, client_gln=gln, status=0)


class TestIsWalmartClient:
    @pytest.mark.parametrize("name,gln,expected", [
        ("WAL-MART CENTROAMERICA", "7407001003857", True),
        ("Anything", "7407001999999", True),
        ("WALMART", None, True),
        ("Wal Mart Escazú", "", True),
        ("Roberto Cruz", "CL-001", False),
        # A GLN wins over the name: a non-Walmart GLN is not Walmart.
        ("Walmart reseller", "7441119600505", False),
        (None, None, False),
    ])
    def test_detection(self, name, gln, expected):
        assert is_walmart_client(_client(name, gln)) is expected

    def test_no_client(self):
        assert is_walmart_client(None) is False


class TestFilePrefix:
    def test_walmart_keeps_last_four(self):
        assert file_prefix("4512345678", _client("WAL-MART CENTROAMERICA", "7407001003857")) == "5678"

    def test_other_customer_uses_full_number(self):
        assert file_prefix("PLC-001", _client("Roberto Cruz", "CL-001")) == "PLC-001"

    def test_no_client_uses_full_number(self):
        assert file_prefix("PM-000012", None) == "PM-000012"

    def test_order_uses_its_client(self):
        order = Order(company_id="org", document_number="PLC-001")
        order.client = _client("Roberto Cruz", "CL-001")
        assert order_file_prefix(order) == "PLC-001"
