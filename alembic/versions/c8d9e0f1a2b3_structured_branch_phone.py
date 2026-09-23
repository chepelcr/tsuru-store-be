"""Branch phones become structured, like client phones: ISO country + number

`branches.phone` was free text — "+506 89890512" from the Hacienda sync, bare
"88888888" from the form — so nothing could say which country a number belonged
to, and the dialing code was baked into a string. Branches now store what
clients store: `phone_country_code` (ISO numeric, 188, a key into data-be's
countries catalog) and `phone_number` (digits). The dialing code is resolved
from the catalog on read.

The backfill reads a leading "+<dialing code>" against `countries.phone_code`
(a code shared by several countries keeps Costa Rica, the only market today)
and treats everything else as a Costa Rican number. The free-text column is
dropped: dev only, no users (owner decision, 2026-09-23).

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-09-23 12:00:00.000000

"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COSTA_RICA = "188"


def upgrade() -> None:
    op.add_column("branches", sa.Column("phone_country_code", sa.String(3), nullable=True))
    op.add_column("branches", sa.Column("phone_number", sa.String(20), nullable=True))

    bind = op.get_bind()
    iso_by_dial = {}
    for iso_code, phone_code in bind.execute(sa.text("SELECT iso_code, phone_code FROM countries")):
        digits = re.sub(r"\D", "", (phone_code or "").partition("-")[0])
        iso_by_dial.setdefault(digits, []).append(iso_code)

    for branch_id, phone in bind.execute(sa.text("SELECT branch_id, phone FROM branches WHERE phone IS NOT NULL")):
        text = phone.strip()
        country = COSTA_RICA
        match = re.match(r"^\+(\d{1,3})[\s-]+(.+)$", text)
        if match:
            candidates = iso_by_dial.get(match.group(1), [])
            country = candidates[0] if len(candidates) == 1 else COSTA_RICA
            text = match.group(2)
        number = re.sub(r"\D", "", text)[:20] or None
        bind.execute(
            sa.text("UPDATE branches SET phone_country_code = :c, phone_number = :n WHERE branch_id = :id"),
            {"c": country if number else None, "n": number, "id": branch_id},
        )

    op.drop_column("branches", "phone")


def downgrade() -> None:
    op.add_column("branches", sa.Column("phone", sa.String(50), nullable=True))
    op.execute(
        "UPDATE branches b SET phone = COALESCE(c.phone_code || ' ', '') || b.phone_number "
        "FROM (SELECT iso_code, phone_code FROM countries) c "
        "WHERE b.phone_number IS NOT NULL AND c.iso_code = b.phone_country_code"
    )
    op.drop_column("branches", "phone_number")
    op.drop_column("branches", "phone_country_code")
