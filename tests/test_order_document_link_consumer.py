"""The order-link consumer: dispatch, idempotence, and the two ordinary no-ops.

The wire format under test is produced by sales-be's
`jbiller_common.hacienda.dtos.events.order_document_link_event`. The literal
JSON below is a sample of that publisher's output — if the two drift, this is
where it shows.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.dtos.requests.order_document_link_dto import OrderDocumentLinkEvent
from app.handlers.sqs_handler import SqsHandler
from app.services.order_service import is_order_billed, link_order_document

#: The producer's committed wire shape, byte-identical to sales-be's copy at
#: `shared/tests/fixtures/link_order_document_event.json`. Both repos assert
#: against it; see `shared/tests/test_order_link_contract.py` there.
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "link_order_document_event.json"

PUBLISHED = {
    "id": "2b0d6b6e-0000-4000-8000-000000000001",
    "event_type": "LINK_ORDER_DOCUMENT",
    "occurred_at": "2026-09-20T14:02:11Z",
    "_type": "OrderDocumentLinkEvent",
    "data": {
        "organization_id": "org-1",
        "order_document_number": "PM-000123",
        "order_source": "manual",
        "document": {
            "document_id": "9f3a0000-0000-0000-0000-000000000001",
            "document_number": 10427,
            "document_type": "01",
            "consecutive_number": "00100001010000000123",
            "document_key": "506" + "0" * 47,
            "issued_on": "2026-09-20T14:02:11+00:00",
            "status": 1,
            "total_amount": 125340.0,
            "currency_code": "CRC",
        },
    },
}


def record(body: dict, *, sns_wrapped: bool = False):
    payload = {"Message": json.dumps(body)} if sns_wrapped else body
    rec = MagicMock()
    rec.body = json.dumps(payload)
    rec.message_id = "msg-1"
    return rec


class TestTheWireFormat:
    def test_the_committed_producer_fixture_validates(self):
        """The real thing, as sales-be serializes it. The inline sample below is
        a convenience for the other cases; THIS is the contract."""
        event = OrderDocumentLinkEvent.model_validate(
            json.loads(FIXTURE.read_text(encoding="utf-8"))
        )
        assert event.data.order_document_number
        assert event.data.document.document_id
        # Every key store-be persists must survive the round trip, or a rename
        # upstream would silently start writing a narrower snapshot here.
        document = event.data.document.model_dump(exclude_none=True)
        assert {
            "document_id", "document_number", "document_type",
            "consecutive_number", "document_key", "issued_on",
            "status", "total_amount", "currency_code",
        } <= set(document)

    def test_the_publishers_json_validates(self):
        event = OrderDocumentLinkEvent.model_validate(PUBLISHED)
        assert event.data.order_document_number == "PM-000123"
        assert event.data.document.document_id.startswith("9f3a")
        assert event.data.document.status == 1

    def test_an_unknown_field_upstream_does_not_reject_the_message(self):
        """sales-be may add to the contract; that must not stop the queue."""
        body = json.loads(json.dumps(PUBLISHED))
        body["data"]["document"]["something_new"] = "x"
        assert OrderDocumentLinkEvent.model_validate(body).data.document.document_id

    def test_a_document_without_an_id_is_rejected(self):
        body = json.loads(json.dumps(PUBLISHED))
        del body["data"]["document"]["document_id"]
        with pytest.raises(Exception):
            OrderDocumentLinkEvent.model_validate(body)


class TestDispatch:
    @patch("app.handlers.sqs_handler.order_service.link_order_document")
    def test_a_link_event_reaches_the_order_service(self, link):
        SqsHandler(service=MagicMock())._handle(record(PUBLISHED))
        link.assert_called_once()
        org, number, document = link.call_args[0]
        assert (org, number) == ("org-1", "PM-000123")
        assert document["consecutive_number"] == "00100001010000000123"

    @patch("app.handlers.sqs_handler.order_service.link_order_document")
    def test_the_sns_envelope_is_unwrapped(self, link):
        SqsHandler(service=MagicMock())._handle(record(PUBLISHED, sns_wrapped=True))
        link.assert_called_once()

    @patch("app.handlers.sqs_handler.order_service.link_order_document")
    def test_a_branch_event_still_goes_to_branch_sync(self, link):
        service = MagicMock()
        branches = {
            "id": "1", "occurred_at": "2026-09-20T14:02:11Z",
            "_type": "OrganizationBranchesEvent", "event_type": "SAVE_BRANCHES",
            "data": {"organization_id": "org-1", "branches": []},
        }
        SqsHandler(service=service)._handle(record(branches))
        service.sync_from_hacienda.assert_called_once()
        link.assert_not_called()

    @patch("app.handlers.sqs_handler.order_service.link_order_document")
    def test_an_unknown_event_type_raises_so_it_reaches_the_dlq(self, link):
        """An unroutable message is a routing bug and the message is evidence.

        Contrast `link_order_document`, which DROPS an order it cannot find: that
        is ordinary data with nothing to investigate. This one means somebody
        subscribed the queue to the wrong topic, and a DLQ is visible where a log
        line is not. Pinned by `test_branch_sync_handler` too.
        """
        with pytest.raises(ValueError, match="Unhandled SQS event_type"):
            SqsHandler(service=MagicMock())._handle(
                record({"event_type": "SOMETHING_ELSE", "data": {}})
            )
        link.assert_not_called()


@pytest.fixture
def repo():
    with patch("app.services.order_service.OrderRepository") as factory:
        r = MagicMock()
        factory.return_value.__enter__.return_value = r
        yield r


def order(**overrides):
    stub = MagicMock()
    stub.document_number = "PM-000123"
    stub.document_id = None
    stub.document_info = None
    for k, v in overrides.items():
        setattr(stub, k, v)
    return stub


DOCUMENT = PUBLISHED["data"]["document"]


class TestLinking:
    @patch("app.services.order_service.order_to_response", lambda o: o)
    def test_it_writes_the_id_and_the_snapshot(self, repo):
        existing = order()
        repo.find_by_company_and_document.return_value = existing
        repo.save.side_effect = lambda o: o

        link_order_document("org-1", "PM-000123", DOCUMENT)

        assert existing.document_id == DOCUMENT["document_id"]
        assert existing.document_info["consecutive_number"] == "00100001010000000123"
        assert existing.document_info["status"] == 1
        repo.save.assert_called_once()

    @patch("app.services.order_service.order_to_response", lambda o: o)
    def test_only_the_agreed_fields_are_stored(self, repo):
        """A field added upstream must not silently widen the row."""
        repo.find_by_company_and_document.return_value = order()
        repo.save.side_effect = lambda o: o
        existing = repo.find_by_company_and_document.return_value

        link_order_document("org-1", "PM-000123", {**DOCUMENT, "secret": "x"})

        assert "secret" not in existing.document_info

    def test_no_such_order_is_dropped_not_raised(self, repo):
        """The order number is read off the document; a chain PO number typed by
        hand may name no order of ours. Retrying cannot make it exist."""
        repo.find_by_company_and_document.return_value = None

        assert link_order_document("org-1", "PM-000123", DOCUMENT) is None
        repo.save.assert_not_called()

    def test_a_second_document_does_not_overwrite_the_first(self, repo):
        repo.find_by_company_and_document.return_value = order(
            document_id="another-sale",
            document_info={"consecutive_number": "00100001010000000999"},
        )

        assert link_order_document("org-1", "PM-000123", DOCUMENT) is None
        repo.save.assert_not_called()

    @patch("app.services.order_service.order_to_response", lambda o: o)
    def test_relinking_the_same_document_is_idempotent(self, repo):
        """A redelivered SQS message must not be an error."""
        existing = order(document_id=DOCUMENT["document_id"], document_info={})
        repo.find_by_company_and_document.return_value = existing
        repo.save.side_effect = lambda o: o

        assert link_order_document("org-1", "PM-000123", DOCUMENT) is not None
        assert existing.document_id == DOCUMENT["document_id"]

    @patch("app.services.order_service.order_to_response", lambda o: o)
    def test_a_rejection_releases_the_order(self, repo):
        """Hacienda refused it, so nothing was billed and the cashier must be
        able to issue a corrected document."""
        existing = order(document_id=DOCUMENT["document_id"], document_info={"status": 0})
        repo.find_by_company_and_document.return_value = existing
        repo.save.side_effect = lambda o: o

        link_order_document("org-1", "PM-000123", {**DOCUMENT, "status": 3})

        assert existing.document_info["status"] == 3
        # The link is KEPT — the order records which document was refused — but
        # it stops counting as billed.
        assert existing.document_id == DOCUMENT["document_id"]
        assert is_order_billed(existing) is False

    @patch("app.services.order_service.order_to_response", lambda o: o)
    def test_a_corrected_document_may_claim_a_released_order(self, repo):
        """The whole point of releasing it. Without this the emission claim
        stands forever and the order is stuck, repairable only by hand."""
        existing = order(
            document_id="refused-doc",
            document_info={"status": 3, "consecutive_number": "…238"},
        )
        repo.find_by_company_and_document.return_value = existing
        repo.save.side_effect = lambda o: o

        assert link_order_document("org-1", "PM-000123", DOCUMENT) is not None
        assert existing.document_id == DOCUMENT["document_id"]
        assert is_order_billed(existing) is True

    def test_an_accepted_document_still_cannot_be_displaced(self, repo):
        """Releasing on rejection must not weaken the double-billing guard."""
        repo.find_by_company_and_document.return_value = order(
            document_id="accepted-doc", document_info={"status": 1},
        )

        assert link_order_document("org-1", "PM-000123", DOCUMENT) is None
        repo.save.assert_not_called()

    def test_an_in_flight_document_cannot_be_displaced_either(self, repo):
        """A claim with no verdict yet still holds the order — that is what
        stops the second factura while the first is being validated."""
        repo.find_by_company_and_document.return_value = order(
            document_id="in-flight-doc", document_info={"status": 0},
        )

        assert link_order_document("org-1", "PM-000123", DOCUMENT) is None
        repo.save.assert_not_called()

    def test_a_document_with_no_id_is_a_real_error(self, repo):
        with pytest.raises(ValueError, match="document_id"):
            link_order_document("org-1", "PM-000123", {"document_type": "01"})
