from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from app.dtos.responses.pagination_dto import PaginationResponse


class ConsecutiveBranchRef(BaseModel):
    branch_id: str
    code: int
    name: str


class ConsecutiveTerminalRef(BaseModel):
    terminal_id: str
    code: int
    name: str


class ConsecutiveDocumentTypeRef(BaseModel):
    id: int
    code: str
    name: str


class ConsecutiveResponse(BaseModel):
    """Consecutive (document sequence counter) response DTO."""

    consecutive_id: str
    organization_id: str
    terminal_id: str
    document_type_id: int
    current_number: int
    document_consecutive: Optional[str] = None  # 20-digit branch+terminal+code+seq, when requested by the format endpoint
    # Context — filled on the list/detail/update endpoints, which join the
    # terminal, its branch and the document type.
    branch: Optional[ConsecutiveBranchRef] = None
    terminal: Optional[ConsecutiveTerminalRef] = None
    document_type: Optional[ConsecutiveDocumentTypeRef] = None
    # The 20-digit consecutive the NEXT document of this type will carry
    # (current_number + 1). Informational: the sales allocator owns the increment.
    next_document_consecutive: Optional[str] = None
    created_at: Optional[str] = None  # ISO timestamp
    updated_at: Optional[str] = None  # ISO timestamp
    created_by: str

    model_config = {"from_attributes": True}


class ConsecutiveListResponse(BaseModel):
    """List of consecutives with pagination."""

    data: List[ConsecutiveResponse]
    pagination: PaginationResponse


class ConsecutiveAdjustmentResponse(BaseModel):
    """One audited manual change to a consecutive counter."""

    adjustment_id: str
    consecutive_id: str
    previous_number: Optional[int] = None  # None = the edit created the counter
    new_number: int
    reason: str
    changed_by: str
    changed_on: str  # ISO timestamp


class ConsecutiveAdjustmentListResponse(BaseModel):
    data: List[ConsecutiveAdjustmentResponse]
