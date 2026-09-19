"""Make the order dates real dates.

`crossdocking_orders.creation_date` / `.delivery_date` and
`crossdocking_confirmations.delivery_date` are VARCHAR(20), and they hold **two
different formats depending on how the row was created**:

    Excel import      DD/MM/YYYY   (`order_detail_parser._format_date`)
    manual / POS      YYYY-MM-DD   (the FE sends an ISO date)
    storefront        YYYY-MM-DD

Everything downstream had to guess. `search_utils` compares them as raw strings,
so a `deliveryDate` range is day-first lexicographic and never matches an
ISO-dated manual order at all; `confirmation_service._parse_date` hard-fails on
the ISO form; and the dashboard deliberately avoids these columns entirely,
filtering on `created_on` instead, because a bare cast reads the wrong month.

**The cast must match each row's shape, not guess.** Of the 45 live rows, 44 are
DD/MM/YYYY and one is ISO — and **12 of the DD/MM rows have a day ≤ 12**, so a
plain `::date` under Postgres's default DateStyle (MDY) would silently read
"09/02/2026" as 2 September instead of 9 February. Silently: no error, a quarter
of the table wrong. Hence the explicit per-row regex below.

Anything matching neither shape becomes NULL rather than failing the migration —
there is no such row today, and a date nobody can parse is better absent than
invented. The verification in `deploys`/the plan checks the count afterwards.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""

from alembic import op
import sqlalchemy as sa

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None

#: (table, column) pairs to convert.
COLUMNS = (
    ("crossdocking_orders", "creation_date"),
    ("crossdocking_orders", "delivery_date"),
    ("crossdocking_confirmations", "delivery_date"),
)

#: Shape-matched conversion. `to_date` with an explicit format is immune to
#: DateStyle; the bare cast is not.
_TO_DATE = """
    CASE
      WHEN {col} IS NULL OR btrim({col}) = '' THEN NULL
      WHEN btrim({col}) ~ '^\\d{{2}}/\\d{{2}}/\\d{{4}}$' THEN to_date(btrim({col}), 'DD/MM/YYYY')
      WHEN btrim({col}) ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}$' THEN to_date(btrim({col}), 'YYYY-MM-DD')
      ELSE NULL
    END
"""

#: Back to text on the way down, in the format the Excel import used — which is
#: what the majority of rows were and what the spreadsheet readers expect.
_TO_TEXT = "CASE WHEN {col} IS NULL THEN NULL ELSE to_char({col}, 'DD/MM/YYYY') END"


def upgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(20),
            type_=sa.Date(),
            existing_nullable=True,
            postgresql_using=_TO_DATE.format(col=column),
        )


def downgrade() -> None:
    """Back to VARCHAR(20), writing DD/MM/YYYY.

    Lossy in one respect, deliberately: a row that was originally ISO
    ("2026-09-14") comes back as "14/09/2026". The value is the same date and
    every reader accepts the DD/MM form, but the original spelling is not
    recoverable — the column no longer records which format it arrived in, which
    is the entire point of having converted it.
    """
    for table, column in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Date(),
            type_=sa.String(20),
            existing_nullable=True,
            postgresql_using=_TO_TEXT.format(col=column),
        )
