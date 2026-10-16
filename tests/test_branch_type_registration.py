"""Branch registration persists a real org-scoped type instead of phantom defaults."""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
import pytest

from app.configuration.database_connection import DatabaseConnection
from app.models.base import Base
from app.models.branch import Branch
from app.models.branch_type import BranchType
from app.models.country import Country
from app.models.terminal import Terminal
from app.repositories.branch_type_repository import BranchTypeRepository
from app.services.branch_sync_service import BranchSyncService


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Country.__table__, Branch.__table__, BranchType.__table__, Terminal.__table__])
    monkeypatch.setattr(DatabaseConnection, "_engine", engine)
    monkeypatch.setattr(DatabaseConnection, "_session_factory", sessionmaker(bind=engine, expire_on_commit=False))
    yield engine
    engine.dispose()


def test_default_catalog_creation_is_idempotent_and_scoped(engine):
    with Session(engine) as session, session.begin():
        repo = BranchTypeRepository.from_session(session)
        first = repo.ensure_general_type("org-1")
        repeated = repo.ensure_general_type("org-1")
        other = repo.ensure_general_type("org-2")
        assert first.branch_type_id == repeated.branch_type_id
        assert other.branch_type_id != first.branch_type_id
        assert [row.code for row in repo.find_all_by_organization("org-1")] == ["general"]


def test_registration_reuses_custom_catalog_and_creates_no_legacy_defaults(engine):
    with Session(engine) as session, session.begin():
        session.add(BranchType(organization_id="custom", code="shop", name="Shop", created_by="operator"))
    service = BranchSyncService()
    for org in ["custom", "new", "new"]:
        service.sync_from_hacienda(org, [{"number": 1, "terminals": [{"number": 1}]}])
    with Session(engine) as session:
        assert {(row.organization_id, row.code) for row in session.scalars(select(BranchType))} == {("custom", "shop"), ("new", "general")}
        assert {(row.organization_id, row.type) for row in session.scalars(select(Branch))} == {("custom", "shop"), ("new", "general")}


def test_empty_discovery_does_not_invent_types(engine):
    BranchSyncService().sync_from_hacienda("empty", [])
    with Session(engine) as session:
        assert session.scalars(select(BranchType)).all() == []
