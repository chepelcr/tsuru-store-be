"""Store product prices with decimal precision.

Revision ID: 20261015_decimal_product_prices
Revises: c8d9e0f1a2b3
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261015_decimal_product_prices"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "products",
        "price",
        existing_type=sa.Integer(),
        type_=sa.Numeric(18, 5),
        postgresql_using="price::numeric(18, 5)",
    )
    op.alter_column(
        "products",
        "original_price",
        existing_type=sa.Integer(),
        type_=sa.Numeric(18, 5),
        postgresql_using="original_price::numeric(18, 5)",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM products
                WHERE price <> trunc(price)
                   OR (
                       original_price IS NOT NULL
                       AND original_price <> trunc(original_price)
                   )
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade product prices while fractional values exist';
            END IF;
        END $$;
        """
    )
    op.alter_column(
        "products",
        "original_price",
        existing_type=sa.Numeric(18, 5),
        type_=sa.Integer(),
        postgresql_using="original_price::integer",
    )
    op.alter_column(
        "products",
        "price",
        existing_type=sa.Numeric(18, 5),
        type_=sa.Integer(),
        postgresql_using="price::integer",
    )
