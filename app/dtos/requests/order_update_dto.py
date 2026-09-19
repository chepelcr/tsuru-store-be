"""Request DTO for editing an order in place.

Replaces the status-only body this endpoint used to take. It carried exactly
`{status: int}`, which is why changing a delivery date meant deleting the order
and re-uploading the spreadsheet — the only other way the date could be set.

Both fields are optional and at least one is required, so `{status}` alone keeps
working for every existing client.

Authors: jcampos
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrderUpdateDTO(BaseModel):
    """Fields of an order that may be changed after it exists."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[int] = Field(
        None,
        description=(
            "Order status: 0=quote, 1=pending, 2=processing, 3=shipped, "
            "4=delivered, 5=cancelled. Illegal transitions are refused."
        ),
        ge=0,
        le=5,
        examples=[4],
    )

    delivery_date: Optional[date] = Field(
        None,
        description=(
            "New delivery date, ISO `YYYY-MM-DD`. Allowed only while the order is "
            "`pending` and not yet billed, and it must not be in the past. The "
            "order's spreadsheets are rewritten to match — a database-only change "
            "would be reverted by the next reprocess."
        ),
        examples=["2026-10-15"],
    )

    @model_validator(mode="after")
    def at_least_one_field(self) -> "OrderUpdateDTO":
        """An empty body is a mistake, not a no-op.

        Accepting it would return 200 for a request that changed nothing, which
        reads as success to whatever sent it.
        """
        if self.status is None and self.delivery_date is None:
            raise ValueError("Provide at least one of: status, delivery_date")
        return self
