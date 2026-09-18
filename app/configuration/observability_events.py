"""Best-effort backend request audit and critical-error SNS publisher.

The browser never reports platform failures. Every backend HTTP request emits one
AUDIT_REQUEST_COMPLETED envelope, and 5xx/uncaught failures emit a second
BACKEND_ERROR_OCCURRED envelope. SNS subscription filters route each event to
its own SQS queue in support-be.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import json
import logging
import os
import re
import traceback
from typing import Any
from uuid import uuid4

import boto3
from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)
_TOPIC_ARNS: dict[str, str | None] = {}
_ORGANIZATION_PATH = re.compile(r"/organizations/([^/?]+)")


def _stage() -> str:
    raw = os.getenv("ENVIRONMENT", os.getenv("STAGE", "dev")).lower()
    return {"development": "dev", "staging": "stag", "production": "prod"}.get(raw, raw)


def _topic(kind: str) -> str | None:
    if kind in _TOPIC_ARNS:
        return _TOPIC_ARNS[kind]
    env_name = "AUDIT_EVENTS_TOPIC_ARN" if kind == "audit-records" else "ERROR_EVENTS_TOPIC_ARN"
    topic = os.getenv(env_name)
    if not topic:
        path = f"/tsuru/{_stage()}/support-api/events/{kind}/topic-arn"
        try:
            topic = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1")).get_parameter(
                Name=path, WithDecryption=False
            )["Parameter"]["Value"]
        except Exception as exc:
            logger.warning("Observability topic unavailable: %s (%s)", path, exc)
            topic = None
    _TOPIC_ARNS[kind] = topic
    return topic


def _jwt_subject(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        payload = authorization.split(" ", 1)[1].split(".")[1]
        payload += "=" * (-len(payload) % 4)
        value = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return str(value.get("sub")) if value.get("sub") else None
    except Exception:
        return None


def _identity(request: Request) -> tuple[str | None, str | None]:
    user_id = request.headers.get("x-user-id") or _jwt_subject(request.headers.get("authorization"))
    organization_id = request.headers.get("x-organization-id") or request.headers.get("x-org-id")
    if not organization_id:
        match = _ORGANIZATION_PATH.search(request.url.path)
        organization_id = match.group(1) if match else None
    return user_id, organization_id


def _format_exception(error: BaseException) -> str:
    """The traceback text, on every runtime we deploy to.

    `traceback.format_exception(exc)` — one argument — is Python 3.10+. store-be
    still runs 3.9, where it raises `TypeError: missing 2 required positional
    arguments`, *inside the error reporter*, in a `finally` block. An exception
    raised there REPLACES the exception being handled, so the real application
    error never reached an exception handler: the caller got a bare 500 with no
    error DTO, and the incident describing it was never published either.

    The three-argument form is correct on 3.9 through 3.14, so this needs no
    version check.
    """
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def _publish(kind: str, event_type: str, type_name: str, data: dict[str, Any],
             *, event_id: str, occurred_at: datetime) -> None:
    topic = _topic(kind)
    if not topic:
        return
    envelope = {
        "id": event_id,
        "date": occurred_at.isoformat(),
        "eventType": event_type,
        "_type": type_name,
        "data": data,
    }
    try:
        boto3.client("sns", region_name=os.getenv("AWS_REGION", "us-east-1")).publish(
            TopicArn=topic,
            Message=json.dumps(envelope, separators=(",", ":"), default=str),
            Subject=event_type,
            MessageAttributes={
                "eventType": {"DataType": "String", "StringValue": event_type}
            },
        )
    except Exception:
        logger.exception("Failed to publish %s observability event", event_type)


async def _publish_async(*args, **kwargs) -> None:
    await asyncio.to_thread(_publish, *args, **kwargs)


def install_observability_events(app: FastAPI, service_name: str) -> None:
    @app.middleware("http")
    async def publish_request_events(request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path == "/health":
            return await call_next(request)

        started_at = datetime.now(timezone.utc)
        started = asyncio.get_running_loop().time()
        request_id = request.headers.get("x-request-id") or str(uuid4())
        user_id, organization_id = _identity(request)
        route = request.url.path
        status_code = 500
        caught: Exception | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            route = getattr(request.scope.get("route"), "path", route)
            return response
        except Exception as exc:
            caught = exc
            raise
        finally:
            # Reporting is best-effort, always. `_publish` already swallows its
            # own failures, but everything AROUND it — building the payload,
            # reading request state, formatting a traceback — runs in a `finally`,
            # where a raise replaces the exception being handled and turns a
            # diagnosable application error into a bare 500. That is exactly what
            # a Python 3.9 `format_exception` call did here. Nothing in this block
            # is allowed to change the outcome of the request.
            try:
                duration_ms = round((asyncio.get_running_loop().time() - started) * 1000)
                method = request.method.upper()
                request_type = f"{method} {route}"[:160]
                common = {
                    "service": service_name,
                    "requestType": request_type,
                    "httpMethod": method,
                    "route": route[:500],
                    "statusCode": status_code,
                    "userId": user_id,
                    "organizationId": organization_id,
                    "requestId": request_id,
                }
                await _publish_async(
                    "audit-records",
                    "AUDIT_REQUEST_COMPLETED",
                    "AuditRequestCompletedEvent",
                    {**common, "durationMs": duration_ms},
                    event_id=str(uuid4()),
                    occurred_at=started_at,
                )
                if status_code >= 500 or caught is not None:
                    internal_error = caught or getattr(request.state, "observability_exception", None)
                    code = str(
                        getattr(request.state, "observability_error_code", None)
                        or getattr(internal_error, "code", None)
                        or f"COMMON_{status_code}"
                    )
                    await _publish_async(
                        "backend-errors",
                        "BACKEND_ERROR_OCCURRED",
                        "BackendErrorOccurredEvent",
                        {
                            **common,
                            "errorCode": code,
                            "errorName": internal_error.__class__.__name__ if internal_error else "BackendHttpError",
                            # Public response messages are catalog codes. Internal detail
                            # stays only in this protected support event.
                            "errorMessage": (str(internal_error) if internal_error else code)[:2000],
                            "stackTrace": (
                                _format_exception(internal_error)[:8000]
                                if internal_error is not None else None
                            ),
                        },
                        event_id=str(uuid4()),
                        occurred_at=started_at,
                    )
            except Exception:
                logger.exception("Observability reporting failed for %s", route)
