"""Inbound branch discovery contract; counters are the last number already used."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class SyncDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class BranchPhoneDTO(SyncDTO):
    country_code: Optional[Union[str, int]] = Field(None, alias="countryCode")
    number: Optional[Union[str, int]] = None


class BranchResidenceDTO(SyncDTO):
    country_code: Optional[Union[str, int]] = Field(None, alias="countryCode")
    province_code: Optional[int] = Field(None, alias="provinceCode", ge=1)
    canton_code: Optional[int] = Field(None, alias="cantonCode", ge=1)
    district_code: Optional[int] = Field(None, alias="districtCode", ge=1)
    neighborhood_code: Optional[int] = Field(None, alias="neighborhoodCode", ge=1)
    address: Optional[str] = None


class BranchConsecutiveDTO(SyncDTO):
    document_type: str = Field(alias="documentType", pattern=r"^[0-9]{2}$")
    current_number: int = Field(alias="currentNumber", ge=0, le=9999999999, strict=True)


class BranchTerminalDTO(SyncDTO):
    number: int = Field(ge=1, le=99999, strict=True)
    name: Optional[str] = Field(None, max_length=255)
    consecutives: list[BranchConsecutiveDTO] = Field(default_factory=list)


class BranchSyncDTO(SyncDTO):
    number: int = Field(ge=1, le=999, strict=True)
    name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = None
    phone: Optional[BranchPhoneDTO] = None
    residence: Optional[BranchResidenceDTO] = None
    terminals: list[BranchTerminalDTO] = Field(default_factory=list)


class OrganizationBranchesPayload(SyncDTO):
    organization_id: str = Field(alias="organizationId", min_length=1, max_length=255)
    branches: list[BranchSyncDTO]


class OrganizationBranchesEvent(SyncDTO):
    id: str = Field(min_length=1)
    occurred_at: datetime = Field(alias="occurredAt")
    type_: Literal["OrganizationBranchesEvent"] = Field(alias="_type")
    event_type: Literal["SAVE_BRANCHES"] = Field(alias="eventType")
    data: OrganizationBranchesPayload
