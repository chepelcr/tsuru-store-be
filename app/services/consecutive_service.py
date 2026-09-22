from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.dtos.requests.consecutive_request_dto import (
    MAX_CONSECUTIVE_NUMBER,
    ConsecutiveCreateRequestDTO,
    ConsecutiveUpdateRequestDTO,
)
from app.dtos.responses.consecutive_dto import (
    ConsecutiveAdjustmentListResponse,
    ConsecutiveAdjustmentResponse,
    ConsecutiveBranchRef,
    ConsecutiveDocumentTypeRef,
    ConsecutiveListResponse,
    ConsecutiveResponse,
    ConsecutiveTerminalRef,
)
from app.dtos.responses.pagination_dto import PaginationResponse
from app.enums.consecutive_search_filters import ConsecutiveSearchFilters
from app.models.branch import Branch
from app.models.consecutive import Consecutive
from app.models.consecutive_adjustment import ConsecutiveAdjustment
from app.models.document_type import DocumentType
from app.models.terminal import Terminal
from app.repositories.branch_repository import BranchRepository
from app.repositories.consecutive_repository import ConsecutiveRepository
from app.repositories.document_type_repository import DocumentTypeRepository
from app.repositories.terminal_repository import TerminalRepository
from app.utils.search_utils import SearchUtils

logger = logging.getLogger(__name__)


class ConsecutiveConflictError(Exception):
    """A manual edit that would not raise the counter.

    Carries the value that is actually stored, so the caller can show it: by
    the time the user confirms, a sale may already have moved it.
    """

    def __init__(self, current_number: int, requested: int):
        self.current_number = current_number
        self.requested = requested
        super().__init__(
            f"The consecutive can only be raised: requested {requested}, "
            f"current is {current_number}"
        )


def get_consecutives(
    organization_id: str,
    user_id: str,
    page: int = 1,
    page_size: int = 12,
    search: Optional[str] = None,
) -> ConsecutiveListResponse:
    """Get all consecutives for an organization with pagination and optional filters."""
    filters, order_by = (
        SearchUtils.parse_search_filter(search, Consecutive, ConsecutiveSearchFilters)
        if search
        else ([], None)
    )

    with ConsecutiveRepository() as repo:
        items, total = repo.find_all_paginated(
            organization_id,
            filters=filters,
            order_by=order_by,
            page=page,
            page_size=page_size,
        )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return ConsecutiveListResponse(
        data=[_map_with_context(*row) for row in items],
        pagination=PaginationResponse(
            page=page,
            page_size=page_size,
            total_elements=total,
            total_pages=total_pages,
        ),
    )


def get_consecutive(
    organization_id: str, user_id: str, consecutive_id: str
) -> Optional[ConsecutiveResponse]:
    """Get a single consecutive by ID."""
    with ConsecutiveRepository() as repo:
        row = repo.find_with_context(consecutive_id, organization_id)
    return _map_with_context(*row) if row else None


def create_consecutive(
    organization_id: str,
    user_id: str,
    dto: ConsecutiveCreateRequestDTO,
) -> ConsecutiveResponse:
    """Create a new consecutive sequence counter."""
    # Validate terminal belongs to org
    with TerminalRepository() as t_repo:
        terminal = t_repo.find_by_id_and_organization(dto.terminal_id, organization_id)
    if not terminal:
        raise ValueError(f"Terminal {dto.terminal_id} not found in organization")

    # Validate document type exists
    with DocumentTypeRepository() as dt_repo:
        doc_type = dt_repo.find_by_id(dto.document_type_id)
    if not doc_type:
        raise ValueError(f"Document type {dto.document_type_id} not found")

    with ConsecutiveRepository() as repo:
        # Check uniqueness
        existing = repo.find_by_terminal_and_doc_type(
            dto.terminal_id, dto.document_type_id, organization_id
        )
        if existing:
            raise ValueError(
                f"Consecutive for terminal {dto.terminal_id} and document type "
                f"{dto.document_type_id} already exists"
            )

        initial = dto.initial_number or 0
        reason = (dto.reason or "").strip()
        # Starting a counter past zero is a manual adjustment: it decides the
        # number of the next fiscal document, so it is audited like an edit.
        if initial > 0 and len(reason) < 3:
            raise ValueError("A reason is required to start a consecutive above 0")

        consecutive = Consecutive(
            organization_id=organization_id,
            terminal_id=uuid.UUID(dto.terminal_id),
            document_type_id=dto.document_type_id,
            current_number=initial,
            created_by=user_id,
        )
        saved = repo.save(consecutive)
        if initial > 0:
            repo.add_adjustment(ConsecutiveAdjustment(
                organization_id=organization_id,
                consecutive_id=saved.consecutive_id,
                terminal_id=saved.terminal_id,
                document_type_id=saved.document_type_id,
                previous_number=None,
                new_number=initial,
                reason=reason,
                changed_by=user_id,
            ))

    return get_consecutive(organization_id, user_id, str(saved.consecutive_id)) or _map_consecutive(saved)


def update_consecutive_number(
    organization_id: str,
    user_id: str,
    consecutive_id: str,
    dto: ConsecutiveUpdateRequestDTO,
) -> Optional[ConsecutiveResponse]:
    """Manually raise a consecutive counter, audited.

    **Raise-only.** `current_number` is the last number already issued: the
    sales allocator writes every number it hands out, and the Hacienda-history
    sync only ever raises it (GREATEST). So "strictly greater than current" is
    exactly "never re-issues a number" — lowering it would make the next
    documents reuse claves Hacienda has already accepted, and it rejects them
    as duplicates. There is deliberately no override.

    The row is locked FOR UPDATE — the same lock the allocator takes — so the
    comparison and the write cannot straddle a sale being numbered.
    """
    reason = dto.reason.strip()
    if len(reason) < 3:
        raise ValueError("A reason is required")
    if dto.current_number > MAX_CONSECUTIVE_NUMBER:
        raise ValueError("The consecutive cannot exceed 10 digits")

    with ConsecutiveRepository() as repo:
        consecutive = repo.lock_for_update(consecutive_id, organization_id)
        if not consecutive:
            return None
        previous = consecutive.current_number
        if dto.current_number <= previous:
            raise ConsecutiveConflictError(previous, dto.current_number)

        consecutive.current_number = dto.current_number
        repo.add_adjustment(ConsecutiveAdjustment(
            organization_id=organization_id,
            consecutive_id=consecutive.consecutive_id,
            terminal_id=consecutive.terminal_id,
            document_type_id=consecutive.document_type_id,
            previous_number=previous,
            new_number=dto.current_number,
            reason=reason,
            changed_by=user_id,
        ))
        logger.warning(
            "Consecutive %s manually raised %s -> %s by %s (org %s): %s",
            consecutive_id, previous, dto.current_number, user_id, organization_id, reason,
        )

    return get_consecutive(organization_id, user_id, consecutive_id)


def get_adjustments(
    organization_id: str, consecutive_id: str, limit: int = 50
) -> Optional[ConsecutiveAdjustmentListResponse]:
    with ConsecutiveRepository() as repo:
        if not repo.find_by_id_and_org(consecutive_id, organization_id):
            return None
        rows = repo.find_adjustments(consecutive_id, organization_id, limit=limit)
    return ConsecutiveAdjustmentListResponse(data=[
        ConsecutiveAdjustmentResponse(
            adjustment_id=str(a.adjustment_id),
            consecutive_id=str(a.consecutive_id),
            previous_number=a.previous_number,
            new_number=a.new_number,
            reason=a.reason,
            changed_by=a.changed_by,
            changed_on=a.changed_on.isoformat() if a.changed_on else "",
        )
        for a in rows
    ])


def get_next_number(
    organization_id: str, terminal_id: str, document_type_id: int
) -> Optional[ConsecutiveResponse]:
    """Atomically increment and return the next consecutive number."""
    with ConsecutiveRepository() as repo:
        existing = repo.find_by_terminal_and_doc_type(
            terminal_id, document_type_id, organization_id
        )
        if not existing:
            return None
        updated = repo.increment_and_get(str(existing.consecutive_id), organization_id)
    return _map_consecutive(updated) if updated else None


def update_consecutive_status(
    organization_id: str,
    user_id: str,
    consecutive_id: str,
    status: int,
) -> Optional[ConsecutiveResponse]:
    """Soft-delete a consecutive (status 3). Any other status is a no-op.

    `consecutives` has no status column — this used to assign `.status` on the
    model, which SQLAlchemy silently ignored, so only the delete ever
    persisted. That is now the documented behaviour rather than an accident.
    """
    with ConsecutiveRepository() as repo:
        consecutive = repo.find_by_id_and_org(consecutive_id, organization_id)
        if not consecutive:
            return None

        if status == 3:
            consecutive.deleted_on = datetime.now(timezone.utc)
            repo.save(consecutive)

    return _map_consecutive(consecutive)


def format_consecutive_by_code(
    organization_id: str,
    user_id: str,
    terminal_id: str,
    document_type_code: str,
) -> Optional[ConsecutiveResponse]:
    """Resolve doc-type code → id, locate/create the consecutive row, and return it
    with `document_consecutive` formatted as branch(3) + terminal(5) + doc_type_code(2) + current_number(10).

    Does NOT increment current_number — the caller (e.g. sales-api) owns the atomic increment.
    """
    with TerminalRepository() as t_repo:
        terminal = t_repo.find_by_id_and_organization(terminal_id, organization_id)
    if not terminal:
        raise ValueError(f"Terminal {terminal_id} not found in organization")

    with BranchRepository() as b_repo:
        branch = b_repo.find_by_id_and_organization(str(terminal.branch_id), organization_id)
    if not branch:
        raise ValueError(
            f"Branch {terminal.branch_id} for terminal {terminal_id} not found in organization"
        )

    with DocumentTypeRepository() as dt_repo:
        doc_type = dt_repo.find_by_code(document_type_code)
    if not doc_type:
        raise ValueError(f"Document type code {document_type_code} not found")

    with ConsecutiveRepository() as repo:
        consecutive = repo.find_by_terminal_and_doc_type(
            terminal_id, doc_type.id, organization_id
        )
        if not consecutive:
            consecutive = Consecutive(
                organization_id=organization_id,
                terminal_id=uuid.UUID(terminal_id) if isinstance(terminal_id, str) else terminal_id,
                document_type_id=doc_type.id,
                current_number=0,
                created_by=user_id,
            )
            consecutive = repo.save(consecutive)

    formatted = format_document_consecutive(
        branch.code, terminal.code, document_type_code, consecutive.current_number
    )

    response = _map_consecutive(consecutive)
    response.document_consecutive = formatted
    return response


def format_document_consecutive(
    branch_code: int, terminal_code: int, document_type_code: str, number: int
) -> str:
    """Hacienda's 20-digit consecutive: branch(3) + terminal(5) + type(2) + number(10)."""
    return (
        f"{branch_code:03d}"
        f"{terminal_code:05d}"
        f"{document_type_code.zfill(2)}"
        f"{number:010d}"
    )


def _map_with_context(
    c: Consecutive, terminal: Terminal, branch: Branch, doc_type: DocumentType
) -> ConsecutiveResponse:
    response = _map_consecutive(c)
    response.branch = ConsecutiveBranchRef(
        branch_id=str(branch.branch_id), code=branch.code, name=branch.name
    )
    response.terminal = ConsecutiveTerminalRef(
        terminal_id=str(terminal.terminal_id), code=terminal.code, name=terminal.name
    )
    response.document_type = ConsecutiveDocumentTypeRef(
        id=doc_type.id, code=doc_type.code, name=doc_type.description
    )
    next_number = c.current_number + 1
    if next_number <= MAX_CONSECUTIVE_NUMBER:
        response.next_document_consecutive = format_document_consecutive(
            branch.code, terminal.code, doc_type.code, next_number
        )
    return response


def _map_consecutive(c: Consecutive) -> ConsecutiveResponse:
    """Map Consecutive model to ConsecutiveResponse DTO."""
    return ConsecutiveResponse(
        consecutive_id=str(c.consecutive_id),
        organization_id=c.organization_id,
        terminal_id=str(c.terminal_id),
        document_type_id=c.document_type_id,
        current_number=c.current_number,
        created_at=c.created_on.isoformat() if c.created_on else None,
        updated_at=c.updated_on.isoformat() if c.updated_on else None,
        created_by=c.created_by,
    )
