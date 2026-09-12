"""Terminal codes are unique per BRANCH, not per organization.

`uq_terminals_org_code` made a terminal code unique across the whole
organization. Hacienda numbers terminals *within* a branch: its 20-digit
consecutive is branch(3) + terminal(5) + type(2) + number(10), so the
(branch, terminal) PAIR identifies the point of sale. Terminal 1 under branch 1
and terminal 1 under branch 14 are both legal, and a real taxpayer has them.

This blocked branch discovery (TSR-254). Importing VILMA CORELLA ARTAVIA's
history on 2026-09-12 found branch 14 / terminal 1 while the organization
already had branch 1 / terminal 1 locally; the sync correctly refused to
reassign an existing terminal to a different branch and rolled the message back
rather than corrupt the mapping, so no branch was ever created.

store-be's own routes already assume the looser rule —
`/branches/{branch_code}/terminals/{terminal_code}` — so the org-wide
constraint was the part that disagreed with both Hacienda and this API.

Widening a uniqueness constraint cannot invalidate existing rows, so the
upgrade is safe on populated data. The downgrade is NOT: it can fail if two
branches have since been given the same terminal code, which is exactly the
state this migration exists to permit. It refuses loudly rather than deleting a
terminal to make room.

Revision ID: c2d3e4f5a6b7
Revises: be1f2a3b4c5d
"""

from alembic import op
import sqlalchemy as sa


revision = "c2d3e4f5a6b7"
down_revision = "be1f2a3b4c5d"
branch_labels = None
depends_on = None

_OLD = "uq_terminals_org_code"
_NEW = "uq_terminals_org_branch_code"


def upgrade() -> None:
    bind = op.get_bind()

    # Created as a UniqueConstraint by j0e1f2a3b4c5, but the model declared it
    # as Index(..., unique=True) under a different name, so tolerate either
    # shape rather than assuming which one this database actually has.
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'terminals'")
        )
    }

    if _OLD in existing:
        # A UniqueConstraint is backed by an index of the same name; dropping
        # the constraint removes both.
        op.drop_constraint(_OLD, "terminals", type_="unique")
    if "idx_terminals_org_code" in existing:
        op.drop_index("idx_terminals_org_code", table_name="terminals")

    if _NEW not in existing:
        op.create_unique_constraint(
            _NEW, "terminals", ["organization_id", "branch_id", "code"]
        )


def downgrade() -> None:
    bind = op.get_bind()

    clashes = bind.execute(
        sa.text(
            """
            SELECT organization_id, code, count(*) AS n
            FROM terminals
            WHERE deleted_on IS NULL
            GROUP BY organization_id, code
            HAVING count(*) > 1
            """
        )
    ).all()
    if clashes:
        detail = ", ".join(f"org={c[0]} code={c[1]} ({c[2]} rows)" for c in clashes)
        raise RuntimeError(
            "Cannot restore the organization-wide terminal code constraint: "
            f"{detail}. These are legal Hacienda configurations (a terminal code "
            "repeats across branches). Re-numbering or deleting a terminal would "
            "break the fiscal consecutive it owns, so this downgrade refuses "
            "rather than choosing for you."
        )

    op.drop_constraint(_NEW, "terminals", type_="unique")
    op.create_unique_constraint(_OLD, "terminals", ["organization_id", "code"])
