"""Give every organization a persisted Branch default without changing assignments."""
from alembic import op
import sqlalchemy as sa

revision = "20261016_default_branch_types"
down_revision = "20261015_branch_type_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("branch_types", sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("""
        INSERT INTO branch_types (
            organization_id, code, name, icon, color, sort_order, status, created_by, is_default
        )
        SELECT id, 'branch', 'Branch', 'store', 'primary', 0, 1, 'system', true
        FROM organizations
        ON CONFLICT (organization_id, code) DO UPDATE SET name = EXCLUDED.name, is_default = true
    """))
    op.create_index("uq_branch_types_default", "branch_types", ["organization_id"], unique=True,
                    postgresql_where=sa.text("is_default AND deleted_on IS NULL"))


def downgrade():
    op.drop_index("uq_branch_types_default", table_name="branch_types")
    op.drop_column("branch_types", "is_default")
    # Keep the catalog entries: organizations may have customized or used them.
