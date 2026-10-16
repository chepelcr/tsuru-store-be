"""Retire the legacy service boolean after preserving its catalog classification."""
from alembic import op
import sqlalchemy as sa

revision = "20261016_drop_is_service"
down_revision = "20261016_default_branch_types"
branch_labels = None
depends_on = None


def upgrade():
    # Keep explicit programs/services. Recover services written by older clients
    # that only set the boolean and left the kind empty or at its default.
    op.execute(sa.text("""
        UPDATE products SET type = 'service'
        WHERE is_service IS TRUE AND (type IS NULL OR trim(type) IN ('', 'product'))
    """))
    op.execute(sa.text("""
        UPDATE products SET type = 'product' WHERE type IS NULL OR trim(type) = ''
    """))
    op.drop_column("products", "is_service")


def downgrade():
    op.add_column("products", sa.Column("is_service", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("UPDATE products SET is_service = (type = 'service')"))
