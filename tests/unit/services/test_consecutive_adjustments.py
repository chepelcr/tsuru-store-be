"""Manual consecutive edits: raise-only, audited, permission-guarded (TSR-327)."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.dtos.requests.consecutive_request_dto import (
    ConsecutiveCreateRequestDTO,
    ConsecutiveUpdateRequestDTO,
)
from app.repositories import permission_repository
from app.services import consecutive_service
from app.services.consecutive_service import ConsecutiveConflictError

ORG = "org-1"
USER = "user-1"
CID = str(uuid.uuid4())


class FakeRepo:
    """Stands in for ConsecutiveRepository (a context manager)."""

    def __init__(self, row=None):
        self.row = row
        self.adjustments = []
        self.locked = False

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def lock_for_update(self, consecutive_id, organization_id):
        self.locked = True
        return self.row

    def add_adjustment(self, adjustment):
        self.adjustments.append(adjustment)
        return adjustment

    def find_by_terminal_and_doc_type(self, *args):
        return None

    def save(self, consecutive):
        consecutive.consecutive_id = uuid.UUID(CID)
        self.row = consecutive
        return consecutive


def _row(current):
    return SimpleNamespace(
        consecutive_id=uuid.UUID(CID),
        terminal_id=uuid.uuid4(),
        document_type_id=1,
        current_number=current,
    )


@pytest.fixture
def repo(monkeypatch):
    fake = FakeRepo(_row(42))
    monkeypatch.setattr(consecutive_service, "ConsecutiveRepository", fake)
    monkeypatch.setattr(consecutive_service, "get_consecutive", lambda *a: "reloaded")
    return fake


def test_raises_the_counter_and_writes_one_audit_row(repo):
    dto = ConsecutiveUpdateRequestDTO(current_number=100, reason="Hacienda sync gap")
    assert consecutive_service.update_consecutive_number(ORG, USER, CID, dto) == "reloaded"
    assert repo.locked, "must take the allocator's row lock"
    assert repo.row.current_number == 100
    [adj] = repo.adjustments
    assert (adj.previous_number, adj.new_number, adj.changed_by) == (42, 100, USER)
    assert adj.reason == "Hacienda sync gap"


@pytest.mark.parametrize("value", [42, 41, 1])
def test_never_lowers_or_repeats_the_counter(repo, value):
    dto = ConsecutiveUpdateRequestDTO(current_number=value, reason="oops")
    with pytest.raises(ConsecutiveConflictError) as err:
        consecutive_service.update_consecutive_number(ORG, USER, CID, dto)
    assert err.value.current_number == 42
    assert repo.row.current_number == 42
    assert repo.adjustments == []


def test_missing_consecutive_returns_none(repo):
    repo.row = None
    dto = ConsecutiveUpdateRequestDTO(current_number=100, reason="whatever")
    assert consecutive_service.update_consecutive_number(ORG, USER, CID, dto) is None


def test_blank_reason_is_rejected(repo):
    dto = ConsecutiveUpdateRequestDTO(current_number=100, reason="   x ")
    with pytest.raises(ValueError):
        consecutive_service.update_consecutive_number(ORG, USER, CID, dto)


def test_eleven_digits_is_rejected_by_the_dto():
    with pytest.raises(Exception):
        ConsecutiveUpdateRequestDTO(current_number=10_000_000_000, reason="too big")


def test_starting_above_zero_is_audited(monkeypatch):
    fake = FakeRepo()
    monkeypatch.setattr(consecutive_service, "ConsecutiveRepository", fake)
    monkeypatch.setattr(consecutive_service, "get_consecutive", lambda *a: "reloaded")
    for repo_name in ("TerminalRepository", "DocumentTypeRepository"):
        stub = MagicMock()
        stub.return_value.__enter__.return_value.find_by_id_and_organization.return_value = object()
        stub.return_value.__enter__.return_value.find_by_id.return_value = object()
        monkeypatch.setattr(consecutive_service, repo_name, stub)

    dto = ConsecutiveCreateRequestDTO(
        terminal_id=str(uuid.uuid4()), document_type_id=1, initial_number=500, reason="migrated"
    )
    consecutive_service.create_consecutive(ORG, USER, dto)
    [adj] = fake.adjustments
    assert adj.previous_number is None and adj.new_number == 500

    no_reason = ConsecutiveCreateRequestDTO(
        terminal_id=str(uuid.uuid4()), document_type_id=1, initial_number=500
    )
    with pytest.raises(ValueError):
        consecutive_service.create_consecutive(ORG, USER, no_reason)


def test_format_document_consecutive_is_hacienda_width():
    assert consecutive_service.format_document_consecutive(1, 2, "1", 43) == "00100002010000000043"


# ── permission_repository ───────────────────────────────────────────────────

def _decision(monkeypatch, **row):
    permission_repository.clear_cache()
    defaults = dict(is_platform_admin=False, available=True, is_owner=False, granted=False)
    defaults.update(row)
    monkeypatch.setattr(
        permission_repository, "_lookup",
        lambda *a: permission_repository.__dict__["_decide"](SimpleNamespace(**defaults)),
    )


@pytest.mark.parametrize(
    "row,expected",
    [
        (dict(is_platform_admin=True, available=False), True),
        (dict(is_owner=True), True),
        (dict(granted=True), True),
        (dict(), False),
        # A disabled module/submodule beats every grant, owner included.
        (dict(is_owner=True, available=False), False),
        (dict(granted=True, available=False), False),
    ],
)
def test_permission_decision(monkeypatch, row, expected):
    _decision(monkeypatch, **row)
    assert permission_repository.has_permission(ORG, USER, "admin", "update", "consecutives") is expected


def test_permission_fails_closed(monkeypatch):
    permission_repository.clear_cache()

    def boom(*a):
        raise RuntimeError("db down")

    monkeypatch.setattr(permission_repository, "_lookup", boom)
    assert permission_repository.has_permission(ORG, USER, "admin", "read", "consecutives") is False
    assert permission_repository.has_permission(ORG, None, "admin", "read", "consecutives") is False
