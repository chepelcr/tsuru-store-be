"""Unit tests for the branch service (repository mocked, no I/O).

Rewritten 2026-09-12. The previous version was written against an older API and
had been failing for some time: it called `find_all_by_organization(org_id,
is_active=..., branch_type=...)` when the service uses `find_all_paginated`,
treated `get_branches` as returning a list rather than a `BranchListResponse`,
constructed models with `is_active=` (replaced by `status` in migration
f6a7b8c9d0e1) and used string codes like "P1" (made integer by
s9a0b1c2d3e4). So it guarded nothing while looking like it did — which mattered
when TSR-254 changed the terminal uniqueness rule underneath it.

`status` is 1=Active, 2=Inactive, 3=Deleted. Codes are integers, unique per
organization for branches (a Hacienda requirement).
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.dtos.common.location_dto import LocationRequestDTO
from app.dtos.requests.branch_request_dto import (
    BranchCreateRequestDTO,
    BranchUpdateRequestDTO,
)
from app.models.branch import Branch
from app.services import branch_service

ORG_ID = "org-123"
USER_ID = "user-456"


def make_branch(**overrides) -> Branch:
    """A Branch as the database would hand it back."""
    now = datetime.now(timezone.utc)
    values = dict(
        branch_id=uuid.uuid4(),
        organization_id=ORG_ID,
        name="Puesto 1",
        code=1,
        type="stand",
        status=1,
        state_id=6,
        county_id=1,
        district_id=1,
        neighborhood_id=4,
        address="Estadio Lito Pérez",
        phone="1234-5678",
        created_by=USER_ID,
    )
    values.update(overrides)
    branch = Branch(**values)
    branch.created_on = now
    branch.updated_on = now
    return branch



def saved(branch):
    """Stand in for repo.save(): apply the column defaults the database would.

    `status`, `created_on` and `updated_on` are server/column defaults, so an
    un-flushed in-memory object still has them as None and BranchResponse
    rejects that. Returning the object untouched would test a state the
    database never produces.
    """
    if branch.status is None:
        branch.status = 1
    now = datetime.now(timezone.utc)
    if branch.created_on is None:
        branch.created_on = now
    branch.updated_on = now
    return branch

@pytest.fixture()
def branch_repo():
    """Patch BranchRepository and the catalog the type validator reads."""
    with patch("app.services.branch_service.BranchRepository") as repo_class, \
         patch("app.services.branch_service.TerminalRepository") as terminal_class, \
         patch("app.services.branch_service.BranchTypeRepository") as type_class:
        repo = MagicMock()
        repo_class.return_value.__enter__.return_value = repo

        terminals = MagicMock()
        terminals.find_all_by_branch.return_value = []
        terminal_class.return_value.__enter__.return_value = terminals

        types = MagicMock()
        types.find_all_by_organization.return_value = [
            MagicMock(code="stand"), MagicMock(code="restaurant"),
        ]
        type_class.return_value.__enter__.return_value = types

        repo.terminals = terminals
        repo.branch_types = types
        yield repo


class TestGetBranches:
    def test_returns_a_paginated_envelope_not_a_list(self, branch_repo):
        branch = make_branch()
        branch_repo.find_all_paginated.return_value = ([branch], 1)

        result = branch_service.get_branches(ORG_ID, USER_ID)

        assert result.pagination.total_elements == 1
        assert result.pagination.page == 1
        assert len(result.data) == 1
        row = result.data[0]
        assert row.branch_id == str(branch.branch_id)
        assert row.name == "Puesto 1"
        assert row.code == 1
        assert row.type == "stand"
        assert row.status == 1

    def test_location_is_assembled_from_the_flat_columns(self, branch_repo):
        branch_repo.find_all_paginated.return_value = ([make_branch()], 1)

        row = branch_service.get_branches(ORG_ID, USER_ID).data[0]

        assert row.location is not None
        assert (
            row.location.state_id,
            row.location.county_id,
            row.location.district_id,
            row.location.neighborhood_id,
        ) == (6, 1, 1, 4)

    def test_no_location_columns_means_no_location_object(self, branch_repo):
        bare = make_branch(
            state_id=None, county_id=None, district_id=None,
            neighborhood_id=None, address=None,
        )
        branch_repo.find_all_paginated.return_value = ([bare], 1)

        assert branch_service.get_branches(ORG_ID, USER_ID).data[0].location is None

    def test_branch_type_filter_reaches_the_repository(self, branch_repo):
        branch_repo.find_all_paginated.return_value = ([], 0)

        branch_service.get_branches(ORG_ID, USER_ID, branch_type="restaurant")

        filters = branch_repo.find_all_paginated.call_args.kwargs["filters"]
        assert filters, "the type filter should be passed down, not applied in memory"


class TestCreateBranch:
    def test_creates_with_an_integer_code_and_the_caller_as_created_by(self, branch_repo):
        branch_repo.find_by_code_and_organization.return_value = None
        branch_repo.save.side_effect = saved

        dto = BranchCreateRequestDTO(
            name="Puesto 2", code=2, type="stand",
            location=LocationRequestDTO(state_id=6, county_id=1, district_id=1, address="x"),
            phone="8888-8888",
        )
        result = branch_service.create_branch(ORG_ID, USER_ID, dto)

        assert result.code == 2
        assert result.created_by == USER_ID
        assert result.status == 1
        branch_repo.find_by_code_and_organization.assert_called_once_with(2, ORG_ID)

    def test_duplicate_code_is_rejected(self, branch_repo):
        branch_repo.find_by_code_and_organization.return_value = make_branch(code=1)

        dto = BranchCreateRequestDTO(name="Otra", code=1, type="stand")
        with pytest.raises(ValueError, match="already exists"):
            branch_service.create_branch(ORG_ID, USER_ID, dto)
        branch_repo.save.assert_not_called()

    def test_a_type_outside_the_org_catalog_is_rejected(self, branch_repo):
        """TSR-254: the type is a branch_types.code slug, validated against the catalog."""
        branch_repo.find_by_code_and_organization.return_value = None

        dto = BranchCreateRequestDTO(name="Puesto 3", code=3, type="not-in-catalog")
        with pytest.raises(ValueError, match="catalog"):
            branch_service.create_branch(ORG_ID, USER_ID, dto)
        branch_repo.save.assert_not_called()

    def test_an_org_with_no_catalog_still_accepts_the_legacy_defaults(self, branch_repo):
        branch_repo.branch_types.find_all_by_organization.return_value = []
        branch_repo.find_by_code_and_organization.return_value = None
        branch_repo.save.side_effect = saved

        dto = BranchCreateRequestDTO(name="Puesto 4", code=4, type="restaurant")
        assert branch_service.create_branch(ORG_ID, USER_ID, dto).type == "restaurant"


class TestUpdateBranch:
    def test_updates_only_the_fields_supplied(self, branch_repo):
        branch = make_branch(name="Antes", phone="1111-1111")
        branch_repo.find_by_code_and_organization.return_value = branch
        branch_repo.save.side_effect = saved

        result = branch_service.update_branch(
            ORG_ID, USER_ID, 1, BranchUpdateRequestDTO(name="Después"),
        )

        assert result.name == "Después"
        assert result.phone == "1111-1111", "an omitted field must not be cleared"

    def test_unknown_code_returns_none(self, branch_repo):
        branch_repo.find_by_code_and_organization.return_value = None

        assert branch_service.update_branch(
            ORG_ID, USER_ID, 99, BranchUpdateRequestDTO(name="x"),
        ) is None

    def test_renaming_onto_an_existing_code_is_rejected(self, branch_repo):
        branch_repo.find_by_code_and_organization.side_effect = [
            make_branch(code=1),   # the branch being updated
            make_branch(code=2),   # the code it wants, already taken
        ]

        with pytest.raises(ValueError, match="already exists"):
            branch_service.update_branch(
                ORG_ID, USER_ID, 1, BranchUpdateRequestDTO(code=2),
            )


class TestDeleteBranch:
    def test_refuses_while_terminals_are_active(self, branch_repo):
        branch_repo.find_by_code_and_organization.return_value = make_branch()
        branch_repo.has_active_terminals.return_value = True

        with pytest.raises(ValueError, match="active terminals"):
            branch_service.delete_branch(ORG_ID, USER_ID, 1)
        branch_repo.delete.assert_not_called()

    def test_refuses_while_sessions_are_active(self, branch_repo):
        branch_repo.find_by_code_and_organization.return_value = make_branch()
        branch_repo.has_active_terminals.return_value = False
        branch_repo.has_active_sessions.return_value = True

        with pytest.raises(ValueError, match="active sessions"):
            branch_service.delete_branch(ORG_ID, USER_ID, 1)
        branch_repo.delete.assert_not_called()

    def test_deletes_when_nothing_depends_on_it(self, branch_repo):
        branch = make_branch()
        branch_repo.find_by_code_and_organization.return_value = branch
        branch_repo.has_active_terminals.return_value = False
        branch_repo.has_active_sessions.return_value = False
        branch_repo.delete.return_value = True

        assert branch_service.delete_branch(ORG_ID, USER_ID, 1) is True
        branch_repo.delete.assert_called_once_with(str(branch.branch_id))

    def test_unknown_code_is_false_not_an_error(self, branch_repo):
        branch_repo.find_by_code_and_organization.return_value = None

        assert branch_service.delete_branch(ORG_ID, USER_ID, 99) is False
