"""Unit tests for the terminal service (repositories mocked, no I/O).

Rewritten 2026-09-12. The previous version had been failing for some time: it
passed `is_active=` to the model (replaced by `status` in migration
f6a7b8c9d0e1), used string codes like "T1" (made integer by s9a0b1c2d3e4), and
called `get_terminals(..., is_active=...)`, which the service no longer accepts.

The rule these tests exist to hold down is the one TSR-254 corrected: a terminal
code is unique **per branch**, not per organization. Hacienda's consecutive is
branch(3) + terminal(5), so the pair identifies the point of sale and terminal 1
may exist under several branches. The old suite asserted the opposite, which is
how an organization-wide constraint survived long enough to hide three of a real
taxpayer's branches.

`status` is 1=Active, 2=Inactive, 3=Deleted.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.dtos.requests.terminal_request_dto import (
    TerminalCreateRequestDTO,
    TerminalUpdateRequestDTO,
)
from app.models.branch import Branch
from app.models.terminal import Terminal
from app.services import terminal_service

ORG_ID = "org-123"
USER_ID = "user-456"


def make_branch(code: int = 1, **overrides) -> Branch:
    values = dict(
        branch_id=uuid.uuid4(), organization_id=ORG_ID, name=f"Sucursal {code}",
        code=code, type="stand", status=1, created_by=USER_ID,
    )
    values.update(overrides)
    return Branch(**values)


def make_terminal(branch: Branch, code: int = 1, **overrides) -> Terminal:
    now = datetime.now(timezone.utc)
    values = dict(
        terminal_id=uuid.uuid4(), organization_id=ORG_ID, branch_id=branch.branch_id,
        name=f"Terminal {code}", code=code, device_id=None, status=1, registered_at=now,
    )
    values.update(overrides)
    terminal = Terminal(**values)
    terminal.created_on = now
    terminal.updated_on = now
    return terminal


def saved(terminal):
    """Stand in for repo.save(): apply the column defaults the database would.

    `status` and the timestamps are column defaults, so an un-flushed in-memory
    object still has them as None and TerminalResponse rejects that. Returning
    the object untouched would assert a state the database never produces.
    """
    if terminal.status is None:
        terminal.status = 1
    now = datetime.now(timezone.utc)
    if terminal.created_on is None:
        terminal.created_on = now
    terminal.updated_on = now
    return terminal


@pytest.fixture()
def repos():
    """Patch both repositories the service opens; expose them as one handle."""
    with patch("app.services.terminal_service.TerminalRepository") as t_class, \
         patch("app.services.terminal_service.BranchRepository") as b_class:
        terminals = MagicMock()
        branches = MagicMock()
        t_class.return_value.__enter__.return_value = terminals
        b_class.return_value.__enter__.return_value = branches

        handle = MagicMock()
        handle.terminals = terminals
        handle.branches = branches
        yield handle


class TestGetTerminals:
    def test_returns_a_paginated_envelope(self, repos):
        branch = make_branch()
        repos.terminals.find_all_paginated.return_value = ([make_terminal(branch)], 1)

        result = terminal_service.get_terminals(ORG_ID, USER_ID)

        assert result.pagination.total_elements == 1
        assert len(result.data) == 1
        assert result.data[0].code == 1
        assert result.data[0].status == 1

    def test_branch_code_is_resolved_to_a_uuid_filter(self, repos):
        branch = make_branch(code=14)
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_all_paginated.return_value = ([], 0)

        terminal_service.get_terminals(ORG_ID, USER_ID, branch_code=14)

        repos.branches.find_by_code_and_organization.assert_called_once_with(14, ORG_ID)
        assert repos.terminals.find_all_paginated.call_args.kwargs["filters"], (
            "the branch filter should reach the query, not be applied in memory"
        )

    def test_an_unknown_branch_yields_an_empty_page_not_every_terminal(self, repos):
        repos.branches.find_by_code_and_organization.return_value = None

        result = terminal_service.get_terminals(ORG_ID, USER_ID, branch_code=999)

        assert result.data == []
        assert result.pagination.total_elements == 0
        repos.terminals.find_all_paginated.assert_not_called()


class TestGetTerminalByCode:
    def test_looked_up_within_its_branch(self, repos):
        branch = make_branch(code=14)
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = make_terminal(branch, code=1)

        result = terminal_service.get_terminal_by_code(ORG_ID, USER_ID, 1, 14)

        assert result is not None and result.code == 1
        repos.terminals.find_by_code_and_branch.assert_called_once_with(
            1, str(branch.branch_id), ORG_ID
        )

    def test_unknown_branch_returns_none(self, repos):
        repos.branches.find_by_code_and_organization.return_value = None

        assert terminal_service.get_terminal_by_code(ORG_ID, USER_ID, 1, 999) is None
        repos.terminals.find_by_code_and_branch.assert_not_called()


class TestCreateTerminal:
    def test_creates_within_the_branch(self, repos):
        branch = make_branch(code=14)
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = None
        repos.terminals.save.side_effect = saved

        result = terminal_service.create_terminal(
            ORG_ID, USER_ID, 14, TerminalCreateRequestDTO(name="Caja 1", code=1),
        )

        assert result.code == 1
        assert result.branch_id == str(branch.branch_id)
        assert result.status == 1

    def test_uniqueness_is_checked_per_branch_not_per_organization(self, repos):
        """The heart of TSR-254: the same code in another branch is not a clash."""
        branch = make_branch(code=14)
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = None
        repos.terminals.save.side_effect = saved

        terminal_service.create_terminal(
            ORG_ID, USER_ID, 14, TerminalCreateRequestDTO(name="Caja 1", code=1),
        )

        repos.terminals.find_by_code_and_branch.assert_called_once_with(
            1, str(branch.branch_id), ORG_ID
        )
        assert not repos.terminals.find_by_code_and_organization.called, (
            "an organization-wide check would reject terminal 1 in a second branch"
        )

    def test_duplicate_code_within_the_same_branch_is_rejected(self, repos):
        branch = make_branch(code=14)
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = make_terminal(branch, code=1)

        with pytest.raises(ValueError, match="already exists in this branch"):
            terminal_service.create_terminal(
                ORG_ID, USER_ID, 14, TerminalCreateRequestDTO(name="Caja dup", code=1),
            )
        repos.terminals.save.assert_not_called()

    def test_unknown_branch_is_rejected(self, repos):
        repos.branches.find_by_code_and_organization.return_value = None

        with pytest.raises(ValueError, match="Branch does not exist"):
            terminal_service.create_terminal(
                ORG_ID, USER_ID, 999, TerminalCreateRequestDTO(name="Caja", code=1),
            )

    def test_device_id_stays_globally_unique(self, repos):
        """Unlike the code, device_id is unique across every organization."""
        branch = make_branch()
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = None
        repos.terminals.find_by_device_id.return_value = make_terminal(branch, code=9)

        with pytest.raises(ValueError, match="already registered"):
            terminal_service.create_terminal(
                ORG_ID, USER_ID, 1,
                TerminalCreateRequestDTO(name="Caja", code=2, device_id="dev-1"),
            )
        repos.terminals.save.assert_not_called()


class TestUpdateTerminal:
    def test_updates_only_what_was_supplied(self, repos):
        branch = make_branch()
        terminal = make_terminal(branch, code=1, device_id="dev-1")
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = terminal
        repos.terminals.save.side_effect = saved

        result = terminal_service.update_terminal(
            ORG_ID, USER_ID, 1, 1, TerminalUpdateRequestDTO(name="Renombrada"),
        )

        assert result.name == "Renombrada"
        assert result.device_id == "dev-1", "an omitted field must not be cleared"

    def test_renaming_onto_a_code_used_in_the_same_branch_is_rejected(self, repos):
        branch = make_branch()
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.side_effect = [
            make_terminal(branch, code=1),   # the terminal being updated
            make_terminal(branch, code=2),   # the code it wants, taken in this branch
        ]

        with pytest.raises(ValueError, match="already exists in this branch"):
            terminal_service.update_terminal(
                ORG_ID, USER_ID, 1, 1, TerminalUpdateRequestDTO(code=2),
            )

    def test_unknown_terminal_returns_none(self, repos):
        repos.branches.find_by_code_and_organization.return_value = make_branch()
        repos.terminals.find_by_code_and_branch.return_value = None

        assert terminal_service.update_terminal(
            ORG_ID, USER_ID, 99, 1, TerminalUpdateRequestDTO(name="x"),
        ) is None


class TestTerminalStatus:
    def test_deleting_status_stamps_deleted_on(self, repos):
        branch = make_branch()
        terminal = make_terminal(branch)
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = terminal
        repos.terminals.save.side_effect = saved

        result = terminal_service.update_terminal_status(ORG_ID, USER_ID, 1, 1, 3)

        assert result.status == 3
        assert terminal.deleted_on is not None

    def test_deactivating_does_not_stamp_deleted_on(self, repos):
        branch = make_branch()
        terminal = make_terminal(branch)
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = terminal
        repos.terminals.save.side_effect = saved

        result = terminal_service.update_terminal_status(ORG_ID, USER_ID, 1, 1, 2)

        assert result.status == 2
        assert terminal.deleted_on is None


class TestDeleteTerminal:
    def test_refuses_while_assignments_are_active(self, repos):
        branch = make_branch()
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = make_terminal(branch)
        repos.terminals.has_active_assignments.return_value = True

        with pytest.raises(ValueError, match="active assignments"):
            terminal_service.delete_terminal(ORG_ID, USER_ID, 1, 1)
        repos.terminals.delete.assert_not_called()

    def test_deletes_when_nothing_depends_on_it(self, repos):
        branch = make_branch()
        terminal = make_terminal(branch)
        repos.branches.find_by_code_and_organization.return_value = branch
        repos.terminals.find_by_code_and_branch.return_value = terminal
        repos.terminals.has_active_assignments.return_value = False
        repos.terminals.delete.return_value = True

        assert terminal_service.delete_terminal(ORG_ID, USER_ID, 1, 1) is True
        repos.terminals.delete.assert_called_once_with(str(terminal.terminal_id))

    def test_unknown_branch_is_false_not_an_error(self, repos):
        repos.branches.find_by_code_and_organization.return_value = None

        assert terminal_service.delete_terminal(ORG_ID, USER_ID, 1, 999) is False
