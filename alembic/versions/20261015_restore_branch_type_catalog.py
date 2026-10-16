"""Restore catalog entries actually referenced by existing branches.

An organization without a catalog used to accept the two legacy type codes.
Preserve those branches without introducing unused default types into any org.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261015_branch_type_catalog"
down_revision = "20261015_decimal_product_prices"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
        INSERT INTO branch_types (
            organization_id, code, name, icon, color, sort_order, status, created_by
        )
        SELECT DISTINCT b.organization_id, b.type,
            CASE b.type WHEN 'stand' THEN 'Sucursal' WHEN 'restaurant' THEN 'Local'
                ELSE initcap(replace(replace(b.type, '_', ' '), '-', ' ')) END,
            'store', 'primary', 0, 1, 'system'
        FROM branches b
        WHERE b.deleted_on IS NULL AND b.type IS NOT NULL AND b.type <> ''
        AND NOT EXISTS (
            SELECT 1 FROM branch_types bt
            WHERE bt.organization_id = b.organization_id AND bt.code = b.type
        )
        ON CONFLICT (organization_id, code) DO NOTHING
    """))


def downgrade():
    # These rows are referenced by branches and may have been customized.
    pass
