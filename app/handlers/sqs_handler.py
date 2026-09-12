"""SQS branch discovery consumer with SNS unwrapping and partial batch retries."""

from __future__ import annotations

import json
import logging
from typing import Optional

from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.data_classes import SQSRecord

from app.dtos.requests.branch_sync_dto import OrganizationBranchesEvent
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
                "Branch sync record %s failed", record.message_id, exc_info=True,
            )
            raise

    def _handle(self, record: SQSRecord):
        body = json.loads(record.body)
        if isinstance(body, dict) and "Message" in body:
            body = json.loads(body["Message"])
        event = OrganizationBranchesEvent.model_validate(body)
        self._service.sync_from_hacienda(event.data.organization_id, event.data.branches)
