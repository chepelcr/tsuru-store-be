"""Client status change.

Separate from the shared `StatusRequestDTO`, which the clients endpoint was
borrowing: that one is documented as "Order status (1=pending … 5=cancelled)"
and bounded `1..5`, so this endpoint advertised order semantics for a client and
accepted 4 and 5 — values a client has no meaning for and which would have
written an unreadable status onto the row.
"""

from pydantic import BaseModel, ConfigDict, Field


class ClientStatusRequestDTO(BaseModel):
    """Status update request for a client."""

    model_config = ConfigDict(populate_by_name=True)

    status: int = Field(
        ...,
        description="Client status (1=active, 2=inactive, 3=deleted)",
        ge=1,
        le=3,
        examples=[1, 2],
    )
