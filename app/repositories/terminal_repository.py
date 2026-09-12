from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func, select, and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.configuration.database_connection import DatabaseConnection
from app.models.terminal import Terminal

logger = logging.getLogger(__name__)


class TerminalRepository(DatabaseConnection):

    def __init__(self):
        super().__init__()

    def insert_from_history(self, **values) -> Terminal:
        """Insert a discovered terminal without overwriting operator-owned fields.

        The conflict target is (organization_id, branch_id, code): Hacienda
        numbers terminals within a branch, so the same code under a different
        branch is a different terminal, not a collision. This used to conflict
        on (organization_id, code) and raise when the existing row belonged to
        another branch — correct given that constraint, but it meant a taxpayer
        with branch 1/terminal 1 and branch 14/terminal 1 could never have its
        branches discovered at all (TSR-254, migration c2d3e4f5a6b7).
        """
        stmt = insert(Terminal).values(**values).on_conflict_do_nothing(
            index_elements=[Terminal.organization_id, Terminal.branch_id, Terminal.code],
        )
        self.session.execute(stmt)
        return self.find_by_code_and_branch(
            values["code"], str(values["branch_id"]), values["organization_id"],
        )

    def find_by_id_and_organization(
        self, terminal_id: str, organization_id: str
    ) -> Optional[Terminal]:
        """Find a terminal by ID and organization."""
        try:
            stmt = select(Terminal).where(
                and_(
                    Terminal.terminal_id == uuid.UUID(terminal_id),
                    Terminal.organization_id == organization_id,
                )
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding terminal {terminal_id} for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def find_by_code_and_organization(
        self, code: int, organization_id: str
    ) -> Optional[Terminal]:
        """Find ANY terminal with this code in the organization.

        Prefer :meth:`find_by_code_and_branch`. Terminal codes are unique per
        branch, not per organization, so this can match several rows and which
        one you get is arbitrary. It returns the first rather than raising
        MultipleResultsFound, because raising would fail on exactly the data
        migration c2d3e4f5a6b7 exists to permit.
        """
        try:
            stmt = select(Terminal).where(
                and_(
                    Terminal.code == code,
                    Terminal.organization_id == organization_id,
                )
            )
            return self.session.execute(stmt).scalars().first()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding terminal by code {code} for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def find_by_code_and_branch(
        self, code: int, branch_id: str, organization_id: str
    ) -> Optional[Terminal]:
        """Find a terminal by its integer code within a specific branch."""
        try:
            stmt = select(Terminal).where(
                and_(
                    Terminal.code == code,
                    Terminal.branch_id == uuid.UUID(branch_id),
                    Terminal.organization_id == organization_id,
                )
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding terminal by code {code} in branch {branch_id}: {e}",
                exc_info=True,
            )
            raise

    def find_by_device_id(self, device_id: str) -> Optional[Terminal]:
        """Find a terminal by device_id (globally unique)."""
        try:
            stmt = select(Terminal).where(Terminal.device_id == device_id)
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding terminal by device_id {device_id}: {e}",
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
    ) -> Tuple[List[Terminal], int]:
        """Find terminals for an organization with pagination."""
        try:
            base = [
                Terminal.organization_id == organization_id,
                Terminal.deleted_on.is_(None),
            ]
            if filters:
                base.extend(filters)
            stmt = select(Terminal).where(and_(*base))
            total = self.session.execute(
                select(func.count()).select_from(stmt.subquery())
            ).scalar() or 0
            if order_by is not None:
                stmt = stmt.order_by(order_by)
            else:
                stmt = stmt.order_by(Terminal.name)
            items = list(
                self.session.execute(
                    stmt.offset((page - 1) * page_size).limit(page_size)
                ).scalars().all()
            )
            return items, total
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding paginated terminals for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def find_all_by_branch(self, branch_id: str) -> List[Terminal]:
        """Find all non-deleted terminals for a branch."""
        try:
            stmt = select(Terminal).where(
                and_(
                    Terminal.branch_id == uuid.UUID(branch_id),
                    Terminal.deleted_on.is_(None),
                )
            ).order_by(Terminal.name)
            return list(self.session.execute(stmt).scalars().all())
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding terminals for branch {branch_id}: {e}",
                exc_info=True,
            )
            raise

    def find_all_by_branch_ids(self, branch_ids: List[str]) -> Dict[str, List[Terminal]]:
        """Batch query terminals by list of branch IDs.

        Returns a dict keyed by branch_id string, each value being a list of
        non-deleted terminals for that branch.
        """
        if not branch_ids:
            return {}
        try:
            uuids = [uuid.UUID(bid) for bid in branch_ids]
            stmt = select(Terminal).where(
                and_(
                    Terminal.branch_id.in_(uuids),
                    Terminal.deleted_on.is_(None),
                )
            ).order_by(Terminal.name)
            terminals = list(self.session.execute(stmt).scalars().all())
            result: Dict[str, List[Terminal]] = {bid: [] for bid in branch_ids}
            for terminal in terminals:
                key = str(terminal.branch_id)
                if key in result:
                    result[key].append(terminal)
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error finding terminals by branch ids: {e}", exc_info=True)
            raise

    def save(self, terminal: Terminal) -> Terminal:
        """Save or update a terminal."""
        try:
            terminal = self.session.merge(terminal)
            self.session.flush()
            return terminal
        except SQLAlchemyError as e:
            logger.error(f"Error saving terminal: {e}", exc_info=True)
            raise

    def delete(self, terminal_id: str) -> bool:
        """Delete a terminal by ID."""
        try:
            stmt = select(Terminal).where(Terminal.terminal_id == uuid.UUID(terminal_id))
            terminal = self.session.execute(stmt).scalar_one_or_none()
            if not terminal:
                return False
            self.session.delete(terminal)
            self.session.flush()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Error deleting terminal {terminal_id}: {e}", exc_info=True)
            raise

    def validate_branch_exists(self, branch_id: str, organization_id: str) -> bool:
        """Check if a branch exists and belongs to the organization."""
        try:
            from app.models.branch import Branch

            stmt = select(func.count()).select_from(Branch).where(
                and_(
                    Branch.branch_id == uuid.UUID(branch_id),
                    Branch.organization_id == organization_id,
                )
            )
            count = self.session.execute(stmt).scalar() or 0
            return count > 0
        except SQLAlchemyError as e:
            logger.error(
                f"Error validating branch {branch_id} for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def has_active_assignments(self, terminal_id: str) -> bool:
        """Check if a terminal has active assignments."""
        try:
            from app.models.assignment import Assignment

            stmt = select(func.count()).select_from(Assignment).where(
                and_(
                    Assignment.terminal_id == uuid.UUID(terminal_id),
                    Assignment.status == 1,
                )
            )
            count = self.session.execute(stmt).scalar() or 0
            return count > 0
        except SQLAlchemyError as e:
            logger.error(
                f"Error checking active assignments for terminal {terminal_id}: {e}",
                exc_info=True,
            )
            raise
