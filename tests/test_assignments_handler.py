"""
Unit tests for assignments handler (repository, service, controller).
"""
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.dtos.requests.assignment_request_dto import (
    AssignmentCreateRequestDTO,
    AssignmentUpdateRequestDTO,
)
from app.dtos.responses.assignment_dto import AssignmentResponse
from app.models.assignment import Assignment
from app.services import assignment_service


class TestAssignmentService:
    """Test assignment service layer."""

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_get_assignments_success(self, mock_repo_class):
        """Test getting all assignments for an organization."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = uuid.uuid4()
        session_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        terminal_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        mock_assignment = Assignment(
            assignment_id=assignment_id,
            organization_id=org_id,
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=terminal_id,
            role="cashier",
            start_time=now,
            status=1,
            created_by=user_id,
        )
        mock_assignment.created_on = now
        mock_assignment.updated_on = now

        mock_repo = MagicMock()
        mock_repo.find_all_paginated.return_value = ([mock_assignment], 1)
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        # get_assignments batch-enriches from UserRepository; unmocked it
        # reaches for real database credentials.
        with patch("app.services.assignment_service.UserRepository") as user_class:
            user_repo = MagicMock()
            user_repo.find_by_ids.return_value = {}
            user_class.return_value.__enter__.return_value = user_repo

            result = assignment_service.get_assignments(org_id, user_id)

        # Assert
        assert len(result.data) == 1
        assert result.data[0].assignment_id == str(assignment_id)
        assert result.data[0].user_id == "cashier-789"
        assert result.data[0].role == "cashier"
        assert result.data[0].status == 1
        mock_repo.find_all_paginated.assert_called_once_with(
            org_id, filters=[], order_by=None, page=1, page_size=12
        )

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_get_assignments_with_filters(self, mock_repo_class):
        """Test getting assignments with various filter combinations."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        assigned_user_id = "cashier-789"

        mock_repo = MagicMock()
        mock_repo.find_all_paginated.return_value = ([], 0)
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        # Per-field filter kwargs were replaced by one `search` string that
        # SearchUtils parses into SQLAlchemy filters.
        assignment_service.get_assignments(
            org_id, user_id, page=3, page_size=7, search=f"session_id:{session_id}"
        )

        # Assert
        call = mock_repo.find_all_paginated.call_args
        assert call.args == (org_id,)
        assert call.kwargs["page"] == 3
        assert call.kwargs["page_size"] == 7
        assert call.kwargs["filters"], "the search string should reach the query"

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_get_assignment_by_id_success(self, mock_repo_class):
        """Test getting a single assignment by ID."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = uuid.uuid4()
        session_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        mock_assignment = Assignment(
            assignment_id=assignment_id,
            organization_id=org_id,
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=None,
            role="supervisor",
            start_time=now,
            status=1,
            created_by=user_id,
        )
        mock_assignment.created_on = now
        mock_assignment.updated_on = now

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = mock_assignment
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        # get_assignment enriches the row from UserRepository; unmocked it
        # reaches for real database credentials.
        with patch("app.services.assignment_service.UserRepository") as user_class:
            user_repo = MagicMock()
            user_repo.find_by_ids.return_value = {}
            user_class.return_value.__enter__.return_value = user_repo

            result = assignment_service.get_assignment(
                org_id, user_id, str(assignment_id)
            )

        # Assert
        assert result is not None
        assert result.assignment_id == str(assignment_id)
        assert result.role == "supervisor"
        assert result.terminal_id is None
        mock_repo.find_by_id_and_organization.assert_called_once_with(
            str(assignment_id), org_id
        )

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_get_assignment_not_found(self, mock_repo_class):
        """Test getting a non-existent assignment returns None."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = str(uuid.uuid4())

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = None
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = assignment_service.get_assignment(org_id, user_id, assignment_id)

        # Assert
        assert result is None

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_create_assignment_success(self, mock_repo_class):
        """Test creating a new assignment with valid data."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = uuid.uuid4()
        session_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        terminal_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        dto = AssignmentCreateRequestDTO(
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=terminal_id,
            role="cashier",
            start_time=now,
        )

        mock_assignment = Assignment(
            assignment_id=assignment_id,
            organization_id=org_id,
            session_id=uuid.UUID(session_id),
            user_id=dto.user_id,
            branch_id=uuid.UUID(branch_id),
            terminal_id=uuid.UUID(terminal_id),
            role=dto.role,
            start_time=dto.start_time,
            status=1,
            created_by=user_id,
        )
        mock_assignment.created_on = now
        mock_assignment.updated_on = now

        mock_repo = MagicMock()
        mock_repo.validate_session_exists_and_active.return_value = True
        mock_repo.validate_branch_exists.return_value = True
        mock_repo.validate_terminal_exists.return_value = True
        mock_repo.find_active_assignment_for_user.return_value = None
        mock_repo.save.return_value = mock_assignment
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = assignment_service.create_assignment(org_id, user_id, dto)

        # Assert
        assert result.user_id == "cashier-789"
        assert result.role == "cashier"
        assert result.status == 1
        assert result.terminal_id == terminal_id
        mock_repo.validate_session_exists_and_active.assert_called_once_with(
            session_id, org_id
        )
        mock_repo.validate_branch_exists.assert_called_once_with(branch_id, org_id)
        mock_repo.validate_terminal_exists.assert_called_once_with(terminal_id, branch_id)
        mock_repo.find_active_assignment_for_user.assert_called_once_with("cashier-789")
        mock_repo.save.assert_called_once()

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_create_assignment_without_terminal(self, mock_repo_class):
        """Test creating an assignment without a terminal (supervisor role)."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = uuid.uuid4()
        session_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        dto = AssignmentCreateRequestDTO(
            session_id=session_id,
            user_id="supervisor-999",
            branch_id=branch_id,
            terminal_id=None,
            role="supervisor",
            start_time=now,
        )

        mock_assignment = Assignment(
            assignment_id=assignment_id,
            organization_id=org_id,
            session_id=uuid.UUID(session_id),
            user_id=dto.user_id,
            branch_id=uuid.UUID(branch_id),
            terminal_id=None,
            role=dto.role,
            start_time=dto.start_time,
            status=1,
            created_by=user_id,
        )
        mock_assignment.created_on = now
        mock_assignment.updated_on = now

        mock_repo = MagicMock()
        mock_repo.validate_session_exists_and_active.return_value = True
        mock_repo.validate_branch_exists.return_value = True
        mock_repo.find_active_assignment_for_user.return_value = None
        mock_repo.save.return_value = mock_assignment
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = assignment_service.create_assignment(org_id, user_id, dto)

        # Assert
        assert result.role == "supervisor"
        assert result.terminal_id is None
        mock_repo.validate_terminal_exists.assert_not_called()

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_create_assignment_invalid_session(self, mock_repo_class):
        """Test creating assignment fails when session doesn't exist or isn't active."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        dto = AssignmentCreateRequestDTO(
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=None,
            role="cashier",
            start_time=now,
        )

        mock_repo = MagicMock()
        mock_repo.validate_session_exists_and_active.return_value = False
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act & Assert
        with pytest.raises(ValueError, match="does not exist.*or is not active"):
            assignment_service.create_assignment(org_id, user_id, dto)

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_create_assignment_invalid_branch(self, mock_repo_class):
        """Test creating assignment fails when branch doesn't exist or doesn't belong to org."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        dto = AssignmentCreateRequestDTO(
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=None,
            role="cashier",
            start_time=now,
        )

        mock_repo = MagicMock()
        mock_repo.validate_session_exists_and_active.return_value = True
        mock_repo.validate_branch_exists.return_value = False
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act & Assert
        with pytest.raises(ValueError, match="does not exist or does not belong"):
            assignment_service.create_assignment(org_id, user_id, dto)

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_create_assignment_invalid_terminal(self, mock_repo_class):
        """Test creating assignment fails when terminal doesn't exist or doesn't belong to branch."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        terminal_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        dto = AssignmentCreateRequestDTO(
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=terminal_id,
            role="cashier",
            start_time=now,
        )

        mock_repo = MagicMock()
        mock_repo.validate_session_exists_and_active.return_value = True
        mock_repo.validate_branch_exists.return_value = True
        mock_repo.validate_terminal_exists.return_value = False
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act & Assert
        with pytest.raises(ValueError, match="does not exist or does not belong to branch"):
            assignment_service.create_assignment(org_id, user_id, dto)

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_create_assignment_user_already_has_active_assignment(self, mock_repo_class):
        """Test creating assignment fails when user already has active assignment."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        dto = AssignmentCreateRequestDTO(
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=None,
            role="cashier",
            start_time=now,
        )

        existing_assignment = Assignment(
            assignment_id=uuid.uuid4(),
            organization_id=org_id,
            session_id=uuid.uuid4(),
            user_id="cashier-789",
            branch_id=uuid.uuid4(),
            terminal_id=None,
            role="cashier",
            start_time=now,
            status=1,
            created_by=user_id,
        )

        mock_repo = MagicMock()
        mock_repo.validate_session_exists_and_active.return_value = True
        mock_repo.validate_branch_exists.return_value = True
        mock_repo.find_active_assignment_for_user.return_value = existing_assignment
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act & Assert
        with pytest.raises(ValueError, match="already has an active assignment"):
            assignment_service.create_assignment(org_id, user_id, dto)

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_update_assignment_success(self, mock_repo_class):
        """Test updating an assignment."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = uuid.uuid4()
        session_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        terminal_id = uuid.uuid4()
        new_terminal_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        existing_assignment = Assignment(
            assignment_id=assignment_id,
            organization_id=org_id,
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=terminal_id,
            role="cashier",
            start_time=now,
            status=1,
            created_by=user_id,
        )
        existing_assignment.created_on = now
        existing_assignment.updated_on = now

        dto = AssignmentUpdateRequestDTO(
            terminal_id=new_terminal_id,
        )

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing_assignment
        mock_repo.validate_terminal_exists.return_value = True
        mock_repo.save.return_value = existing_assignment
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = assignment_service.update_assignment(
            org_id, user_id, str(assignment_id), dto
        )

        # Assert
        assert result is not None
        assert result.terminal_id == new_terminal_id
        mock_repo.validate_terminal_exists.assert_called_once_with(
            new_terminal_id, str(branch_id)
        )
        mock_repo.save.assert_called_once()

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_update_assignment_deactivate_sets_end_time(self, mock_repo_class):
        """Test deactivating an assignment automatically sets end_time."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = uuid.uuid4()
        session_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        existing_assignment = Assignment(
            assignment_id=assignment_id,
            organization_id=org_id,
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=None,
            role="cashier",
            start_time=now,
            end_time=None,
            status=1,
            created_by=user_id,
        )
        existing_assignment.created_on = now
        existing_assignment.updated_on = now

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing_assignment
        mock_repo.save.return_value = existing_assignment
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        # Status changes go through update_assignment_status, not
        # update_assignment — that is the entry point which stamps end_time.
        result = assignment_service.update_assignment_status(
            org_id, user_id, str(assignment_id), 2
        )

        # Assert
        assert result is not None
        assert result.status == 2
        assert existing_assignment.end_time is not None
        mock_repo.save.assert_called_once()

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_update_assignment_not_found(self, mock_repo_class):
        """Test updating a non-existent assignment returns None."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = str(uuid.uuid4())

        dto = AssignmentUpdateRequestDTO(
            status=2,
        )

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = None
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = assignment_service.update_assignment(org_id, user_id, assignment_id, dto)

        # Assert
        assert result is None
        mock_repo.save.assert_not_called()

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_update_assignment_invalid_terminal(self, mock_repo_class):
        """Test updating assignment fails when terminal doesn't belong to branch."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = uuid.uuid4()
        session_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        new_terminal_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        existing_assignment = Assignment(
            assignment_id=assignment_id,
            organization_id=org_id,
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=None,
            role="cashier",
            start_time=now,
            status=1,
            created_by=user_id,
        )

        dto = AssignmentUpdateRequestDTO(
            terminal_id=new_terminal_id,
        )

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing_assignment
        mock_repo.validate_terminal_exists.return_value = False
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act & Assert
        with pytest.raises(ValueError, match="does not exist or does not belong to branch"):
            assignment_service.update_assignment(org_id, user_id, str(assignment_id), dto)

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_delete_assignment_success(self, mock_repo_class):
        """Test deleting an assignment successfully."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = uuid.uuid4()
        session_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        existing_assignment = Assignment(
            assignment_id=assignment_id,
            organization_id=org_id,
            session_id=session_id,
            user_id="cashier-789",
            branch_id=branch_id,
            terminal_id=None,
            role="cashier",
            start_time=now,
            status=2,
            created_by=user_id,
        )

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing_assignment
        mock_repo.delete.return_value = True
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = assignment_service.delete_assignment(org_id, user_id, str(assignment_id))

        # Assert
        assert result is True
        mock_repo.delete.assert_called_once_with(str(assignment_id))

    @patch("app.services.assignment_service.AssignmentRepository")
    def test_delete_assignment_not_found(self, mock_repo_class):
        """Test deleting a non-existent assignment returns False."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        assignment_id = str(uuid.uuid4())

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = None
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = assignment_service.delete_assignment(org_id, user_id, assignment_id)

        # Assert
        assert result is False
        mock_repo.delete.assert_not_called()
