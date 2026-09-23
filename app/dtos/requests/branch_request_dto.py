from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dtos.common.location_dto import LocationRequestDTO


class BranchPhoneRequestDTO(BaseModel):
    """A branch phone, shaped like a client phone.

    ``country_code`` is the ISO numeric code (188) from the countries catalog —
    the dialing code (+506) is resolved on read, never sent or stored.
    """

    model_config = ConfigDict(populate_by_name=True)

    country_code: str = Field("188", pattern=r"^[0-9]{1,3}$")
    number: str = Field(..., min_length=1, max_length=20)

    @field_validator("number")
    @classmethod
    def digits_only(cls, v: str) -> str:
        digits = "".join(ch for ch in v if ch.isdigit())
        if not digits:
            raise ValueError("number must contain digits")
        return digits


class BranchCreateRequestDTO(BaseModel):
    """Request DTO for creating a branch with snake_case fields."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    code: int = Field(..., ge=1, description="Numeric branch code, unique per organization (Hacienda requirement)")
    # A branch_types.code slug, not a fixed pair. TSR-139 replaced the two
    # hardcoded kinds with a per-org catalog and dropped the CHECK constraint;
    # this Literal was the leftover that made a swept branch (which carries the
    # org's own first branch type) un-saveable through this same API.
    type: str = Field(..., min_length=1, max_length=50)
    location: Optional[LocationRequestDTO] = Field(None)
    phone: Optional[BranchPhoneRequestDTO] = Field(None)

    @field_validator("name")
    @classmethod
    def validate_not_empty(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Field cannot be empty or whitespace")
        return v


class BranchUpdateRequestDTO(BaseModel):
    """Request DTO for updating a branch with snake_case fields."""

    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[int] = Field(None, ge=1)
    type: Optional[str] = Field(None, min_length=1, max_length=50)
    is_active: Optional[bool] = Field(None)
    location: Optional[LocationRequestDTO] = Field(None)
    phone: Optional[BranchPhoneRequestDTO] = Field(None)

    @field_validator("name")
    @classmethod
    def validate_not_empty(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Field cannot be empty or whitespace")
        return v
