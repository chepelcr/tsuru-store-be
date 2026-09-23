"""Add crossdocking_orders.credit_notes — the credit notes issued against an order

The early-payment discount ("descuento por pronto pago", TSR-340) is a
financial credit note (reference code 09) emitted against the order's accepted
invoice. It carries the order number, so the LINK_ORDER_DOCUMENT event reaches
store-be — but it must NOT relink the order: the invoice still bills it. The
note is appended here instead, one entry per credit note document.

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-22 23:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("crossdocking_orders", sa.Column("credit_notes", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("crossdocking_orders", "credit_notes")
