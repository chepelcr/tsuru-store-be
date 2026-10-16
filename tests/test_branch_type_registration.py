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
from app.services.branch_type_service import get_branch_types


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
        first = repo.ensure_default_type("org-1")
        repeated = repo.ensure_default_type("org-1")
        other = repo.ensure_default_type("org-2")
        assert first.branch_type_id == repeated.branch_type_id
        assert other.branch_type_id != first.branch_type_id
        assert first.name == "Branch"
        assert first.is_default is True
        assert [row.code for row in repo.find_all_by_organization("org-1")] == ["branch"]


def test_new_organization_without_branches_gets_a_saved_default_on_catalog_read(engine):
    for _ in range(2):
        result = get_branch_types("fresh-org", "user-1")
        assert len(result.data) == 1
        assert (result.data[0].code, result.data[0].name, result.data[0].is_default) == ("branch", "Branch", True)
    with Session(engine) as session:
        assert len(session.scalars(select(BranchType)).all()) == 1
        assert session.scalars(select(Branch)).all() == []


def test_registration_reuses_custom_catalog_and_creates_no_legacy_defaults(engine):
    with Session(engine) as session, session.begin():
        session.add(BranchType(organization_id="custom", code="shop", name="Shop", created_by="operator"))
    service = BranchSyncService()
    for org in ["custom", "new", "new"]:
        service.sync_from_hacienda(org, [{"number": 1, "terminals": [{"number": 1}]}])
    with Session(engine) as session:
        assert {(row.organization_id, row.code) for row in session.scalars(select(BranchType))} == {("custom", "shop"), ("custom", "branch"), ("new", "branch")}
        assert {(row.organization_id, row.type) for row in session.scalars(select(Branch))} == {("custom", "branch"), ("new", "branch")}


def test_empty_discovery_does_not_invent_types(engine):
    BranchSyncService().sync_from_hacienda("empty", [])
    with Session(engine) as session:
        assert session.scalars(select(BranchType)).all() == []


def test_default_bootstrap_preserves_customization_and_existing_assignments(engine):
    with Session(engine) as session, session.begin():
        repo = BranchTypeRepository.from_session(session)
        default = repo.ensure_default_type("org-1")
        default.name, default.icon, default.sort_order = "Main branch", "warehouse", 9
        session.add(BranchType(organization_id="org-1", code="shop", name="Shop", created_by="operator"))
        session.add(Branch(organization_id="org-1", code=1, name="Existing", type="shop", created_by="operator"))
    BranchSyncService().sync_from_hacienda("org-1", [{"number": 1, "terminals": [{"number": 1}]}])
    with Session(engine) as session:
        repo = BranchTypeRepository.from_session(session)
        default = repo.ensure_default_type("org-1")
        assert (default.name, default.icon, default.sort_order) == ("Main branch", "warehouse", 9)
        assert repo.find_all_by_organization("org-1")[0].is_default is True
        assert session.scalar(select(Branch)).type == "shop"
