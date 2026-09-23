"""A phone country as the ISO numeric code (188), whatever shape it arrived in.

Phones are stored like client phones: the ISO key into data-be's `countries`
catalog, with the dialing code (+506) resolved on read. Producers do not all
agree on what they send: the POS sends the ISO code, older branch-sync events
sent the dialing code. This normalizes both, and falls back to Costa Rica (the
only market today) for a dialing code several countries share (+1).
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.country import Country

COSTA_RICA = "188"


def iso_country_code(session: Session, value: object) -> Optional[str]:
    """``188`` → ``188``; ``506`` / ``+506`` → ``188``; unknown → Costa Rica."""
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return None
    if session.get(Country, digits) is not None:
        return digits
    matches = session.execute(
        select(Country.iso_code).where(Country.phone_code.in_((f"+{digits}", digits)))
    ).scalars().all()
    return matches[0] if len(matches) == 1 else COSTA_RICA


def phone_digits(value: object) -> Optional[str]:
    """The number as digits (at most 20), or None."""
    digits = re.sub(r"\D", "", str(value or ""))[:20]
    return digits or None
