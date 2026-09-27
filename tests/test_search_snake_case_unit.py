"""Search filter fields are snake_case on the wire.

Run: `python -m pytest tests/test_search_snake_case_unit.py -q`

The parser DROPS a clause whose field it cannot resolve — silently, returning
the list unfiltered — so a field-name mismatch looks like a search that found
nothing useful. The orders enum was the last one still speaking camelCase.
"""
import pytest

from app.enums.search_filters import SearchFilters

pytestmark = pytest.mark.unit


def test_every_order_filter_is_snake_case():
    for member in SearchFilters:
        assert member.json_field == member.json_field.lower(), member


@pytest.mark.parametrize("legacy,snake", [
    ("clientName", "client_name"),
    ("documentNumber", "document_number"),
    ("deliverToCode", "deliver_to_code"),
])
def test_legacy_camel_case_still_resolves(legacy, snake):
    # An older client keeps filtering until it is redeployed.
    assert SearchFilters.get_filter_by_json_field(legacy) is SearchFilters.get_filter_by_json_field(snake)
    assert SearchFilters.get_filter_by_json_field(snake) is not None
