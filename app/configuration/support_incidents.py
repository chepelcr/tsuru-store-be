"""Best-effort server-side incident forwarding for real 5xx responses.

Set SUPPORT_INCIDENTS_URL to the platform public backend-ingest URL and
SUPPORT_INGEST_TOKEN to the same private value configured on management-be.
No health requests or expected 4xx responses are reported.
"""

import asyncio
import json
import logging
import os
import re
import urllib.request

from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)
_UUID_IN_ORG_PATH = re.compile(r"/organizations/([0-9a-fA-F-]{36})(?:/|$)")


def _module_from_path(path: str, service_name: str) -> str:
    segments = [part for part in path.split("/") if part and part != "api"]
    if "organizations" in segments:
        index = segments.index("organizations")
        if len(segments) > index + 2:
            return segments[index + 2][:80]
    return (segments[0] if segments else service_name)[:80]


def _forward(payload: dict) -> None:
    url = os.getenv("SUPPORT_INCIDENTS_URL", "")
    token = os.getenv("SUPPORT_INGEST_TOKEN", "")
    if not url or not token:
        return
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"content-type": "application/json", "x-support-ingest-token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            response.read()
    except Exception:
        logger.warning("Backend incident forwarding failed", exc_info=True)


def install_support_incident_reporting(app: FastAPI, service_name: str) -> None:
    @app.middleware("http")
    async def report_real_failures(request: Request, call_next):
        path = request.url.path
        if path == "/health":
            return await call_next(request)
        status = None
        error_name = None
        message = None
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception as error:
            status = 500
            error_name = type(error).__name__
            message = str(error)[:1000]
            raise
        finally:
            if status is not None and status >= 500:
                match = _UUID_IN_ORG_PATH.search(path)
                payload = {
                    "service": service_name[:80],
                    "source": "backend-exception" if error_name else "backend-http",
                    "status_code": min(status, 599), "module": _module_from_path(path, service_name),
                    "route": path[:250],
                    "error_message": message or f"{request.method} {path} returned HTTP {status}",
                }
                if match:
                    payload["organization_id"] = match.group(1)
                if error_name:
                    payload["error_name"] = error_name
                await asyncio.to_thread(_forward, payload)
