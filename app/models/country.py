"""Read-only mirror of data-be's `countries` catalog.

store-be never writes it (data-be's `app/locations` owns schema and rows; alembic
here excludes it). It exists so a stored phone country — the ISO numeric code,
``188`` — can be shown as its dialing code, ``+506``, straight from the DB
instead of every client looking it up.

NOTE: `Optional[X]` rather than `X | None` — the Lambda runtime is Python 3.9
(see `cabys.py`).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Country(Base):
    __tablename__ = "countries"
    __table_args__ = {"extend_existing": True}

    # ISO 3166-1 numeric — the primary key. NOT a dialing code.
    iso_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    iso: Mapped[str] = mapped_column(String(2), nullable=False)
    # The dialing code with its "+", e.g. "+506".
    phone_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    @property
    def dial_code(self) -> Optional[str]:
        """The country part, bare digits: ``+506`` → ``506``, ``+1-869`` → ``1``.

        Same split sales-be sends as ``CodigoPais`` (max three digits).
        """
        digits = "".join(ch for ch in (self.phone_code or "").partition("-")[0] if ch.isdigit())
        return digits or None

    @property
    def dial_area(self) -> Optional[str]:
        """The area code the catalog writes after the dash (``+1-869`` → ``869``)."""
        digits = "".join(ch for ch in (self.phone_code or "").partition("-")[2] if ch.isdigit())
        return digits or None
