from __future__ import annotations

import logging
import uuid

from app.dtos.requests.branch_type_request_dto import (
    BranchTypeCreateRequestDTO,
    BranchTypeUpdateRequestDTO,
)
from app.dtos.responses.branch_type_dto import BranchTypeListResponse, BranchTypeResponse
from app.models.branch_type import BranchType
from app.repositories.branch_type_repository import BranchTypeRepository

logger = logging.getLogger(__name__)


def get_branch_types(organization_id: str, user_id: str) -> BranchTypeListResponse:
    """The organization's branch-type catalog, in display order."""
    with BranchTypeRepository() as repo:
        repo.ensure_default_type(organization_id)
        branch_types = repo.find_all_by_organization(organization_id)
        repo.session.commit()

    return BranchTypeListResponse(data=[_map_branch_type(bt) for bt in branch_types])


def create_branch_type(
    organization_id: str,
    user_id: str,
    dto: BranchTypeCreateRequestDTO,
) -> BranchTypeResponse:
    """Create a branch type. Codes are unique per organization."""
    with BranchTypeRepository() as repo:
        existing = repo.find_by_code_and_organization(dto.code, organization_id)
        if existing:
            raise ValueError(
                f"Branch type code '{dto.code}' already exists in this organization"
            )

        branch_type = BranchType(
            branch_type_id=uuid.uuid4(),
            organization_id=organization_id,
            code=dto.code,
            name=dto.name,
            icon=dto.icon,
            color=dto.color,
            sort_order=dto.sort_order if dto.sort_order is not None else 0,
            # Set explicitly rather than leaning on the column default, which only
            # materialises at flush time — the mapped response reads it right after.
            status=1,
            is_default=False,
            created_by=user_id,
        )
        branch_type = repo.save(branch_type)

    return _map_branch_type(branch_type)


def update_branch_type(
    organization_id: str,
    user_id: str,
    branch_type_id: str,
    dto: BranchTypeUpdateRequestDTO,
) -> BranchTypeResponse | None:
    """Update a branch type's presentation fields. `code` is immutable — branches
    reference it by value, so renaming it would orphan them."""
    with BranchTypeRepository() as repo:
        branch_type = repo.find_by_id_and_organization(branch_type_id, organization_id)
        if not branch_type:
            return None

        if dto.name is not None:
            branch_type.name = dto.name
        if dto.icon is not None:
            branch_type.icon = dto.icon
        if dto.color is not None:
            branch_type.color = dto.color
        if dto.sort_order is not None:
            branch_type.sort_order = dto.sort_order

        branch_type = repo.save(branch_type)

    return _map_branch_type(branch_type)


def delete_branch_type(organization_id: str, user_id: str, branch_type_id: str) -> bool:
    """Delete a branch type, provided no branch still uses its code."""
    with BranchTypeRepository() as repo:
        branch_type = repo.find_by_id_and_organization(branch_type_id, organization_id)
        if not branch_type:
            return False

        if branch_type.is_default:
            raise ValueError("The default branch type cannot be deleted. You can edit its name and appearance.")

        in_use = repo.count_branches_using(branch_type.code, organization_id)
        if in_use:
            raise ValueError(
                f"Cannot delete branch type '{branch_type.code}': "
                f"{in_use} branch(es) still use it. Reassign those branches first."
            )

        return repo.delete(str(branch_type.branch_type_id))


def _map_branch_type(branch_type: BranchType) -> BranchTypeResponse:
    """Map BranchType model to BranchTypeResponse DTO."""
    return BranchTypeResponse(
        id=str(branch_type.branch_type_id),
        organization_id=branch_type.organization_id,
        code=branch_type.code,
        name=branch_type.name,
        icon=branch_type.icon,
        color=branch_type.color,
        sort_order=branch_type.sort_order,
        status=branch_type.status,
        is_default=branch_type.is_default,
        created_at=branch_type.created_on.isoformat() if branch_type.created_on else None,
        updated_at=branch_type.updated_on.isoformat() if branch_type.updated_on else None,
    )
