"""Order billing link: five invoice_* columns -> document_id + document_info (TSR-317)

The link between a pedido and the electronic document that billed it used to be
five flat columns, written by a synchronous POST the POS made from the checkout
the moment *our* API answered `confirmed` — before Hacienda had ruled on the
document at all.

It is now written by an SQS consumer when sales-be reports an ACCEPTED verdict,
and it is shaped as one id plus one snapshot:

* ``document_id``   — sales-be's ``Sale.sale_id`` UUID. The identifier the POS
                      already routes a document by, so the order's badge can
                      link straight to it.
* ``document_info`` — the rest of the document (type, consecutive, clave,
                      emission date, ATV status, total, currency), denormalised
                      because store-be does not own ``billing_sales`` and
                      cannot join to it.

Backfill runs BEFORE the drop, so an order already linked keeps its link. The
five old values compose into the same JSON shape the consumer writes, with
``status`` left null: those rows were linked without a Hacienda verdict, and
inventing ACCEPTED for them would assert something that was never checked.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-20 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "crossdocking_orders"
OLD_COLUMNS = (
    "invoice_sale_id",
    "invoice_document_type",
    "invoice_consecutive_number",
    "invoice_document_key",
    "invoice_issued_on",
)


def _columns(conn) -> set:
    return {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t"
            ),
            {"t": TABLE},
        )
    }


def upgrade() -> None:
    conn = op.get_bind()
    existing = _columns(conn)

    if "document_id" not in existing:
        op.add_column(TABLE, sa.Column("document_id", sa.String(length=255), nullable=True))
    if "document_info" not in existing:
        op.add_column(TABLE, sa.Column("document_info", postgresql.JSON(), nullable=True))

    # Backfill before the drop. `invoice_sale_id` is the old link key and it is
    # what `document_id` becomes — it already held the sale UUID.
    if "invoice_sale_id" in existing:
        conn.execute(
            sa.text(
                f"""
                UPDATE {TABLE}
                   SET document_id = invoice_sale_id,
                       document_info = json_build_object(
                           'document_id',        invoice_sale_id,
                           'document_type',      invoice_document_type,
                           'consecutive_number', invoice_consecutive_number,
                           'document_key',       invoice_document_key,
                           'issued_on',          invoice_issued_on
                       )
                 WHERE invoice_sale_id IS NOT NULL
                """
            )
        )

    op.create_index(
        "idx_order_document_id", TABLE, ["company_id", "document_id"], unique=False
    )

    for column in OLD_COLUMNS:
        if column in existing:
            op.drop_column(TABLE, column)


def downgrade() -> None:
    conn = op.get_bind()
    existing = _columns(conn)

    for column, type_ in (
        ("invoice_sale_id", sa.String(length=255)),
        ("invoice_document_type", sa.String(length=8)),
        ("invoice_consecutive_number", sa.String(length=50)),
        ("invoice_document_key", sa.String(length=100)),
        ("invoice_issued_on", sa.String(length=30)),
    ):
        if column not in existing:
            op.add_column(TABLE, sa.Column(column, type_, nullable=True))

    # Unpick the snapshot back into the flat columns. Anything the old shape had
    # no room for (status, total, currency) is dropped — that is what makes this
    # a downgrade rather than a round trip.
    conn.execute(
        sa.text(
            f"""
            UPDATE {TABLE}
               SET invoice_sale_id            = document_id,
                   invoice_document_type      = document_info ->> 'document_type',
                   invoice_consecutive_number = document_info ->> 'consecutive_number',
                   invoice_document_key       = document_info ->> 'document_key',
                   invoice_issued_on          = document_info ->> 'issued_on'
             WHERE document_id IS NOT NULL
            """
        )
    )

    op.drop_index("idx_order_document_id", table_name=TABLE)
    op.drop_column(TABLE, "document_info")
    op.drop_column(TABLE, "document_id")
