from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert

from app.configuration.database_connection import DatabaseConnection
from app.models.branch import Branch
from app.models.branch_type import BranchType

logger = logging.getLogger(__name__)


class BranchTypeRepository(DatabaseConnection):

    def __init__(self):
        super().__init__()

    def ensure_default_type(self, organization_id: str) -> BranchType:
        """Every organization gets its own editable Branch default.

        Concurrent registration/history messages must reuse the same catalog row.
        """
        self.session.execute(
            insert(BranchType).values(
                organization_id=organization_id, code="branch", name="Branch",
                icon="store", color="primary", sort_order=0, status=1, is_default=True, created_by="system",
            ).on_conflict_do_nothing(index_elements=["organization_id", "code"])
        )
        branch_type = self.find_by_code_and_organization("branch", organization_id)
        if not branch_type.is_default:
            branch_type.is_default = True
            self.session.flush()
        return branch_type

    def find_all_by_organization(self, organization_id: str) -> List[BranchType]:
        """All non-deleted branch types for an organization, in display order."""
        try:
            stmt = (
                select(BranchType)
                .where(
                    and_(
                        BranchType.organization_id == organization_id,
                        BranchType.deleted_on.is_(None),
                    )
                )
                .order_by(BranchType.is_default.desc(), BranchType.sort_order, BranchType.name)
            )
            return list(self.session.execute(stmt).scalars().all())
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding branch types for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def find_by_id_and_organization(
        self, branch_type_id: str, organization_id: str
    ) -> Optional[BranchType]:
        """Find a branch type by ID, scoped to its organization."""
        try:
            stmt = select(BranchType).where(
                and_(
                    BranchType.branch_type_id == uuid.UUID(branch_type_id),
                    BranchType.organization_id == organization_id,
                    BranchType.deleted_on.is_(None),
                )
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except ValueError:
            # Not a UUID — treat as "no such branch type" rather than a 500.
            return None
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding branch type {branch_type_id} for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def find_by_code_and_organization(
        self, code: str, organization_id: str
    ) -> Optional[BranchType]:
        """Find a branch type by its code within an organization."""
        try:
            stmt = select(BranchType).where(
                and_(
                    BranchType.code == code,
                    BranchType.organization_id == organization_id,
                    BranchType.deleted_on.is_(None),
                )
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding branch type by code {code} for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def count_branches_using(self, code: str, organization_id: str) -> int:
        """How many non-deleted branches still reference this type code."""
        try:
            stmt = select(func.count()).select_from(Branch).where(
                and_(
                    Branch.organization_id == organization_id,
                    Branch.type == code,
                    Branch.deleted_on.is_(None),
                )
            )
            return self.session.execute(stmt).scalar() or 0
        except SQLAlchemyError as e:
            logger.error(
                f"Error counting branches using type {code} for organization {organization_id}: {e}",
                exc_info=True,
            )
            raise

    def save(self, branch_type: BranchType) -> BranchType:
        """Save or update a branch type."""
        try:
            branch_type = self.session.merge(branch_type)
            self.session.flush()
            return branch_type
        except SQLAlchemyError as e:
            logger.error(f"Error saving branch type: {e}", exc_info=True)
            raise

    def delete(self, branch_type_id: str) -> bool:
        """Delete a branch type by ID."""
        try:
            stmt = select(BranchType).where(
                BranchType.branch_type_id == uuid.UUID(branch_type_id)
            )
            branch_type = self.session.execute(stmt).scalar_one_or_none()
            if not branch_type:
                return False
            self.session.delete(branch_type)
            self.session.flush()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Error deleting branch type {branch_type_id}: {e}", exc_info=True)
            raise
