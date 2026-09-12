"""
Unit tests for calculate_expected_amounts method in ClosingRepository.

**Validates: Requirement 5.1**
WHEN a cashier submits a closing THEN THE System SHALL calculate expected amounts 
from orders associated with the assignment.
"""
import pytest
import uuid
from decimal import Decimal
from sqlalchemy import text

from app.repositories.closing_repository import ClosingRepository
from app.configuration.database_connection import DatabaseConnection


@pytest.mark.unit
# Needs a real database: every test opens DatabaseConnection directly and
# creates a sales_orders table. Marked so the conftest skips it cleanly
# when no database is configured, instead of erroring on credentials.
@pytest.mark.integration
class TestCalculateExpectedAmounts:
    """Test the calculate_expected_amounts method."""

    @pytest.fixture
    def setup_sales_orders_table(self):
        """Create a temporary sales_orders table for testing."""
        with DatabaseConnection() as db:
            # Create the sales_orders table if it doesn't exist
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS sales_orders (
                    order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    assignment_id UUID NOT NULL,
                    payment_method VARCHAR(50) NOT NULL,
                    total DECIMAL(12, 2) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            db.session.commit()
        
        yield
        
        # Cleanup: Drop the table after tests
        with DatabaseConnection() as db:
            db.session.execute(text("DROP TABLE IF EXISTS sales_orders CASCADE"))
            db.session.commit()

    def test_calculate_expected_amounts_with_cash_orders(self, setup_sales_orders_table):
        """Test calculating expected amounts with only cash orders."""
        assignment_id = uuid.uuid4()
        
        # Insert test orders
        with DatabaseConnection() as db:
            db.session.execute(text("""
                INSERT INTO sales_orders (assignment_id, payment_method, total)
                VALUES 
                    (:assignment_id, 'cash', 100.00),
                    (:assignment_id, 'cash', 200.50),
                    (:assignment_id, 'cash', 50.25)
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()
        
        # Calculate expected amounts
        with ClosingRepository() as repo:
            result = repo.calculate_expected_amounts(str(assignment_id))
        
        # Verify results
        assert result['expected_cash'] == Decimal('350.75')
        assert result['expected_sinpe'] == Decimal('0')
        assert result['expected_card'] == Decimal('0')
        assert result['expected_total'] == Decimal('350.75')
        
        # Cleanup
        with DatabaseConnection() as db:
            db.session.execute(text("""
                DELETE FROM sales_orders WHERE assignment_id = :assignment_id
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()

    def test_calculate_expected_amounts_with_sinpe_orders(self, setup_sales_orders_table):
        """Test calculating expected amounts with only sinpe orders."""
        assignment_id = uuid.uuid4()
        
        # Insert test orders
        with DatabaseConnection() as db:
            db.session.execute(text("""
                INSERT INTO sales_orders (assignment_id, payment_method, total)
                VALUES 
                    (:assignment_id, 'sinpe', 150.00),
                    (:assignment_id, 'sinpe', 75.50)
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()
        
        # Calculate expected amounts
        with ClosingRepository() as repo:
            result = repo.calculate_expected_amounts(str(assignment_id))
        
        # Verify results
        assert result['expected_cash'] == Decimal('0')
        assert result['expected_sinpe'] == Decimal('225.50')
        assert result['expected_card'] == Decimal('0')
        assert result['expected_total'] == Decimal('225.50')
        
        # Cleanup
        with DatabaseConnection() as db:
            db.session.execute(text("""
                DELETE FROM sales_orders WHERE assignment_id = :assignment_id
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()

    def test_calculate_expected_amounts_with_card_orders(self, setup_sales_orders_table):
        """Test calculating expected amounts with only card orders."""
        assignment_id = uuid.uuid4()
        
        # Insert test orders
        with DatabaseConnection() as db:
            db.session.execute(text("""
                INSERT INTO sales_orders (assignment_id, payment_method, total)
                VALUES 
                    (:assignment_id, 'card', 300.00),
                    (:assignment_id, 'card', 125.75)
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()
        
        # Calculate expected amounts
        with ClosingRepository() as repo:
            result = repo.calculate_expected_amounts(str(assignment_id))
        
        # Verify results
        assert result['expected_cash'] == Decimal('0')
        assert result['expected_sinpe'] == Decimal('0')
        assert result['expected_card'] == Decimal('425.75')
        assert result['expected_total'] == Decimal('425.75')
        
        # Cleanup
        with DatabaseConnection() as db:
            db.session.execute(text("""
                DELETE FROM sales_orders WHERE assignment_id = :assignment_id
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()

    def test_calculate_expected_amounts_with_mixed_payment_methods(self, setup_sales_orders_table):
        """Test calculating expected amounts with mixed payment methods."""
        assignment_id = uuid.uuid4()
        
        # Insert test orders with all payment methods
        with DatabaseConnection() as db:
            db.session.execute(text("""
                INSERT INTO sales_orders (assignment_id, payment_method, total)
                VALUES 
                    (:assignment_id, 'cash', 100.00),
                    (:assignment_id, 'cash', 50.00),
                    (:assignment_id, 'sinpe', 200.00),
                    (:assignment_id, 'sinpe', 150.00),
                    (:assignment_id, 'card', 300.00),
                    (:assignment_id, 'card', 100.00)
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()
        
        # Calculate expected amounts
        with ClosingRepository() as repo:
            result = repo.calculate_expected_amounts(str(assignment_id))
        
        # Verify results
        assert result['expected_cash'] == Decimal('150.00')
        assert result['expected_sinpe'] == Decimal('350.00')
        assert result['expected_card'] == Decimal('400.00')
        assert result['expected_total'] == Decimal('900.00')
        
        # Cleanup
        with DatabaseConnection() as db:
            db.session.execute(text("""
                DELETE FROM sales_orders WHERE assignment_id = :assignment_id
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()

    def test_calculate_expected_amounts_with_no_orders(self, setup_sales_orders_table):
        """Test calculating expected amounts when no orders exist for assignment."""
        assignment_id = uuid.uuid4()
        
        # Calculate expected amounts (no orders inserted)
        with ClosingRepository() as repo:
            result = repo.calculate_expected_amounts(str(assignment_id))
        
        # Verify all amounts are zero
        assert result['expected_cash'] == Decimal('0')
        assert result['expected_sinpe'] == Decimal('0')
        assert result['expected_card'] == Decimal('0')
        assert result['expected_total'] == Decimal('0')

    def test_calculate_expected_amounts_without_sales_orders_table(self):
        """Test graceful fallback when sales_orders table doesn't exist."""
        assignment_id = uuid.uuid4()
        
        # Ensure the table doesn't exist
        with DatabaseConnection() as db:
            db.session.execute(text("DROP TABLE IF EXISTS sales_orders CASCADE"))
            db.session.commit()
        
        # Calculate expected amounts (should return zeros gracefully)
        with ClosingRepository() as repo:
            result = repo.calculate_expected_amounts(str(assignment_id))
        
        # Verify all amounts are zero (graceful fallback)
        assert result['expected_cash'] == Decimal('0')
        assert result['expected_sinpe'] == Decimal('0')
        assert result['expected_card'] == Decimal('0')
        assert result['expected_total'] == Decimal('0')

    def test_calculate_expected_amounts_with_decimal_precision(self, setup_sales_orders_table):
        """Test that decimal precision is maintained in calculations."""
        assignment_id = uuid.uuid4()
        
        # Insert orders with precise decimal values
        with DatabaseConnection() as db:
            db.session.execute(text("""
                INSERT INTO sales_orders (assignment_id, payment_method, total)
                VALUES 
                    (:assignment_id, 'cash', 99.99),
                    (:assignment_id, 'sinpe', 123.45),
                    (:assignment_id, 'card', 67.89)
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()
        
        # Calculate expected amounts
        with ClosingRepository() as repo:
            result = repo.calculate_expected_amounts(str(assignment_id))
        
        # Verify decimal precision
        assert result['expected_cash'] == Decimal('99.99')
        assert result['expected_sinpe'] == Decimal('123.45')
        assert result['expected_card'] == Decimal('67.89')
        assert result['expected_total'] == Decimal('291.33')
        
        # Cleanup
        with DatabaseConnection() as db:
            db.session.execute(text("""
                DELETE FROM sales_orders WHERE assignment_id = :assignment_id
            """), {"assignment_id": str(assignment_id)})
            db.session.commit()

    def test_calculate_expected_amounts_filters_by_assignment_id(self, setup_sales_orders_table):
        """Test that calculation only includes orders for the specified assignment."""
        assignment_id_1 = uuid.uuid4()
        assignment_id_2 = uuid.uuid4()
        
        # Insert orders for two different assignments
        with DatabaseConnection() as db:
            db.session.execute(text("""
                INSERT INTO sales_orders (assignment_id, payment_method, total)
                VALUES 
                    (:assignment_id_1, 'cash', 100.00),
                    (:assignment_id_1, 'sinpe', 200.00),
                    (:assignment_id_2, 'cash', 500.00),
                    (:assignment_id_2, 'card', 300.00)
            """), {
                "assignment_id_1": str(assignment_id_1),
                "assignment_id_2": str(assignment_id_2)
            })
            db.session.commit()
        
        # Calculate expected amounts for assignment 1
        with ClosingRepository() as repo:
            result = repo.calculate_expected_amounts(str(assignment_id_1))
        
        # Verify only assignment 1 orders are included
        assert result['expected_cash'] == Decimal('100.00')
        assert result['expected_sinpe'] == Decimal('200.00')
        assert result['expected_card'] == Decimal('0')
        assert result['expected_total'] == Decimal('300.00')
        
        # Cleanup
        with DatabaseConnection() as db:
            db.session.execute(text("""
                DELETE FROM sales_orders 
                WHERE assignment_id IN (:assignment_id_1, :assignment_id_2)
            """), {
                "assignment_id_1": str(assignment_id_1),
                "assignment_id_2": str(assignment_id_2)
            })
            db.session.commit()
