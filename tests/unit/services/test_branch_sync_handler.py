import json
from unittest.mock import Mock

import pytest

from app.handlers.sqs_handler import SqsHandler


def event_payload(**overrides):
    return {
        "id": "event-1",
        "occurred_at": "2026-09-11T18:00:00Z",
        "_type": "OrganizationBranchesEvent",
        "event_type": "SAVE_BRANCHES",
        "data": {
            "organization_id": "org-1",
            "branches": [{
                "number": 1,
                "terminals": [{
                    "number": 1,
                    "consecutives": [{"document_type": "01", "current_number": 42}],
                }],
            }],
        },
        **overrides,
    }


def record(message_id, body):
    return {
        "messageId": message_id,
        "body": json.dumps(body),
        "eventSource": "aws:sqs",
        "attributes": {"MessageGroupId": "org-1"},
    }


@pytest.mark.parametrize("wrapped", [False, True])
def test_direct_and_sns_records_use_frozen_contract(wrapped):
    service = Mock()
    body = event_payload()
    if wrapped:
        body = {"Type": "Notification", "Message": json.dumps(body)}

    assert SqsHandler(service).handle({"Records": [record("ok", body)]}, None) == {
        "batchItemFailures": [],
    }
    organization, branches = service.sync_from_hacienda.call_args.args
    assert organization == "org-1"
    assert branches[0].terminals[0].consecutives[0].current_number == 42


def test_partial_batch_failure_retries_only_failed_messages():
    service = Mock()
    service.sync_from_hacienda.side_effect = [RuntimeError("commit failed"), None]
    result = SqsHandler(service).handle({"Records": [
        record("failed", event_payload()),
        record("ok", event_payload()),
    ]}, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "failed"}]}
    assert service.sync_from_hacienda.call_count == 2


@pytest.mark.parametrize("body", [
    [],
    {"Type": "Notification", "Message": "not json"},
    event_payload(event_type="UNKNOWN"),
    event_payload(data={"organization_id": "org-1", "branches": [{"number": True}]}),
    event_payload(data={"organization_id": "", "branches": []}),
    event_payload(data={"organization_id": "org-1", "branches": [{
        "number": 1, "terminals": [{"number": 1, "consecutives": [{
            "document_type": "01", "current_number": -1,
        }]}],
    }]}),
])
def test_entire_batch_validation_failure_returns_retry_identifier(body):
    service = Mock()
    result = SqsHandler(service).handle({"Records": [record("bad", body)]}, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "bad"}]}
    service.sync_from_hacienda.assert_not_called()
