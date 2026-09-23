from __future__ import annotations

import logging
from typing import Dict, List, Optional
import uuid
from datetime import datetime, timezone

from app.dtos.requests.branch_request_dto import (
    BranchCreateRequestDTO,
    BranchUpdateRequestDTO,
)
from app.dtos.responses.branch_dto import BranchListResponse, BranchResponse, LocationResponse
from app.dtos.responses.client_dto import PhoneResponse
from app.dtos.responses.pagination_dto import PaginationResponse
from app.dtos.responses.terminal_dto import TerminalResponse
from app.enums.branch_search_filters import BranchSearchFilters
from app.models.branch import Branch
from app.repositories.branch_repository import BranchRepository
from app.repositories.branch_type_repository import BranchTypeRepository
from app.repositories.terminal_repository import TerminalRepository
from app.utils.search_utils import SearchUtils

logger = logging.getLogger(__name__)


def get_branches(
    organization_id: str,
    user_id: str,
    page: int = 1,
    page_size: int = 12,
    search: Optional[str] = None,
    branch_type: Optional[str] = None,
) -> BranchListResponse:
    """Get all branches for an organization with pagination and optional filters."""
    filters, order_by = (
        SearchUtils.parse_search_filter(search, Branch, BranchSearchFilters)
        if search
        else ([], None)
    )

    # Apply branch_type filter outside of search string if provided
    if branch_type is not None:
        from sqlalchemy import and_
        from app.models.branch import Branch as BranchModel
        filters = list(filters)
        filters.append(BranchModel.type == branch_type)

    with BranchRepository() as repo:
        branches, total = repo.find_all_paginated(
            organization_id,
            filters=filters,
            order_by=order_by,
            page=page,
            page_size=page_size,
        )

    # Batch-load terminals for all branches
    branch_ids = [str(b.branch_id) for b in branches]
    terminals_map: Dict[str, List] = {}
    if branch_ids:
        with TerminalRepository() as t_repo:
            terminals_map = t_repo.find_all_by_branch_ids(branch_ids)

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return BranchListResponse(
        data=[_map_branch(b, terminals_map=terminals_map) for b in branches],
        pagination=PaginationResponse(
            page=page,
            page_size=page_size,
            total_elements=total,
            total_pages=total_pages,
        ),
    )


def get_branch(
    organization_id: str, user_id: str, branch_code: int
) -> Optional[BranchResponse]:
    """Get a single branch by integer code, embedding its terminals."""
    with BranchRepository() as repo:
        branch = repo.find_by_code_and_organization(branch_code, organization_id)
    if not branch:
        return None
    return _map_branch(branch)


def _validate_branch_type(organization_id: str, code: Optional[str]) -> None:
    """Reject a branch type that is not in the organization's own catalog.

    The DTO used to pin this to Literal['stand','restaurant']. TSR-139 replaced
    those two kinds with a per-org `branch_types` catalog and dropped the CHECK
    constraint, which left the Literal both too narrow (a swept branch carries
    the org's first catalog code, e.g. 'shop', and could not be saved back
    through this API) and the only validation there was. Validate against the
    catalog instead, so the check follows the data rather than a frozen pair.
    """
    if code is None:
        return
    with BranchTypeRepository() as type_repo:
        allowed = {row.code for row in type_repo.find_all_by_organization(organization_id)}
    # An org with no catalog yet keeps the two legacy defaults, matching the
    # seed in migration z6b7c8d9e0f1.
    if not allowed:
        allowed = {"stand", "restaurant"}
    if code not in allowed:
        raise ValueError(
            f"Branch type '{code}' is not in this organization's catalog "
            f"({', '.join(sorted(allowed))})"
        )


def create_branch(
    organization_id: str,
    user_id: str,
    dto: BranchCreateRequestDTO,
) -> BranchResponse:
    """Create a new branch."""
    _validate_branch_type(organization_id, dto.type)
    with BranchRepository() as repo:
        # Check code uniqueness within organization
        existing = repo.find_by_code_and_organization(dto.code, organization_id)
        if existing:
            raise ValueError(
                f"Branch code '{dto.code}' already exists in this organization"
            )

        branch_id = uuid.uuid4()

        loc = dto.location
        branch = Branch(
            branch_id=branch_id,
            organization_id=organization_id,
            name=dto.name,
            code=dto.code,
            type=dto.type,
            state_id=loc.state_id if loc else None,
            county_id=loc.county_id if loc else None,
            district_id=loc.district_id if loc else None,
            neighborhood_id=loc.neighborhood_id if loc else None,
            address=loc.address if loc else None,
            phone_country_code=dto.phone.country_code if dto.phone else None,
            phone_number=dto.phone.number if dto.phone else None,
            created_by=user_id,
        )
        branch = repo.save(branch)

    return _map_branch(branch)


def update_branch(
    organization_id: str,
    user_id: str,
    branch_code: int,
    dto: BranchUpdateRequestDTO,
) -> Optional[BranchResponse]:
    """Update an existing branch by integer code."""
    _validate_branch_type(organization_id, dto.type)
    with BranchRepository() as repo:
        branch = repo.find_by_code_and_organization(branch_code, organization_id)
        if not branch:
            return None

        # Check code uniqueness if updating code
        if dto.code and dto.code != branch.code:
            existing = repo.find_by_code_and_organization(dto.code, organization_id)
            if existing:
                raise ValueError(
                    f"Branch code '{dto.code}' already exists in this organization"
                )

        # Update fields
        if dto.name is not None:
            branch.name = dto.name
        if dto.code is not None:
            branch.code = dto.code
        if dto.type is not None:
            branch.type = dto.type
        if dto.location is not None:
            loc = dto.location
            if loc.state_id is not None:
                branch.state_id = loc.state_id
            if loc.county_id is not None:
                branch.county_id = loc.county_id
            if loc.district_id is not None:
                branch.district_id = loc.district_id
            if loc.neighborhood_id is not None:
                branch.neighborhood_id = loc.neighborhood_id
            if loc.address is not None:
                branch.address = loc.address
        if dto.phone is not None:
            branch.phone_country_code = dto.phone.country_code
            branch.phone_number = dto.phone.number

        branch = repo.save(branch)

    return _map_branch(branch)


def update_branch_status(
    organization_id: str,
    user_id: str,
    branch_code: int,
    status: int,
) -> Optional[BranchResponse]:
    """Update the status of a branch by integer code. Status 3 (Deleted) sets deleted_on."""
    with BranchRepository() as repo:
        branch = repo.find_by_code_and_organization(branch_code, organization_id)
        if not branch:
            return None

        branch.status = status
        if status == 3:
            branch.deleted_on = datetime.now(timezone.utc)

        branch = repo.save(branch)

    return _map_branch(branch)


def delete_branch(organization_id: str, user_id: str, branch_code: int) -> bool:
    """Delete a branch by integer code if it has no active terminals or sessions."""
    with BranchRepository() as repo:
        branch = repo.find_by_code_and_organization(branch_code, organization_id)
        if not branch:
            return False

        branch_id_str = str(branch.branch_id)

        # Check for active terminals
        if repo.has_active_terminals(branch_id_str):
            raise ValueError(
                "Cannot delete branch with active terminals. "
                "Please deactivate or delete terminals first."
            )

        # Check for active sessions
        if repo.has_active_sessions(branch_id_str):
            raise ValueError(
                "Cannot delete branch with active sessions. "
                "Please end all active sessions first."
            )

        return repo.delete(branch_id_str)


def _map_branch(
    branch: Branch,
    terminals_map: Optional[Dict[str, list]] = None,
) -> BranchResponse:
    """Map Branch model to BranchResponse DTO."""
    # Load terminals for single-branch fetch (no terminals_map provided)
    if terminals_map is not None:
        raw_terminals = terminals_map.get(str(branch.branch_id), [])
    else:
        with TerminalRepository() as t_repo:
            raw_terminals = t_repo.find_all_by_branch(str(branch.branch_id))

    terminals = [_map_terminal_embed(t) for t in raw_terminals]

    has_location = any([
        branch.state_id, branch.county_id, branch.district_id,
        branch.neighborhood_id, branch.address,
    ])
    location = LocationResponse(
        state_id=branch.state_id,
        county_id=branch.county_id,
        district_id=branch.district_id,
        neighborhood_id=branch.neighborhood_id,
        address=branch.address,
    ) if has_location else None

    return BranchResponse(
        branch_id=str(branch.branch_id),
        organization_id=branch.organization_id,
        name=branch.name,
        code=branch.code,
        type=branch.type,
        status=branch.status,
        location=location,
        phone=PhoneResponse(
            country_code=branch.phone_country_code,
            dial_code=(branch.phone_country.dial_code if branch.phone_country
                       else branch.phone_country_code),
            dial_area=branch.phone_country.dial_area if branch.phone_country else None,
            number=branch.phone_number,
        ) if branch.phone_number else None,
        created_at=branch.created_on.isoformat() if branch.created_on else None,
        updated_at=branch.updated_on.isoformat() if branch.updated_on else None,
        created_by=branch.created_by,
        terminals=terminals,
    )


def _map_terminal_embed(terminal) -> TerminalResponse:
    """Map Terminal model to TerminalResponse DTO (used when embedding in branches)."""
    return TerminalResponse(
        terminal_id=str(terminal.terminal_id),
        organization_id=terminal.organization_id,
        branch_id=str(terminal.branch_id),
        name=terminal.name,
        code=terminal.code,
        device_id=terminal.device_id,
        status=terminal.status,
        registered_at=terminal.registered_at.isoformat() if terminal.registered_at else None,
        last_seen_at=terminal.last_seen_at.isoformat() if terminal.last_seen_at else None,
        created_at=terminal.created_on.isoformat() if terminal.created_on else None,
        updated_at=terminal.updated_on.isoformat() if terminal.updated_on else None,
    )
