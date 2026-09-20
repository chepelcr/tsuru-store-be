"""Add crossdocking_clients.notes

The POS has shipped a notes panel with a save button against a column that does
not exist. `ClientRequestDTO` does not forbid extra keys, so the note was
accepted by the API, ignored, and lost; the panel read back empty every time,
because `ClientResponse` had no `notes` either. The feature looked implemented
from both ends and was implemented at neither.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-20 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "clients"


def _has_column(conn, column: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": TABLE, "c": column},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "notes"):
        op.add_column(TABLE, sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, "notes"):
        op.drop_column(TABLE, "notes")
