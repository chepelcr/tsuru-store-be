from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class BranchTypeResponse(BaseModel):
    """Branch type response DTO.

    The identifier is exposed as `id` (not `branch_type_id`) because that is the
    field name in the POS `BranchTypeOption` contract this catalog feeds.
    """

    id: str
    organization_id: str
    code: str
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    sort_order: int = 0
    is_default: bool = False
    status: int  # 1=Active 2=Inactive 3=Deleted
    created_at: Optional[str] = None  # ISO timestamp
    updated_at: Optional[str] = None  # ISO timestamp

    model_config = {"from_attributes": True}


class BranchTypeListResponse(BaseModel):
    """The org's branch-type catalog.

    Unpaginated on purpose — it is a small, fully-loaded selector catalog, and the
    POS renders every entry at once.
    """

    data: List[BranchTypeResponse]
