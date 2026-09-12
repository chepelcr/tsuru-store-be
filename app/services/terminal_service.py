from __future__ import annotations

import logging
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from app.dtos.requests.terminal_request_dto import (
    TerminalCreateRequestDTO,
    TerminalUpdateRequestDTO,
)
from app.dtos.responses.pagination_dto import PaginationResponse
from app.dtos.responses.terminal_dto import TerminalListResponse, TerminalResponse
from app.enums.terminal_search_filters import TerminalSearchFilters
from app.models.terminal import Terminal
from app.repositories.branch_repository import BranchRepository
from app.repositories.terminal_repository import TerminalRepository
from app.utils.search_utils import SearchUtils

logger = logging.getLogger(__name__)


def get_terminals(
    organization_id: str,
    user_id: str,
    page: int = 1,
    page_size: int = 12,
    search: Optional[str] = None,
    branch_code: Optional[int] = None,
) -> TerminalListResponse:
    """Get all terminals for an organization, optionally filtered by branch code."""
    filters, order_by = (
        SearchUtils.parse_search_filter(search, Terminal, TerminalSearchFilters)
        if search
        else ([], None)
    )

    if branch_code is not None:
        # Resolve branch UUID from code
        with BranchRepository() as b_repo:
            branch = b_repo.find_by_code_and_organization(branch_code, organization_id)
        if branch:
            filters.append(Terminal.branch_id == branch.branch_id)
        else:
            # No matching branch → return empty
            return TerminalListResponse(
                data=[],
                pagination=PaginationResponse(page=page, page_size=page_size, total_elements=0, total_pages=0),
            )

    with TerminalRepository() as repo:
        terminals, total = repo.find_all_paginated(
            organization_id,
            filters=filters,
            order_by=order_by,
            page=page,
            page_size=page_size,
        )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return TerminalListResponse(
        data=[_map_terminal(t) for t in terminals],
        pagination=PaginationResponse(
            page=page,
            page_size=page_size,
            total_elements=total,
            total_pages=total_pages,
        ),
    )


def get_terminal_by_code(
    organization_id: str,
    user_id: str,
    terminal_code: int,
    branch_code: int,
) -> Optional[TerminalResponse]:
    """Get a single terminal by its integer code within a branch."""
    with BranchRepository() as b_repo:
        branch = b_repo.find_by_code_and_organization(branch_code, organization_id)
    if not branch:
        return None

    with TerminalRepository() as repo:
        terminal = repo.find_by_code_and_branch(terminal_code, str(branch.branch_id), organization_id)
    if not terminal:
        return None
    return _map_terminal(terminal)


def create_terminal(
    organization_id: str,
    user_id: str,
    branch_code: int,
    dto: TerminalCreateRequestDTO,
) -> TerminalResponse:
    with BranchRepository() as b_repo:
        branch = b_repo.find_by_code_and_organization(branch_code, organization_id)
        
        if not branch:
            raise ValueError(
                f"Branch does not exist or does not belong to this organization"
            )
                
        """Create a new terminal."""
        with TerminalRepository() as repo:
            # Per branch, not per organization: Hacienda numbers terminals
            # within a branch, so the same code in another branch is fine.
            existing = repo.find_by_code_and_branch(
                dto.code, str(branch.branch_id), organization_id
            )
            if existing:
                raise ValueError(
                    f"Terminal code '{dto.code}' already exists in this branch"
                )

            if dto.device_id:
                existing_device = repo.find_by_device_id(dto.device_id)
                if existing_device:
                    raise ValueError(
                        f"Device ID '{dto.device_id}' is already registered to another terminal"
                    )

            terminal_id = uuid.uuid4()
            now = datetime.now(timezone.utc)

            terminal = Terminal(
                terminal_id=terminal_id,
                organization_id=organization_id,
                branch_id=branch.branch_id,
                name=dto.name,
                code=dto.code,
                device_id=dto.device_id,
                registered_at=now,
            )
            terminal = repo.save(terminal)

        return _map_terminal(terminal)


def update_terminal(
    organization_id: str,
    user_id: str,
    terminal_code: int,
    branch_code: int,
    dto: TerminalUpdateRequestDTO,
) -> Optional[TerminalResponse]:
    """Update an existing terminal identified by integer code."""
    with BranchRepository() as b_repo:
        branch = b_repo.find_by_code_and_organization(branch_code, organization_id)
    if not branch:
        return None

    with TerminalRepository() as repo:
        terminal = repo.find_by_code_and_branch(terminal_code, str(branch.branch_id), organization_id)
        if not terminal:
            return None

        if dto.code is not None and dto.code != terminal.code:
            existing = repo.find_by_code_and_branch(
                dto.code, str(branch.branch_id), organization_id
            )
            if existing:
                raise ValueError(
                    f"Terminal code '{dto.code}' already exists in this branch"
                )

        if dto.device_id and dto.device_id != terminal.device_id:
            existing_device = repo.find_by_device_id(dto.device_id)
            if existing_device:
                raise ValueError(
                    f"Device ID '{dto.device_id}' is already registered to another terminal"
                )

        if dto.name is not None:
            terminal.name = dto.name
        if dto.code is not None:
            terminal.code = dto.code
        if dto.device_id is not None:
            terminal.device_id = dto.device_id

        terminal = repo.save(terminal)

    return _map_terminal(terminal)


def update_terminal_status(
    organization_id: str,
    user_id: str,
    terminal_code: int,
    branch_code: int,
    status: int,
) -> Optional[TerminalResponse]:
    """Update the status of a terminal identified by integer code."""
    with BranchRepository() as b_repo:
        branch = b_repo.find_by_code_and_organization(branch_code, organization_id)
    if not branch:
        return None

    with TerminalRepository() as repo:
        terminal = repo.find_by_code_and_branch(terminal_code, str(branch.branch_id), organization_id)
        if not terminal:
            return None

        terminal.status = status
        if status == 3:
            terminal.deleted_on = datetime.now(timezone.utc)

        terminal = repo.save(terminal)

    return _map_terminal(terminal)


def delete_terminal(
    organization_id: str,
    user_id: str,
    terminal_code: int,
    branch_code: int,
) -> bool:
    """Delete a terminal by integer code if it has no active assignments."""
    with BranchRepository() as b_repo:
        branch = b_repo.find_by_code_and_organization(branch_code, organization_id)
    if not branch:
        return False

    with TerminalRepository() as repo:
        terminal = repo.find_by_code_and_branch(terminal_code, str(branch.branch_id), organization_id)
        if not terminal:
            return False

        terminal_id_str = str(terminal.terminal_id)
        if repo.has_active_assignments(terminal_id_str):
            raise ValueError(
                "Cannot delete terminal with active assignments. "
                "Please end all active assignments first."
            )

        return repo.delete(terminal_id_str)


def _map_terminal(terminal: Terminal) -> TerminalResponse:
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
