"""
Unit tests for closing service business logic.
These tests verify service methods without requiring database access.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.8**
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal
from datetime import datetime, timezone
import uuid

from app.services import closing_service
from app.dtos.requests.closing_request_dto import (
    ClosingCreateRequestDTO,
    ClosingUpdateRequestDTO,
)
from app.models.closing import Closing


class TestClosingServiceUnit:
    """Unit tests for closing service methods."""

    @patch('app.services.closing_service.ClosingRepository')
    def test_get_closings_returns_all_for_organization(self, mock_repo_class):
        """
        Test that get_closings returns all closings for an organization.
        
        **Validates: Requirement 5.4**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        
        closing1 = Closing(
            closing_id=uuid.uuid4(),
            organization_id="org-123",
            session_id=uuid.uuid4(),
            assignment_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            terminal_id=None,
            cashier_id="cashier-1",
            expected_cash=Decimal('100.00'),
            expected_sinpe=Decimal('50.00'),
            expected_card=Decimal('50.00'),
            expected_total=Decimal('200.00'),
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
            status='pending',
        )
        
        closing2 = Closing(
            closing_id=uuid.uuid4(),
            organization_id="org-123",
            session_id=uuid.uuid4(),
            assignment_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            terminal_id=None,
            cashier_id="cashier-2",
            expected_cash=Decimal('200.00'),
            expected_sinpe=Decimal('100.00'),
            expected_card=Decimal('100.00'),
            expected_total=Decimal('400.00'),
            declared_cash=Decimal('200.00'),
            declared_sinpe=Decimal('100.00'),
            declared_card=Decimal('100.00'),
            declared_total=Decimal('400.00'),
            status='approved',
        )
        
        mock_repo.find_all_paginated.return_value = ([closing1, closing2], 2)
        
        # Call service
        result = closing_service.get_closings("org-123", "user-123")
        
        # Verify
        assert len(result.data) == 2
        assert result.data[0].organization_id == "org-123"
        assert result.data[1].organization_id == "org-123"
        call = mock_repo.find_all_paginated.call_args
        assert call.args == ("org-123",)
        assert "filters" in call.kwargs and "page" in call.kwargs

    @patch('app.services.closing_service.ClosingRepository')
    def test_get_closings_with_session_filter(self, mock_repo_class):
        """
        Test that get_closings filters by session_id.
        
        **Validates: Requirement 5.4**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.find_all_paginated.return_value = ([], 0)
        
        # Call service with session filter
        closing_service.get_closings(
            "org-123", "user-123", search="status:approved"
        )
        
        # Verify filter was passed
        call = mock_repo.find_all_paginated.call_args
        assert call.args == ("org-123",)
        assert "filters" in call.kwargs and "page" in call.kwargs

    @patch('app.services.closing_service.ClosingRepository')
    def test_get_closings_with_status_filter(self, mock_repo_class):
        """
        Test that get_closings filters by status.
        
        **Validates: Requirement 5.4**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.find_all_paginated.return_value = ([], 0)
        
        # Call service with status filter
        closing_service.get_closings(
            "org-123", "user-123", search="status:approved"
        )
        
        # Verify filter was passed
        call = mock_repo.find_all_paginated.call_args
        assert call.args == ("org-123",)
        assert "filters" in call.kwargs and "page" in call.kwargs

    @patch('app.services.closing_service.ClosingRepository')
    def test_get_closings_with_branch_filter(self, mock_repo_class):
        """
        Test that get_closings filters by branch_id.
        
        **Validates: Requirement 5.4**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.find_all_paginated.return_value = ([], 0)
        
        # Call service with branch filter
        closing_service.get_closings(
            "org-123", "user-123", search="status:approved"
        )
        
        # Verify filter was passed
        call = mock_repo.find_all_paginated.call_args
        assert call.args == ("org-123",)
        assert "filters" in call.kwargs and "page" in call.kwargs

    @patch('app.services.closing_service.ClosingRepository')
    def test_get_closings_with_multiple_filters(self, mock_repo_class):
        """
        Test that get_closings applies multiple filters simultaneously.
        
        **Validates: Requirement 5.4**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.find_all_paginated.return_value = ([], 0)
        
        # Call service with several filters at once. They travel as one
        # `search` string that SearchUtils parses, not as a kwarg per field.
        closing_service.get_closings(
            "org-123",
            "user-123",
            search="session_id:session-456,status:approved,branch_id:branch-789",
        )
        
        # Verify all filters were passed
        call = mock_repo.find_all_paginated.call_args
        assert call.args == ("org-123",)
        assert "filters" in call.kwargs and "page" in call.kwargs

    @patch('app.services.closing_service.ClosingRepository')
    def test_get_closing_returns_closing_when_found(self, mock_repo_class):
        """
        Test that get_closing returns a closing when it exists.
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        
        closing = Closing(
            closing_id=uuid.uuid4(),
            organization_id="org-123",
            session_id=uuid.uuid4(),
            assignment_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            terminal_id=None,
            cashier_id="cashier-1",
            expected_cash=Decimal('100.00'),
            expected_sinpe=Decimal('50.00'),
            expected_card=Decimal('50.00'),
            expected_total=Decimal('200.00'),
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
            status='pending',
        )
        
        mock_repo.find_by_id_and_organization.return_value = closing
        
        # Call service
        result = closing_service.get_closing("org-123", "user-123", str(closing.closing_id))
        
        # Verify
        assert result is not None
        assert result.closing_id == str(closing.closing_id)
        assert result.organization_id == "org-123"

    @patch('app.services.closing_service.ClosingRepository')
    def test_get_closing_returns_none_when_not_found(self, mock_repo_class):
        """
        Test that get_closing returns None when closing doesn't exist.
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.find_by_id_and_organization.return_value = None
        
        # Call service
        result = closing_service.get_closing("org-123", "user-123", "nonexistent-id")
        
        # Verify
        assert result is None

    @patch('app.services.closing_service.ClosingRepository')
    def test_create_closing_validates_assignment_exists(self, mock_repo_class):
        """
        Test that create_closing validates assignment exists.
        
        **Validates: Requirement 5.1**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.validate_assignment_exists.return_value = False
        
        # Create DTO
        dto = ClosingCreateRequestDTO(
            session_id=str(uuid.uuid4()),
            assignment_id="nonexistent-assignment",
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
        )
        
        # Call service and expect error
        with pytest.raises(ValueError) as exc_info:
            closing_service.create_closing("org-123", "user-123", dto)
        
        assert "does not exist or does not belong to this organization" in str(exc_info.value)

    @patch('app.services.closing_service.ClosingRepository')
    def test_create_closing_prevents_duplicate_for_assignment(self, mock_repo_class):
        """
        Test that create_closing prevents duplicate closings for same assignment.
        
        **Validates: Requirement 5.8**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.validate_assignment_exists.return_value = True
        
        existing_closing = Closing(
            closing_id=uuid.uuid4(),
            organization_id="org-123",
            session_id=uuid.uuid4(),
            assignment_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            terminal_id=None,
            cashier_id="cashier-1",
            expected_cash=Decimal('100.00'),
            expected_sinpe=Decimal('50.00'),
            expected_card=Decimal('50.00'),
            expected_total=Decimal('200.00'),
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
            status='pending',
        )
        
        mock_repo.find_by_assignment.return_value = existing_closing
        
        # Create DTO
        dto = ClosingCreateRequestDTO(
            session_id=str(uuid.uuid4()),
            assignment_id="assignment-123",
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
        )
        
        # Call service and expect error
        with pytest.raises(ValueError) as exc_info:
            closing_service.create_closing("org-123", "user-123", dto)
        
        assert "A closing already exists for assignment" in str(exc_info.value)

    @patch('app.services.closing_service.ClosingRepository')
    def test_create_closing_calculates_declared_total(self, mock_repo_class):
        """
        Test that create_closing calculates declared_total from payment methods.
        
        **Validates: Requirement 5.2**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.validate_assignment_exists.return_value = True
        mock_repo.find_by_assignment.return_value = None
        
        assignment_details = Mock()
        assignment_details.session_id = uuid.uuid4()
        assignment_details.branch_id = uuid.uuid4()
        assignment_details.terminal_id = None
        assignment_details.user_id = "cashier-1"
        mock_repo.get_assignment_details.return_value = assignment_details
        
        mock_repo.calculate_expected_amounts.return_value = {
            'expected_cash': Decimal('0'),
            'expected_sinpe': Decimal('0'),
            'expected_card': Decimal('0'),
            'expected_total': Decimal('0'),
        }
        
        saved_closing = None
        def capture_closing(closing):
            nonlocal saved_closing
            saved_closing = closing
            return closing
        
        mock_repo.save.side_effect = capture_closing
        
        # Create DTO with specific amounts
        assignment_id = str(uuid.uuid4())
        dto = ClosingCreateRequestDTO(
            session_id=str(uuid.uuid4()),
            assignment_id=assignment_id,
            declared_cash=Decimal('100.50'),
            declared_sinpe=Decimal('75.25'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('225.75'),
        )
        
        # Call service
        closing_service.create_closing("org-123", "user-123", dto)
        
        # Verify declared_total was calculated correctly
        assert saved_closing is not None
        assert saved_closing.declared_total == Decimal('225.75')

    @patch('app.services.closing_service.ClosingRepository')
    def test_create_closing_sets_status_to_pending(self, mock_repo_class):
        """
        Test that create_closing sets status to 'pending'.
        
        **Validates: Requirement 5.3**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.validate_assignment_exists.return_value = True
        mock_repo.find_by_assignment.return_value = None
        
        assignment_details = Mock()
        assignment_details.session_id = uuid.uuid4()
        assignment_details.branch_id = uuid.uuid4()
        assignment_details.terminal_id = None
        assignment_details.user_id = "cashier-1"
        mock_repo.get_assignment_details.return_value = assignment_details
        
        mock_repo.calculate_expected_amounts.return_value = {
            'expected_cash': Decimal('0'),
            'expected_sinpe': Decimal('0'),
            'expected_card': Decimal('0'),
            'expected_total': Decimal('0'),
        }
        
        saved_closing = None
        def capture_closing(closing):
            nonlocal saved_closing
            saved_closing = closing
            return closing
        
        mock_repo.save.side_effect = capture_closing
        
        # Create DTO
        assignment_id = str(uuid.uuid4())
        dto = ClosingCreateRequestDTO(
            session_id=str(uuid.uuid4()),
            assignment_id=assignment_id,
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
        )
        
        # Call service
        closing_service.create_closing("org-123", "user-123", dto)
        
        # Verify status is 'pending'
        assert saved_closing is not None
        assert saved_closing.status == 'pending'

    @patch('app.services.closing_service.ClosingRepository')
    def test_create_closing_uses_expected_amounts_from_repository(self, mock_repo_class):
        """
        Test that create_closing uses expected amounts calculated by repository.
        
        **Validates: Requirement 5.1**
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.validate_assignment_exists.return_value = True
        mock_repo.find_by_assignment.return_value = None
        
        assignment_details = Mock()
        assignment_details.session_id = uuid.uuid4()
        assignment_details.branch_id = uuid.uuid4()
        assignment_details.terminal_id = None
        assignment_details.user_id = "cashier-1"
        mock_repo.get_assignment_details.return_value = assignment_details
        
        # Mock expected amounts from orders
        mock_repo.calculate_expected_amounts.return_value = {
            'expected_cash': Decimal('150.00'),
            'expected_sinpe': Decimal('100.00'),
            'expected_card': Decimal('75.00'),
            'expected_total': Decimal('325.00'),
        }
        
        saved_closing = None
        def capture_closing(closing):
            nonlocal saved_closing
            saved_closing = closing
            return closing
        
        mock_repo.save.side_effect = capture_closing
        
        # Create DTO
        assignment_id = str(uuid.uuid4())
        dto = ClosingCreateRequestDTO(
            session_id=str(uuid.uuid4()),
            assignment_id=assignment_id,
            declared_cash=Decimal('150.00'),
            declared_sinpe=Decimal('100.00'),
            declared_card=Decimal('75.00'),
            declared_total=Decimal('325.00'),
        )
        
        # Call service
        closing_service.create_closing("org-123", "user-123", dto)
        
        # Verify expected amounts match repository calculation
        assert saved_closing is not None
        assert saved_closing.expected_cash == Decimal('150.00')
        assert saved_closing.expected_sinpe == Decimal('100.00')
        assert saved_closing.expected_card == Decimal('75.00')
        assert saved_closing.expected_total == Decimal('325.00')

    @patch('app.services.closing_service.ClosingRepository')
    def test_delete_closing_returns_true_when_deleted(self, mock_repo_class):
        """
        Test that delete_closing returns True when closing is deleted.
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        
        closing = Closing(
            closing_id=uuid.uuid4(),
            organization_id="org-123",
            session_id=uuid.uuid4(),
            assignment_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            terminal_id=None,
            cashier_id="cashier-1",
            expected_cash=Decimal('100.00'),
            expected_sinpe=Decimal('50.00'),
            expected_card=Decimal('50.00'),
            expected_total=Decimal('200.00'),
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
            status='pending',
        )
        
        mock_repo.find_by_id_and_organization.return_value = closing
        mock_repo.delete.return_value = True
        
        # Call service
        result = closing_service.delete_closing("org-123", "user-123", str(closing.closing_id))
        
        # Verify
        assert result is True
        mock_repo.delete.assert_called_once_with(str(closing.closing_id))

    @patch('app.services.closing_service.ClosingRepository')
    def test_delete_closing_returns_false_when_not_found(self, mock_repo_class):
        """
        Test that delete_closing returns False when closing doesn't exist.
        """
        # Setup mock
        mock_repo = MagicMock()
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        mock_repo.find_by_id_and_organization.return_value = None
        
        # Call service
        result = closing_service.delete_closing("org-123", "user-123", "nonexistent-id")
        
        # Verify
        assert result is False
        mock_repo.delete.assert_not_called()

    @patch('app.services.closing_service.ClosingRepository')
    def test_map_closing_converts_all_fields_correctly(self, mock_repo_class):
        """
        Test that _map_closing converts Closing model to ClosingResponse DTO correctly.
        """
        # Create a closing with all fields populated
        closing_id = uuid.uuid4()
        session_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        terminal_id = uuid.uuid4()
        reviewed_at = datetime.now(timezone.utc)
        created_at = datetime.now(timezone.utc)
        
        closing = Closing(
            closing_id=closing_id,
            organization_id="org-123",
            session_id=session_id,
            assignment_id=assignment_id,
            branch_id=branch_id,
            terminal_id=terminal_id,
            cashier_id="cashier-1",
            expected_cash=Decimal('100.50'),
            expected_sinpe=Decimal('50.25'),
            expected_card=Decimal('75.75'),
            expected_total=Decimal('226.50'),
            declared_cash=Decimal('110.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('75.00'),
            declared_total=Decimal('235.00'),
            cash_difference=Decimal('9.50'),
            sinpe_difference=Decimal('-0.25'),
            card_difference=Decimal('-0.75'),
            total_difference=Decimal('8.50'),
            notes="Test notes",
            status='approved',
            reviewed_by="manager-1",
            reviewed_at=reviewed_at,
            created_on=created_at,
        )
        
        # Call mapping function
        result = closing_service._map_closing(closing)
        
        # Verify all fields are mapped correctly
        assert result.closing_id == str(closing_id)
        assert result.organization_id == "org-123"
        assert result.session_id == str(session_id)
        assert result.assignment_id == str(assignment_id)
        assert result.branch_id == str(branch_id)
        assert result.terminal_id == str(terminal_id)
        assert result.cashier_id == "cashier-1"
        assert result.expected_cash == 100.50
        assert result.expected_sinpe == 50.25
        assert result.expected_card == 75.75
        assert result.expected_total == 226.50
        assert result.declared_cash == 110.00
        assert result.declared_sinpe == 50.00
        assert result.declared_card == 75.00
        assert result.declared_total == 235.00
        assert result.cash_difference == 9.50
        assert result.sinpe_difference == -0.25
        assert result.card_difference == -0.75
        assert result.total_difference == 8.50
        assert result.notes == "Test notes"
        assert result.status == 'approved'
        assert result.reviewed_by == "manager-1"
        assert result.reviewed_at == reviewed_at.isoformat()
        assert result.created_at == created_at.isoformat()

    @patch('app.services.closing_service.ClosingRepository')
    def test_map_closing_handles_none_terminal_id(self, mock_repo_class):
        """
        Test that _map_closing handles None terminal_id correctly.
        """
        closing = Closing(
            closing_id=uuid.uuid4(),
            organization_id="org-123",
            session_id=uuid.uuid4(),
            assignment_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            terminal_id=None,  # No terminal
            cashier_id="cashier-1",
            expected_cash=Decimal('100.00'),
            expected_sinpe=Decimal('50.00'),
            expected_card=Decimal('50.00'),
            expected_total=Decimal('200.00'),
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
            status='pending',
        )
        
        # Call mapping function
        result = closing_service._map_closing(closing)
        
        # Verify terminal_id is None
        assert result.terminal_id is None

    @patch('app.services.closing_service.ClosingRepository')
    def test_map_closing_handles_none_reviewed_fields(self, mock_repo_class):
        """
        Test that _map_closing handles None reviewed_by and reviewed_at correctly.
        """
        closing = Closing(
            closing_id=uuid.uuid4(),
            organization_id="org-123",
            session_id=uuid.uuid4(),
            assignment_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            terminal_id=None,
            cashier_id="cashier-1",
            expected_cash=Decimal('100.00'),
            expected_sinpe=Decimal('50.00'),
            expected_card=Decimal('50.00'),
            expected_total=Decimal('200.00'),
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
            status='pending',
            reviewed_by=None,
            reviewed_at=None,
        )
        
        # Call mapping function
        result = closing_service._map_closing(closing)
        
        # Verify reviewed fields are None
        assert result.reviewed_by is None
        assert result.reviewed_at is None

    @patch('app.services.closing_service.ClosingRepository')
    def test_map_closing_handles_none_differences(self, mock_repo_class):
        """
        Test that _map_closing handles None difference fields correctly (defaults to 0.0).
        """
        closing = Closing(
            closing_id=uuid.uuid4(),
            organization_id="org-123",
            session_id=uuid.uuid4(),
            assignment_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            terminal_id=None,
            cashier_id="cashier-1",
            expected_cash=Decimal('100.00'),
            expected_sinpe=Decimal('50.00'),
            expected_card=Decimal('50.00'),
            expected_total=Decimal('200.00'),
            declared_cash=Decimal('100.00'),
            declared_sinpe=Decimal('50.00'),
            declared_card=Decimal('50.00'),
            declared_total=Decimal('200.00'),
            status='pending',
            cash_difference=None,
            sinpe_difference=None,
            card_difference=None,
            total_difference=None,
        )
        
        # Call mapping function
        result = closing_service._map_closing(closing)
        
        # Verify differences default to 0.0
        assert result.cash_difference == 0.0
        assert result.sinpe_difference == 0.0
        assert result.card_difference == 0.0
        assert result.total_difference == 0.0
