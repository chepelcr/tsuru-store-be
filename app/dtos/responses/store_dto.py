from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.dtos.responses.pagination_dto import PaginationResponse


class StoreResponse(BaseModel):
    store_id: str = Field(...)
    company_id: str = Field(...)
    client_id: str = Field(...)
    store_code: str = Field(...)
    store_name: Optional[str] = Field(None)
    slot_id: Optional[str] = Field(None)
    chain: Optional[str] = Field(None)
    gln: Optional[str] = Field(None)

    model_config = {"from_attributes": True}


class StoreListResponse(BaseModel):
    data: List[StoreResponse]
    pagination: PaginationResponse


class StoreUploadResponse(BaseModel):
    """Result of `POST .../stores/upload`.

    The route had no `response_model`, so this two-field shape existed only as a
    dict literal in the controller. `message` is human copy for the toast and
    `count` is the number the caller actually acts on — both are returned because
    the POS shows the first and logs the second.
    """

    message: str
    count: int
