"""SQS consumer with SNS unwrapping, event dispatch and partial batch retries.

Two events arrive on two queues and both land here, because a Lambda's SQS event
sources all funnel into one handler:

    SAVE_BRANCHES        branches discovered from Hacienda -> BranchSyncService
    LINK_ORDER_DOCUMENT  which document billed an order    -> order_service

Dispatch is on `event_type`, not on which queue delivered the message. The
handler used to validate every record as an `OrganizationBranchesEvent`, which
was fine while there was one producer and would have turned the second one into
a validation error on every message.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.data_classes import SQSRecord

from app.dtos.requests.branch_sync_dto import OrganizationBranchesEvent
from app.dtos.requests.order_document_link_dto import OrderDocumentLinkEvent
from app.services import order_service
from app.services.branch_sync_service import BranchSyncService

logger = logging.getLogger(__name__)


class SqsHandler:
    def __init__(self, service: Optional[BranchSyncService] = None):
        self._service = service or BranchSyncService()

    def handle(self, event, context):
        # Return failed item ids even if the entire batch fails; Lambda must not
        # accidentally acknowledge a malformed event or hide it in a 200 envelope.
        # No `logger=` kwarg: it does not exist on the powertools release pip
        # resolves for this image's python 3.9, and passing it raised
        # TypeError on every invocation. Record failures are logged in
        # _process_record instead, which works on any version and names the
        # message id.
        processor = BatchProcessor(
            event_type=EventType.SQS,
            raise_on_entire_batch_failure=False,
        )
        return process_partial_response(
            event=event,
            record_handler=self._process_record,
            processor=processor,
            context=context,
        )

    def _process_record(self, record: SQSRecord):
        try:
            self._handle(record)
        except Exception:
            logger.error(
                "SQS record %s failed", record.message_id, exc_info=True,
            )
            raise

    def _handle(self, record: SQSRecord):
        body = json.loads(record.body)
        if isinstance(body, dict) and "Message" in body:
            body = json.loads(body["Message"])

        event_type = body.get("event_type") if isinstance(body, dict) else None

        if event_type == "SAVE_BRANCHES":
            event = OrganizationBranchesEvent.model_validate(body)
            self._service.sync_from_hacienda(
                event.data.organization_id, event.data.branches
            )
            return

        if event_type == "LINK_ORDER_DOCUMENT":
            event = OrderDocumentLinkEvent.model_validate(body)
            # `link_order_document` returns None — and does not raise — when
            # there is no order to link or one is already linked to a different
            # document. Both are ordinary outcomes, and raising on a queue means
            # retrying something that cannot get better.
            order_service.link_order_document(
                event.data.organization_id,
                event.data.order_document_number,
                event.data.document.model_dump(exclude_none=True),
            )
            return

        # An unroutable message RAISES, so it is reported as a batch item failure
        # and ends up in the DLQ. That is deliberate and predates this handler: a
        # DLQ is visible and replayable, whereas a log line about a dropped
        # message is neither.
        #
        # Not to be confused with the drops inside `link_order_document`. An
        # unknown `event_type` is a routing bug — somebody subscribed this queue
        # to the wrong topic — and the message is evidence. A LINK_ORDER_DOCUMENT
        # naming an order we do not have is ordinary data, not a defect, and
        # there is nothing to investigate or replay.
        raise ValueError(
            f"Unhandled SQS event_type={event_type!r} on message {record.message_id}"
        )
