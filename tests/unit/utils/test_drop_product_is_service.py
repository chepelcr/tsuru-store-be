"""Run the real migration on a disposable catalog and preserve fiscal fields."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_service_column_retirement_preserves_catalog_types_and_cabys():
    path = Path(__file__).parents[3] / "alembic/versions/20261016_drop_product_is_service.py"
    spec = spec_from_file_location("drop_product_is_service", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE products (
                    id TEXT PRIMARY KEY, type TEXT, is_service BOOLEAN NOT NULL,
                    cabys_id TEXT, taxes TEXT
                )
            """))
            rows = [
                {"id": "legacy-service", "type": "product", "is_service": True},
                {"id": "null-service", "type": None, "is_service": True},
                {"id": "blank-service", "type": " ", "is_service": True},
                {"id": "program", "type": "program", "is_service": True},
                {"id": "service", "type": "service", "is_service": False},
                {"id": "product", "type": "product", "is_service": False},
                {"id": "empty-product", "type": None, "is_service": False},
            ]
            connection.execute(text("""
                INSERT INTO products (id, type, is_service, cabys_id, taxes)
                VALUES (:id, :type, :is_service, 'medical-cabys', 'original-tax-data')
            """), rows)

            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()

            assert "is_service" not in {column["name"] for column in inspect(connection).get_columns("products")}
            result = connection.execute(text("SELECT id, type, cabys_id, taxes FROM products")).all()
            assert {row.id: row.type for row in result} == {
                "legacy-service": "service", "null-service": "service", "blank-service": "service",
                "program": "program", "service": "service", "product": "product", "empty-product": "product",
            }
            assert all(row.cabys_id == "medical-cabys" and row.taxes == "original-tax-data" for row in result)

            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            restored = connection.execute(text("SELECT type, is_service FROM products")).all()
            assert all(bool(row.is_service) == (row.type == "service") for row in restored)
    finally:
        engine.dispose()
