"""Catalog changes must round-trip without a legacy field or fiscal side effects."""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.dtos.requests.product_request_dto import ProductRequestDTO
from app.models.cabys import Cabys
from app.models.product import Product
from app.services.product_service import _apply_catalogue_fields, _map_product


@pytest.mark.parametrize("kind", ["product", "service", "program"])
def test_product_type_round_trip_keeps_the_medical_cabys_classification(kind):
    cabys_id = uuid4()
    product = Product(
        id="item-1", organization_id="org-1", category_id="category-1",
        name="Medical course", description="Course", price=Decimal("100"), units_per_box=1,
        status=1, stock_quantity=0, low_stock_threshold=10, track_inventory=False,
        type="service", on_sale=False, is_offer=False, codes=[], discounts=[], taxes=[],
        cabys_id=cabys_id, cabys=Cabys(id=cabys_id, code="9311100000000", product_type_id=6),
        unit_measure="Sp",
    )

    _apply_catalogue_fields(product, ProductRequestDTO(type=kind))
    response = _map_product(product).model_dump()

    assert response["type"] == kind
    assert response["cabys"]["product_type_id"] == 6
    assert response["cabys"]["id"] == str(cabys_id)
    assert response["unit_measure"] == "Sp"
    assert "is_service" not in response
    assert not hasattr(product, "is_service")
