from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

#: Hacienda's sequence segment is 10 digits.
MAX_CONSECUTIVE_NUMBER = 9_999_999_999


class ConsecutiveCreateRequestDTO(BaseModel):
    terminal_id: str = Field(...)
    document_type_id: int = Field(...)
    initial_number: Optional[int] = Field(None, ge=0, le=MAX_CONSECUTIVE_NUMBER)
    # Required when `initial_number` is set above 0: starting a counter past
    # zero is a manual adjustment and is audited like one.
    reason: Optional[str] = Field(None, max_length=500)


class ConsecutiveUpdateRequestDTO(BaseModel):
    """Manual correction of a consecutive counter. Raise-only (see service)."""

    current_number: int = Field(..., ge=1, le=MAX_CONSECUTIVE_NUMBER)
    reason: str = Field(..., min_length=3, max_length=500)
