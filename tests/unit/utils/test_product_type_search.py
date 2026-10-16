"""The shared catalog must filter kinds exactly, including public Programs pages."""
import pytest
from sqlalchemy import create_engine, select, text

from app.enums.product_search_filters import ProductSearchFilters
from app.models.product import Product
from app.utils.search_utils import SearchUtils


@pytest.mark.parametrize("kind", ["product", "service", "program"])
def test_catalog_type_filter_combines_with_status_and_search(kind):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE products (id TEXT, type TEXT, name TEXT, status INTEGER)"
            ))
            connection.execute(text(
                "INSERT INTO products (id, type, name, status) VALUES (:id, :type, :name, :status)"
            ), [
                {"id": f"{product_type}-{status}", "type": product_type, "name": "Training", "status": status}
                for product_type in ("product", "service", "program")
                for status in (1, 2)
            ] + [{"id": "other", "type": kind, "name": "Other", "status": 1}])

            filters, _ = SearchUtils.parse_search_filter(
                f"type:{kind},status:1,name:Training", Product, ProductSearchFilters
            )
            ids = connection.execute(select(Product.id).where(*filters)).scalars().all()
            assert ids == [f"{kind}-1"]
    finally:
        engine.dispose()
