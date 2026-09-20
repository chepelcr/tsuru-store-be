from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


#: Digits an identification number must have, per Hacienda type code.
#:
#: A flat `min_length=9` was wrong in both directions: it rejected a passport
#: (variable, from 6) and accepted an 9-digit cédula jurídica, which must be 10.
#: These mirror `fe/pos-system/src/utils/idValidation.ts`, which is where the POS
#: validates the same field — the two must agree or the form accepts what the
#: API refuses.
#: Pasaporte — the one type whose number is not digits.
PASSPORT_CODE = "05"

ID_NUMBER_LENGTHS: dict = {
    "01": (9, 9),    # Cédula física
    "02": (10, 10),  # Cédula jurídica
    "03": (11, 12),  # DIMEX
    "04": (10, 10),  # NITE
    "05": (6, 50),   # Pasaporte / extranjero — variable
}


class IdentificationRequestDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: Optional[str] = Field(None, max_length=10)
    # Length is checked against the CODE below, not here: one bound cannot be
    # right for a 9-digit cédula and a passport at the same time.
    number: Optional[str] = Field(None, max_length=50)

    @model_validator(mode="after")
    def validate_number_length_for_code(self):
        """A number must have the number of digits its own type requires.

        Only digits are counted, so a masked `1-1234-5678` from the POS and the
        raw `112345678` it stores elsewhere both pass — the two client drawers
        disagree about whether to mask, and a document is not the place to find
        that out.
        """
        if not self.number or not self.code:
            return self
        bounds = ID_NUMBER_LENGTHS.get(self.code)
        if bounds is None:
            return self
        # A passport is alphanumeric and counted whole; the Costa Rican types
        # are digits, counted after the mask is stripped — the POS's two client
        # drawers disagree about whether to store `1-1234-5678` or `112345678`,
        # and an API is not the place to discover that.
        if self.code == PASSPORT_CODE:
            length = len(self.number.strip())
        else:
            length = len("".join(c for c in self.number if c.isdigit()))
        low, high = bounds
        if not (low <= length <= high):
            expected = f"{low}" if low == high else f"{low}-{high}"
            raise ValueError(
                f"identification.number must have {expected} characters for "
                f"type '{self.code}'; got {length}"
            )
        return self


class PhoneRequestDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    country_code: Optional[str] = Field(None, max_length=10)
    area_code: Optional[str] = Field(None, max_length=10)
    number: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = Field(None, max_length=50)


class ResidenceRequestDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    state_id: Optional[int] = Field(None, ge=0)
    county_id: Optional[int] = Field(None, ge=0)
    district_id: Optional[int] = Field(None, ge=0)
    neighborhood_id: Optional[int] = Field(None, ge=0)
    address: Optional[str] = Field(None, max_length=500)


class ClientRequestDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    customer_type: Optional[int] = Field(None, ge=1, le=10)
    client_name: Optional[str] = Field(None)
    client_gln: Optional[str] = Field(None)
    identification: Optional[IdentificationRequestDTO] = Field(None)
    business_name: Optional[str] = Field(None, max_length=255)
    nationality: Optional[str] = Field(None, min_length=2, max_length=3)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[PhoneRequestDTO] = Field(None)
    residence: Optional[ResidenceRequestDTO] = Field(None)
    notes: Optional[str] = Field(None, description="Free-text notes about the customer")

    @model_validator(mode="after")
    def validate_at_least_one_field(self):
        """The client must be identifiable by SOME name, or by its GLN.

        `business_name` counts. It did not, and that is a real rejection rather
        than a theoretical one: the POS renders "Razón social" → `business_name`
        for an EMPRESA customer and never fills `client_name`, so every company
        without a GLN was refused — while the form's own guard checked
        `business_name || client_gln` and let it through. The two ends were
        enforcing different rules.
        """
        if not self.client_name and not self.business_name and not self.client_gln:
            raise ValueError(
                "At least one of client_name, business_name or client_gln is required"
            )
        return self
