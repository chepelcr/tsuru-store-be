"""Real PostgreSQL concurrency probes, isolated in a disposable schema.

Set STORE_BRANCH_SYNC_TEST_DATABASE_URL to an isolated PostgreSQL test database.
The test creates and drops only its own randomly named schema; no cloud DB needed.
"""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import threading
import time
from unittest.mock import Mock
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.configuration.database_connection import DatabaseConnection
from app.models.base import Base
from app.models.branch import Branch
from app.models.branch_type import BranchType
from app.models.consecutive import Consecutive
from app.models.document_type import DocumentType
from app.models.terminal import Terminal
from app.repositories.consecutive_repository import ConsecutiveRepository
from app.services.branch_sync_service import BranchSyncService



def branches(current_number=42, *, branch_number=1, terminal_number=1, **metadata):
    return [{
        "number": branch_number,
        "terminals": [{
            "number": terminal_number,
            "consecutives": [{"documentType": "01", "currentNumber": current_number}],
        }],
        **metadata,
    }]


def only_counter(engine):
    with Session(engine) as session:
        return session.execute(select(Consecutive)).scalar_one()


def wait_for_blocked_transaction(engine, blocker_pid):
    """Prove the second transaction reached PostgreSQL and waits on the first."""
    deadline = time.monotonic() + 5
    with engine.connect() as connection:
        while time.monotonic() < deadline:
            blocked = connection.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                "WHERE :blocker = ANY(pg_blocking_pids(pid)))"
            ), {"blocker": blocker_pid})
            if blocked:
                return
            time.sleep(0.01)
    pytest.fail("Concurrent transaction never reached the expected row lock")


def test_duplicate_reordered_history_never_rewinds_or_adds_one(sync_engine):
    service = BranchSyncService()
    for current in [42, 42, 7, 99, 42]:
        service.sync_from_hacienda("org-1", branches(current))
    with Session(sync_engine) as session:
        for model in [Branch, Terminal, Consecutive]:
            assert session.scalar(select(func.count()).select_from(model)) == 1
        counter = session.scalar(select(Consecutive))
        assert counter.current_number == 99
        assert counter.document_type_id == 101
        assert counter.created_by == "hacienda-history"
        assert session.scalar(select(Branch)).type == "stand"


def test_preserves_operator_branch_and_terminal_edits(sync_engine):
    service = BranchSyncService()
    with Session(sync_engine) as session, session.begin():
        session.add(BranchType(organization_id="org-1", code="shop", name="Tienda", sort_order=1, created_by="operator"))
        session.add(BranchType(organization_id="org-1", code="restaurant", name="Restaurante", sort_order=2, created_by="operator"))
    service.sync_from_hacienda("org-1", branches(
        name="Historical name",
        phone={"countryCode": "506", "number": "22223333"},
        residence={"provinceCode": 1, "cantonCode": 2, "districtCode": 3, "address": "Historical address"},
    ))
    with Session(sync_engine) as session, session.begin():
        branch = session.scalar(select(Branch))
        assert branch.type == "shop"
        assert branch.phone == "+506 22223333"
        assert branch.created_by == "hacienda-history"
        branch.name, branch.type, branch.address = "Operator name", "restaurant", "Operator address"
        branch.state_id = 7
        session.scalar(select(Terminal)).name = "Operator terminal"
    service.sync_from_hacienda("org-1", branches(87, name="Replacement name"))
    with Session(sync_engine) as session:
        branch = session.scalar(select(Branch))
        assert (branch.name, branch.type, branch.address, branch.state_id) == (
            "Operator name", "restaurant", "Operator address", 7,
        )
        assert session.scalar(select(Terminal)).name == "Operator terminal"
        assert session.scalar(select(Consecutive)).current_number == 87


def test_two_branches_may_each_have_terminal_one(sync_engine):
    """The (branch, terminal) pair identifies the point of sale, not the code.

    Hacienda's consecutive is branch(3) + terminal(5), so terminal 1 under
    branch 1 and terminal 1 under branch 14 are two different terminals — and a
    real taxpayer has exactly that. The organization-wide unique constraint
    this replaces rejected the second one, which meant VILMA CORELLA ARTAVIA's
    branches could never be discovered at all: the sync refused to reassign the
    existing terminal and rolled the whole message back (TSR-254).
    """
    service = BranchSyncService()
    service.sync_from_hacienda("org-1", branches(branch_number=1,  terminal_number=1))
    service.sync_from_hacienda("org-1", branches(branch_number=14, terminal_number=1))

    with Session(sync_engine) as session:
        assert sorted(b.code for b in session.scalars(select(Branch)).all()) == [1, 14]
        pairs = sorted(
            (b.code, t.code)
            for t in session.scalars(select(Terminal)).all()
            for b in [session.get(Branch, t.branch_id)]
        )
        assert pairs == [(1, 1), (14, 1)]
        # Two terminals, so two independent counters — a shared code must not
        # collapse them onto one fiscal sequence.
        assert len(session.scalars(select(Consecutive)).all()) == 2


def test_the_same_branch_and_terminal_twice_is_still_one_terminal(sync_engine):
    """Loosening the constraint must not lose idempotency within a branch."""
    service = BranchSyncService()
    service.sync_from_hacienda("org-1", branches(branch_number=7,  terminal_number=3))
    service.sync_from_hacienda("org-1", branches(branch_number=7,  terminal_number=3))

    with Session(sync_engine) as session:
        assert len(session.scalars(select(Branch)).all()) == 1
        assert len(session.scalars(select(Terminal)).all()) == 1
        assert len(session.scalars(select(Consecutive)).all()) == 1


def test_unknown_document_type_rolls_back_entire_message(sync_engine):
    payload = branches()
    payload[0]["terminals"][0]["consecutives"].append({"documentType": "99", "currentNumber": 10})
    with pytest.raises(ValueError, match="Unknown document type"):
        BranchSyncService().sync_from_hacienda("org-1", payload)
    with Session(sync_engine) as session:
        assert session.scalar(select(func.count()).select_from(Branch)) == 0


def test_concurrent_duplicate_initial_upserts(sync_engine):
    start = threading.Barrier(2)

    def sync(number):
        start.wait(timeout=5)
        BranchSyncService().sync_from_hacienda("org-1", branches(number))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(sync, [42, 87]))
    assert only_counter(sync_engine).current_number == 87
    with Session(sync_engine) as session:
        assert session.scalar(select(func.count()).select_from(Terminal)) == 1


@pytest.mark.parametrize("historical_number, expected", [(7, 43), (100, 100)])
def test_sync_waits_for_sales_allocator_row_lock(sync_engine, historical_number, expected):
    BranchSyncService().sync_from_hacienda("org-1", branches())
    started = threading.Event()

    def sync():
        started.set()
        BranchSyncService().sync_from_hacienda("org-1", branches(historical_number))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(sync_engine) as sale_session:
            # This is the sales allocator's SELECT FOR UPDATE / increment flow.
            row = sale_session.execute(select(Consecutive).with_for_update()).scalar_one()
            blocker_pid = sale_session.scalar(text("SELECT pg_backend_pid()"))
            future = pool.submit(sync)
            assert started.wait(timeout=5)
            wait_for_blocked_transaction(sync_engine, blocker_pid)
            row.current_number += 1
            sale_session.commit()
        future.result(timeout=10)
    assert only_counter(sync_engine).current_number == expected


def test_sales_allocator_waits_for_sync_row_lock(sync_engine):
    BranchSyncService().sync_from_hacienda("org-1", branches())
    existing = only_counter(sync_engine)
    started = threading.Event()

    def allocate():
        with Session(sync_engine) as session, session.begin():
            started.set()
            counter = session.execute(select(Consecutive).with_for_update()).scalar_one()
            counter.current_number += 1

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(sync_engine) as session:
            repo = ConsecutiveRepository.from_session(session)
            repo.raise_from_history("org-1", str(existing.terminal_id), 101, 100)
            blocker_pid = session.scalar(text("SELECT pg_backend_pid()"))
            future = pool.submit(allocate)
            assert started.wait(timeout=5)
            wait_for_blocked_transaction(sync_engine, blocker_pid)
            session.commit()
        future.result(timeout=10)
    assert only_counter(sync_engine).current_number == 101


def test_commit_failure_is_not_acknowledged(sync_engine, monkeypatch):
    monkeypatch.setattr(Session, "commit", Mock(side_effect=RuntimeError("commit failed")))
    with pytest.raises(RuntimeError, match="commit failed"):
        BranchSyncService().sync_from_hacienda("org-1", branches())
    with Session(sync_engine) as session:
        assert session.scalar(select(func.count()).select_from(Branch)) == 0


def test_counter_bigint_migration_roundtrip_and_full_serial(sync_engine):
    path = Path(__file__).parents[2] / "alembic/versions/be1f2a3b4c5d_consecutive_bigint.py"
    spec = importlib.util.spec_from_file_location("counter_bigint_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sync_engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        with operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
    BranchSyncService().sync_from_hacienda("org-1", branches(9999999999))
    assert only_counter(sync_engine).current_number == 9999999999
