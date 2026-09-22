"""Add consecutive_adjustments — audit trail of manual consecutive edits

The POS can now raise a terminal's consecutive by hand (TSR-327). That decides
the number of the next fiscal document, so every such edit is recorded with the
value it replaced, the new value, who made it and why. Append-only.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "consecutive_adjustments"


def _has_table(conn) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
            {"t": TABLE},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn):
        return
    op.create_table(
        TABLE,
        sa.Column("adjustment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.String(255), nullable=False),
        sa.Column(
            "consecutive_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("consecutives.consecutive_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("terminal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type_id", sa.Integer(), nullable=False),
        sa.Column("previous_number", sa.BigInteger(), nullable=True),
        sa.Column("new_number", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.String(255), nullable=False),
        sa.Column(
            "changed_on",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_consecutive_adjustments_consecutive", TABLE, ["consecutive_id", "changed_on"]
    )
    op.create_index("idx_consecutive_adjustments_org", TABLE, ["organization_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn):
        op.drop_index("idx_consecutive_adjustments_org", table_name=TABLE)
        op.drop_index("idx_consecutive_adjustments_consecutive", table_name=TABLE)
        op.drop_table(TABLE)
