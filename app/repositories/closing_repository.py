from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple
import uuid
from decimal import Decimal

from sqlalchemy import func, select, and_
from sqlalchemy.exc import SQLAlchemyError

from app.configuration.database_connection import DatabaseConnection
from app.models.closing import Closing

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpectedAmounts:
    """What the system expected a till to hold, per payment method.

    **`available` is the important field.** These figures come from a
    `sales_orders` table that DOES NOT EXIST — `to_regclass('sales_orders')` is
    null in dev — so the query has always fallen into its own except branch and
    returned zeros. The docstring said so ("this is expected if sales_orders table
    doesn't exist yet") and nothing downstream could tell that apart from a till
    that genuinely expected nothing.

    That distinction is not cosmetic. `closings.cash_difference` is a GENERATED
    column, `declared_cash - expected_cash`, so a zero expectation reports the
    cashier's entire declared cash as a SURPLUS — on every closing, for ever. An
    unavailable expectation and a real zero must therefore be different values in
    the type, so a caller cannot use one as the other by accident.

    No closing exists yet in dev (0 rows), so nothing has been mis-reconciled.
    Computing this properly needs the payment split, which lives on documents in
    sales-be, not in any table this service owns — recorded on the roadmap rather
    than guessed at here.
    """

    expected_cash: Decimal
    expected_sinpe: Decimal
    expected_card: Decimal
    expected_total: Decimal
    #: False when the source could not be read at all — the amounts are then
    #: placeholders, not measurements.
    available: bool = True

    @classmethod
    def unavailable(cls) -> "ExpectedAmounts":
        zero = Decimal("0")
        return cls(zero, zero, zero, zero, available=False)


class ClosingRepository(DatabaseConnection):

    def __init__(self):
        super().__init__()

    def find_by_id_and_organization(
        self, closing_id: str, organization_id: str
    ) -> Optional[Closing]:
        """Find a closing by ID and organization."""
        try:
            stmt = select(Closing).where(
                and_(
                    Closing.closing_id == uuid.UUID(closing_id),
                    Closing.organization_id == organization_id,
                )
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding closing {closing_id} for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def find_all_by_organization(
        self,
        organization_id: str,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        branch_id: Optional[str] = None,
    ) -> List[Closing]:
        """Find all closings for an organization with optional filters."""
        try:
            filters = [Closing.organization_id == organization_id]

            if session_id is not None:
                filters.append(Closing.session_id == uuid.UUID(session_id))

            if status is not None:
                filters.append(Closing.status == status)

            if branch_id is not None:
                filters.append(Closing.branch_id == uuid.UUID(branch_id))

            stmt = select(Closing).where(and_(*filters)).order_by(Closing.created_at.desc())

            closings = list(self.session.execute(stmt).scalars().all())
            return closings
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding closings for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def find_all_paginated(
        self,
        organization_id: str,
        filters: list = None,
        order_by=None,
        page: int = 1,
        page_size: int = 12,
    ) -> Tuple[List[Closing], int]:
        """Find closings for an organization with pagination."""
        try:
            base = [
                Closing.organization_id == organization_id,
                Closing.deleted_on.is_(None),
            ]
            if filters:
                base.extend(filters)
            stmt = select(Closing).where(and_(*base))
            total = self.session.execute(
                select(func.count()).select_from(stmt.subquery())
            ).scalar() or 0
            if order_by is not None:
                stmt = stmt.order_by(order_by)
            else:
                stmt = stmt.order_by(Closing.created_on.desc())
            items = list(
                self.session.execute(
                    stmt.offset((page - 1) * page_size).limit(page_size)
                ).scalars().all()
            )
            return items, total
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding paginated closings for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def find_by_assignment(self, assignment_id: str) -> Optional[Closing]:
        """Find a closing by assignment ID (one closing per assignment)."""
        try:
            stmt = select(Closing).where(Closing.assignment_id == uuid.UUID(assignment_id))
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding closing for assignment {assignment_id}: {e}",
                exc_info=True,
            )
            raise

    def save(self, closing: Closing) -> Closing:
        """Save or update a closing."""
        try:
            closing = self.session.merge(closing)
            self.session.flush()
            return closing
        except SQLAlchemyError as e:
            logger.error(f"Error saving closing: {e}", exc_info=True)
            raise

    def delete(self, closing_id: str) -> bool:
        """Delete a closing by ID."""
        try:
            stmt = select(Closing).where(Closing.closing_id == uuid.UUID(closing_id))
            closing = self.session.execute(stmt).scalar_one_or_none()
            if not closing:
                return False
            self.session.delete(closing)
            self.session.flush()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Error deleting closing {closing_id}: {e}", exc_info=True)
            raise

    def validate_assignment_exists(self, assignment_id: str, organization_id: str) -> bool:
        """Check if an assignment exists and belongs to the organization."""
        try:
            from app.models.assignment import Assignment

            stmt = select(func.count()).select_from(Assignment).where(
                and_(
                    Assignment.assignment_id == uuid.UUID(assignment_id),
                    Assignment.organization_id == organization_id,
                )
            )
            count = self.session.execute(stmt).scalar() or 0
            return count > 0
        except SQLAlchemyError as e:
            logger.error(
                f"Error validating assignment {assignment_id} for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def get_assignment_details(self, assignment_id: str):
        """Get assignment details including session, branch, terminal, and cashier."""
        try:
            from app.models.assignment import Assignment

            stmt = select(Assignment).where(Assignment.assignment_id == uuid.UUID(assignment_id))
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error getting assignment details for {assignment_id}: {e}",
                exc_info=True,
            )
            raise

    def calculate_expected_amounts(self, assignment_id: str) -> ExpectedAmounts:
        """Calculate expected amounts from orders for an assignment.

        NOTE: This assumes a sales_orders table exists with columns:
        - assignment_id (UUID)
        - payment_method (string: 'cash', 'sinpe', 'card')
        - total (decimal)

        If the table doesn't exist yet, this will return zeros.
        """
        try:
            # Check if sales_orders table exists
            # For now, we'll use a raw SQL query to handle the case where the table might not exist
            from sqlalchemy import text

            query = text("""
                SELECT
                    COALESCE(SUM(CASE WHEN payment_method = 'cash' THEN total ELSE 0 END), 0) as cash,
                    COALESCE(SUM(CASE WHEN payment_method = 'sinpe' THEN total ELSE 0 END), 0) as sinpe,
                    COALESCE(SUM(CASE WHEN payment_method = 'card' THEN total ELSE 0 END), 0) as card,
                    COALESCE(SUM(total), 0) as total
                FROM sales_orders
                WHERE assignment_id = :assignment_id
            """)

            result = self.session.execute(query, {"assignment_id": str(assignment_id)}).one()

            return ExpectedAmounts(
                expected_cash=Decimal(str(result.cash)),
                expected_sinpe=Decimal(str(result.sinpe)),
                expected_card=Decimal(str(result.card)),
                expected_total=Decimal(str(result.total)),
            )
        except Exception as e:
            # Not "expected", and not zeros: UNAVAILABLE. `sales_orders` does not
            # exist, so this branch is the only one that has ever run, and the
            # zeros it returns become a full-declared-amount surplus through the
            # generated difference columns. The flag is what lets a caller tell
            # the two apart; the log says which source is missing.
            logger.warning(
                "Expected amounts UNAVAILABLE for assignment %s: %s. The payment "
                "split has no source in this service — it lives on documents in "
                "sales-be — so the returned zeros are placeholders, not a "
                "measurement, and every difference computed from them is the "
                "declared amount itself.",
                assignment_id, e,
            )
            return ExpectedAmounts.unavailable()
