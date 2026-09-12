"""
Unit tests for sessions handler (repository, service, controller).
"""
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.dtos.requests.session_request_dto import (
    SessionCreateRequestDTO,
    SessionUpdateRequestDTO,
)
from app.dtos.responses.session_dto import SessionResponse
from app.models.assignment import Assignment
from app.models.session import Session
from app.services import session_service


class TestSessionService:
    """Test session service layer."""

    @patch("app.services.session_service.SessionRepository")
    def test_get_sessions_success(self, mock_repo_class):
        """Test getting all sessions for an organization."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        mock_session = Session(
            session_id=session_id,
            organization_id=org_id,
            branch_id=branch_id,
            name="Partido vs Herediano",
            type="match",
            context="gradas",
            start_time=now,
            status=1,
            expected_revenue=1500000.00,
            created_by=user_id,
        )
        mock_session.created_on = now
        mock_session.updated_on = now

        mock_repo = MagicMock()
        mock_repo.find_all_paginated.return_value = ([mock_session], 1)
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = session_service.get_sessions(org_id, user_id)

        # Assert
        assert len(result.data) == 1
        assert result.data[0].session_id == str(session_id)
        assert result.data[0].name == "Partido vs Herediano"
        assert result.data[0].type == "match"
        assert result.data[0].context == "gradas"
        assert result.data[0].status == 1
        mock_repo.find_all_paginated.assert_called_once_with(
            org_id, filters=[], order_by=None, page=1, page_size=12
        )

    @patch("app.services.session_service.SessionRepository")
    def test_get_sessions_with_filters(self, mock_repo_class):
        """Test getting sessions with filters."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        branch_id = str(uuid.uuid4())

        mock_repo = MagicMock()
        mock_repo.find_all_paginated.return_value = ([], 0)
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        # The per-field filter kwargs were replaced by one `search` string that
        # SearchUtils parses into SQLAlchemy filters, so what reaches the
        # repository is a filter list plus page bounds — not a kwarg per field.
        session_service.get_sessions(
            org_id, user_id, page=2, page_size=5, search="type:match"
        )

        # Assert
        call = mock_repo.find_all_paginated.call_args
        assert call.args == (org_id,)
        assert call.kwargs["page"] == 2
        assert call.kwargs["page_size"] == 5
        assert call.kwargs["filters"], "the search string should reach the query"

    @patch("app.services.session_service.SessionRepository")
    def test_create_session_success(self, mock_repo_class):
        """Test creating a new session."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = uuid.uuid4()
        branch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        dto = SessionCreateRequestDTO(
            name="Partido vs Herediano",
            type="match",
            context="gradas",
            branch_id=branch_id,
            start_time=now,
            expected_revenue=1500000.00,
        )

        mock_session = Session(
            session_id=session_id,
            organization_id=org_id,
            branch_id=uuid.UUID(branch_id),
            name=dto.name,
            type=dto.type,
            context=dto.context,
            start_time=dto.start_time,
            status=1,
            expected_revenue=dto.expected_revenue,
            created_by=user_id,
        )
        mock_session.created_on = now
        mock_session.updated_on = now

        mock_repo = MagicMock()
        mock_repo.validate_branch_exists.return_value = True
        mock_repo.save.return_value = mock_session
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = session_service.create_session(org_id, user_id, dto)

        # Assert
        assert result.name == "Partido vs Herediano"
        assert result.type == "match"
        assert result.context == "gradas"
        assert result.status == 1
        assert result.expected_revenue == 1500000.00
        mock_repo.validate_branch_exists.assert_called_once_with(branch_id, org_id)
        mock_repo.save.assert_called_once()

    @patch("app.services.session_service.SessionRepository")
    def test_create_session_without_branch(self, mock_repo_class):
        """Test creating a session without a branch."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        dto = SessionCreateRequestDTO(
            name="Turno Mañana",
            type="shift",
            context="caja",
            start_time=now,
        )

        mock_session = Session(
            session_id=session_id,
            organization_id=org_id,
            branch_id=None,
            name=dto.name,
            type=dto.type,
            context=dto.context,
            start_time=dto.start_time,
            status=1,
            created_by=user_id,
        )
        mock_session.created_on = now
        mock_session.updated_on = now

        mock_repo = MagicMock()
        mock_repo.save.return_value = mock_session
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = session_service.create_session(org_id, user_id, dto)

        # Assert
        assert result.name == "Turno Mañana"
        assert result.branch_id is None
        mock_repo.validate_branch_exists.assert_not_called()
        mock_repo.save.assert_called_once()

    @patch("app.services.session_service.SessionRepository")
    def test_create_session_invalid_branch(self, mock_repo_class):
        """Test creating a session with invalid branch fails."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        branch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        dto = SessionCreateRequestDTO(
            name="Partido vs Herediano",
            type="match",
            context="gradas",
            branch_id=branch_id,
            start_time=now,
        )

        mock_repo = MagicMock()
        mock_repo.validate_branch_exists.return_value = False
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act & Assert
        with pytest.raises(ValueError, match="does not exist"):
            session_service.create_session(org_id, user_id, dto)

    @patch("app.services.session_service.SessionRepository")
    def test_update_session_success(self, mock_repo_class):
        """Test updating a session."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        existing_session = Session(
            session_id=session_id,
            organization_id=org_id,
            branch_id=None,
            name="Partido vs Herediano",
            type="match",
            context="gradas",
            start_time=now,
            status=1,
            created_by=user_id,
        )
        existing_session.created_on = now
        existing_session.updated_on = now

        dto = SessionUpdateRequestDTO(
            name="Partido vs Herediano - Final",
            actual_revenue=1800000.00,
        )

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing_session
        mock_repo.save.return_value = existing_session
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = session_service.update_session(org_id, user_id, str(session_id), dto)

        # Assert
        assert result is not None
        assert result.name == "Partido vs Herediano - Final"
        assert result.actual_revenue == 1800000.00
        mock_repo.save.assert_called_once()

    @patch("app.services.session_service.SessionRepository")
    def test_update_session_deactivate_sets_end_time(self, mock_repo_class):
        """Test deactivating a session automatically sets end_time."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        existing_session = Session(
            session_id=session_id,
            organization_id=org_id,
            branch_id=None,
            name="Partido vs Herediano",
            type="match",
            context="gradas",
            start_time=now,
            end_time=None,
            status=1,
            created_by=user_id,
        )
        existing_session.created_on = now
        existing_session.updated_on = now

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing_session
        mock_repo.save.return_value = existing_session
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        # Status changes go through update_session_status, not update_session —
        # that is the entry point which also stamps end_time, and it ends the
        # session's open assignments on the way.
        with patch(
            "app.repositories.assignment_repository.AssignmentRepository"
        ) as assign_class:
            assign_repo = MagicMock()
            assign_repo.find_all_by_organization.return_value = []
            assign_class.return_value.__enter__.return_value = assign_repo

            result = session_service.update_session_status(
                org_id, user_id, str(session_id), 2
            )

        # Assert
        assert result is not None
        assert result.status == 2
        assert existing_session.end_time is not None
        mock_repo.save.assert_called_once()

    @patch("app.services.session_service.SessionRepository")
    def test_delete_session_with_active_assignments(self, mock_repo_class):
        """Test deleting a session with active assignments fails."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = uuid.uuid4()

        existing_session = Session(
            session_id=session_id,
            organization_id=org_id,
            branch_id=None,
            name="Partido vs Herediano",
            type="match",
            context="gradas",
            start_time=datetime.now(timezone.utc),
            status=1,
            created_by=user_id,
        )

        active = Assignment(
            assignment_id=uuid.uuid4(),
            organization_id=org_id,
            session_id=session_id,
            terminal_id=uuid.uuid4(),
            user_id="cashier-1",
            role="cashier",
            start_time=datetime.now(timezone.utc),
            status=1,
            created_by=user_id,
        )

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing_session
        mock_repo.delete.return_value = True
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        # Deleting a session no longer refuses when assignments are open — it
        # ends them first. Patched at the source module because the service
        # imports AssignmentRepository inside the function body.
        with patch(
            "app.repositories.assignment_repository.AssignmentRepository"
        ) as assign_class:
            assign_repo = MagicMock()
            assign_repo.find_all_by_organization.return_value = [active]
            assign_class.return_value.__enter__.return_value = assign_repo

            result = session_service.delete_session(org_id, user_id, str(session_id))

        # Assert
        assert result is True
        assert active.status == 2, "an open assignment must be closed, not left active"
        assert active.end_time is not None
        assign_repo.save.assert_called_once_with(active)

    @patch("app.services.session_service.SessionRepository")
    def test_delete_session_success(self, mock_repo_class):
        """Test deleting a session successfully."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = uuid.uuid4()

        existing_session = Session(
            session_id=session_id,
            organization_id=org_id,
            branch_id=None,
            name="Partido vs Herediano",
            type="match",
            context="gradas",
            start_time=datetime.now(timezone.utc),
            status=2,
            created_by=user_id,
        )

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing_session
        mock_repo.delete.return_value = True
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        with patch(
            "app.repositories.assignment_repository.AssignmentRepository"
        ) as assign_class:
            assign_repo = MagicMock()
            assign_repo.find_all_by_organization.return_value = []
            assign_class.return_value.__enter__.return_value = assign_repo

            result = session_service.delete_session(org_id, user_id, str(session_id))

        # Assert
        assert result is True
        mock_repo.delete.assert_called_once_with(str(session_id))

    @patch("app.services.session_service.SessionRepository")
    def test_get_session_not_found(self, mock_repo_class):
        """Test getting a non-existent session returns None."""
        # Arrange
        org_id = "org-123"
        user_id = "user-456"
        session_id = str(uuid.uuid4())

        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = None
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        # Act
        result = session_service.get_session(org_id, user_id, session_id)

        # Assert
        assert result is None
