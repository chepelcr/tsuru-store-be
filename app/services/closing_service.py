from __future__ import annotations

import logging
from typing import List, Optional
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.dtos.requests.closing_request_dto import (
    ClosingCreateRequestDTO,
    ClosingUpdateRequestDTO,
)
from app.dtos.responses.closing_dto import ClosingListResponse, ClosingResponse
from app.dtos.responses.pagination_dto import PaginationResponse
from app.enums.closing_search_filters import ClosingSearchFilters
from app.models.closing import Closing
from app.repositories.closing_repository import ClosingRepository
from app.utils.search_utils import SearchUtils

logger = logging.getLogger(__name__)

# Map integer status codes to closing string statuses
_STATUS_INT_TO_STR = {
    1: "pending",
    2: "approved",
    3: "rejected",
}


def get_closings(
    organization_id: str,
    user_id: str,
    page: int = 1,
    page_size: int = 12,
    search: Optional[str] = None,
) -> ClosingListResponse:
    """Get all closings for an organization with pagination and optional filters."""
    filters, order_by = (
        SearchUtils.parse_search_filter(search, Closing, ClosingSearchFilters)
        if search
        else ([], None)
    )

    with ClosingRepository() as repo:
        closings, total = repo.find_all_paginated(
            organization_id,
            filters=filters,
            order_by=order_by,
            page=page,
            page_size=page_size,
        )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return ClosingListResponse(
        data=[_map_closing(c) for c in closings],
        pagination=PaginationResponse(
            page=page,
            page_size=page_size,
            total_elements=total,
            total_pages=total_pages,
        ),
    )


def get_closing(
    organization_id: str, user_id: str, closing_id: str
) -> Optional[ClosingResponse]:
    """Get a single closing by ID."""
    with ClosingRepository() as repo:
        closing = repo.find_by_id_and_organization(closing_id, organization_id)
    if not closing:
        return None
    return _map_closing(closing)


def create_closing(
    organization_id: str,
    user_id: str,
    dto: ClosingCreateRequestDTO,
) -> ClosingResponse:
    """Create a new closing."""
    with ClosingRepository() as repo:
        # Validate assignment exists and belongs to organization
        if not repo.validate_assignment_exists(dto.assignment_id, organization_id):
            raise ValueError(
                f"Assignment '{dto.assignment_id}' does not exist or does not belong to this organization"
            )

        # Check if closing already exists for this assignment
        existing_closing = repo.find_by_assignment(dto.assignment_id)
        if existing_closing:
            raise ValueError(
                f"A closing already exists for assignment '{dto.assignment_id}' (closing_id: {existing_closing.closing_id})"
            )

        # Get assignment details
        assignment = repo.get_assignment_details(dto.assignment_id)
        if not assignment:
            raise ValueError(f"Assignment '{dto.assignment_id}' not found")

        # Calculate expected amounts from orders
        expected_amounts = repo.calculate_expected_amounts(dto.assignment_id)
        if not expected_amounts.available:
            # Recorded on the closing itself, because `cash_difference` is a
            # GENERATED column (`declared - expected`): with an unavailable
            # expectation every difference equals the declared amount, which reads
            # as a surplus. Whoever reviews this closing has to be able to see
            # that the expectation was never measured.
            logger.warning(
                "Closing for assignment %s is being created with UNAVAILABLE "
                "expected amounts; its difference columns will equal the declared "
                "amounts and must not be read as a surplus.",
                dto.assignment_id,
            )

        # Calculate declared total
        declared_total = dto.declared_cash + dto.declared_sinpe + dto.declared_card

        closing_id = uuid.uuid4()

        closing = Closing(
            closing_id=closing_id,
            organization_id=organization_id,
            session_id=assignment.session_id,
            assignment_id=uuid.UUID(dto.assignment_id),
            branch_id=assignment.branch_id,
            terminal_id=assignment.terminal_id,
            cashier_id=assignment.user_id,
            # Expected amounts (from system)
            expected_cash=expected_amounts.expected_cash,
            expected_sinpe=expected_amounts.expected_sinpe,
            expected_card=expected_amounts.expected_card,
            expected_total=expected_amounts.expected_total,
            # Declared amounts (from cashier)
            declared_cash=dto.declared_cash,
            declared_sinpe=dto.declared_sinpe,
            declared_card=dto.declared_card,
            declared_total=declared_total,
            notes=dto.notes,
            status='pending',
        )
        closing = repo.save(closing)

    return _map_closing(closing)


def update_closing(
    organization_id: str,
    user_id: str,
    closing_id: str,
    dto: ClosingUpdateRequestDTO,
    is_manager: bool = True,
) -> Optional[ClosingResponse]:
    """
    Update an existing closing (typically for approval/rejection).

    Args:
        organization_id: Organization identifier
        user_id: User making the update
        closing_id: Closing identifier
        dto: Update data
        is_manager: Whether the user has manager role (default: True for backward compatibility)
                   In production, this should be determined by API Gateway/auth layer

    Raises:
        PermissionError: If user attempts to approve/reject without manager role

    Note:
        Authorization enforcement should be done at API Gateway/auth layer.
        This service-level check provides defense in depth.
    """
    with ClosingRepository() as repo:
        closing = repo.find_by_id_and_organization(closing_id, organization_id)
        if not closing:
            return None

        # Update status if provided
        if dto.status is not None:
            # Requirement 5.7: Only managers can approve or reject closings
            if dto.status in ['approved', 'rejected'] and not is_manager:
                raise PermissionError(
                    "Only managers can approve or reject closings. "
                    "User must have manager role for this organization."
                )

            closing.status = dto.status
            # When approving or rejecting, set reviewed_by and reviewed_at
            if dto.status in ['approved', 'rejected']:
                closing.reviewed_by = dto.reviewed_by or user_id
                closing.reviewed_at = datetime.now(timezone.utc)

        # Update notes if provided
        if dto.notes is not None:
            closing.notes = dto.notes

        closing = repo.save(closing)

    return _map_closing(closing)


def update_closing_status(
    organization_id: str,
    user_id: str,
    closing_id: str,
    status: int,
) -> Optional[ClosingResponse]:
    """Update closing status using integer status codes.

    Maps: 1 -> 'pending', 2 -> 'approved', 3 -> 'rejected'.
    For statuses 2 and 3, sets reviewed_by and reviewed_at.
    """
    status_str = _STATUS_INT_TO_STR.get(status)
    if status_str is None:
        raise ValueError(f"Invalid closing status code: {status}. Must be 1 (pending), 2 (approved), or 3 (rejected).")

    with ClosingRepository() as repo:
        closing = repo.find_by_id_and_organization(closing_id, organization_id)
        if not closing:
            return None

        closing.status = status_str
        if status in (2, 3):
            closing.reviewed_by = user_id
            closing.reviewed_at = datetime.now(timezone.utc)

        closing = repo.save(closing)

    return _map_closing(closing)


def delete_closing(organization_id: str, user_id: str, closing_id: str) -> bool:
    """Delete a closing."""
    with ClosingRepository() as repo:
        closing = repo.find_by_id_and_organization(closing_id, organization_id)
        if not closing:
            return False

        return repo.delete(closing_id)


def _map_closing(closing: Closing) -> ClosingResponse:
    """Map Closing model to ClosingResponse DTO."""
    return ClosingResponse(
        closing_id=str(closing.closing_id),
        organization_id=closing.organization_id,
        session_id=str(closing.session_id),
        assignment_id=str(closing.assignment_id),
        branch_id=str(closing.branch_id),
        terminal_id=str(closing.terminal_id) if closing.terminal_id else None,
        cashier_id=closing.cashier_id,
        # Expected amounts
        expected_cash=float(closing.expected_cash),
        expected_sinpe=float(closing.expected_sinpe),
        expected_card=float(closing.expected_card),
        expected_total=float(closing.expected_total),
        # Declared amounts
        declared_cash=float(closing.declared_cash),
        declared_sinpe=float(closing.declared_sinpe),
        declared_card=float(closing.declared_card),
        declared_total=float(closing.declared_total),
        # Differences (calculated by database)
        cash_difference=float(closing.cash_difference) if closing.cash_difference is not None else 0.0,
        sinpe_difference=float(closing.sinpe_difference) if closing.sinpe_difference is not None else 0.0,
        card_difference=float(closing.card_difference) if closing.card_difference is not None else 0.0,
        total_difference=float(closing.total_difference) if closing.total_difference is not None else 0.0,
        notes=closing.notes,
        status=closing.status,
        reviewed_by=closing.reviewed_by,
        reviewed_at=closing.reviewed_at.isoformat() if closing.reviewed_at else None,
        created_at=closing.created_on.isoformat() if closing.created_on else "",
    )
