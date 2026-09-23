from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.dtos.responses.pagination_dto import PaginationResponse


class IdentificationResponse(BaseModel):
    model_config = {"from_attributes": True}
    
    code: Optional[str] = Field(None)
    number: Optional[str] = Field(None)


class PhoneResponse(BaseModel):
    model_config = {"from_attributes": True}
    
    #: ISO numeric country code (188) — the key the form's country select uses.
    country_code: Optional[str] = Field(None)
    #: Dialing code (506) from the countries catalog — what people read.
    dial_code: Optional[str] = Field(None)
    #: Area code after the catalog's dash (``+1-869`` → ``869``), else None.
    dial_area: Optional[str] = Field(None)
    area_code: Optional[str] = Field(None)
    number: Optional[str] = Field(None)
    description: Optional[str] = Field(None)


class ResidenceResponse(BaseModel):
    model_config = {"from_attributes": True}
    
    state_id: Optional[int] = Field(None)
    county_id: Optional[int] = Field(None)
    district_id: Optional[int] = Field(None)
    neighborhood_id: Optional[int] = Field(None)
    address: Optional[str] = Field(None)


class ClientResponse(BaseModel):
    client_id: str = Field(...)
    company_id: str = Field(...)
    customer_type: Optional[int] = Field(None)
    client_name: Optional[str] = Field(None)
    client_gln: Optional[str] = Field(None)
    status: int = Field(...)
    identification: Optional[IdentificationResponse] = Field(None)
    business_name: Optional[str] = Field(None)
    nationality: Optional[str] = Field(None)
    email: Optional[str] = Field(None)
    phone: Optional[PhoneResponse] = Field(None)
    residence: Optional[ResidenceResponse] = Field(None)
    notes: Optional[str] = Field(None, description="Free-text notes about the customer")

    model_config = {"from_attributes": True}


class ClientListResponse(BaseModel):
    data: List[ClientResponse]
    pagination: PaginationResponse
