"""Common enum-backed HTTP exception contract for the store service."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from http import HTTPStatus
from typing import Any, Dict, List, Optional, Protocol, Union, runtime_checkable

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


@runtime_checkable
class ErrorDefinition(Protocol):
    @property
    def code(self) -> str: ...

    @property
    def message(self) -> str: ...


class StoreErrorCodes(Enum):
    BAD_REQUEST = ("COMMON_400", "La solicitud no es válida.")
    UNAUTHORIZED = ("COMMON_401", "Autenticación requerida.")
    FORBIDDEN = ("COMMON_403", "No tiene permisos para esta operación.")
    NOT_FOUND = ("COMMON_404", "El recurso solicitado no existe.")
    CONFLICT = ("COMMON_409", "La solicitud entra en conflicto con el estado actual.")
    VALIDATION_ERROR = ("COMMON_422", "La solicitud contiene datos inválidos.")
    TOO_MANY_REQUESTS = ("COMMON_429", "Se excedió el límite de solicitudes.")
    INTERNAL_ERROR = ("COMMON_500", "Ocurrió un error interno.")
    BAD_GATEWAY = ("COMMON_502", "Un servicio dependiente devolvió un error.")
    SERVICE_UNAVAILABLE = ("COMMON_503", "El servicio no está disponible.")
    ORGANIZATION_NOT_FOUND = ("ORGANIZATION_NOT_FOUND", "No se encontró la organización.")
    API_NOT_AVAILABLE = ("API_NOT_AVAILABLE", "Un servicio dependiente no está disponible.")
    EXCEL_PARSE_ERROR = ("EXCEL_PARSE_ERROR", "No se pudo procesar el archivo de Excel.")

    @property
    def code(self) -> str:
        return self.value[0]

    @property
    def message(self) -> str:
        return self.value[1]


_BY_STATUS = {
    400: StoreErrorCodes.BAD_REQUEST,
    401: StoreErrorCodes.UNAUTHORIZED,
    403: StoreErrorCodes.FORBIDDEN,
    404: StoreErrorCodes.NOT_FOUND,
    409: StoreErrorCodes.CONFLICT,
    422: StoreErrorCodes.VALIDATION_ERROR,
    429: StoreErrorCodes.TOO_MANY_REQUESTS,
    500: StoreErrorCodes.INTERNAL_ERROR,
    502: StoreErrorCodes.BAD_GATEWAY,
    503: StoreErrorCodes.SERVICE_UNAVAILABLE,
}


class ErrorResponseDTO(BaseModel):
    timestamp: str
    status: int
    error: str
    message: str
    service: str
    path: str
    details: Optional[List[Dict[str, Any]]] = None


class StoreException(Exception):
    """Domain exception whose code and catalog copy originate in an enum."""

    def __init__(
        self,
        error: ErrorDefinition,
        *,
        status_code: int = 500,
        message: str | None = None,
    ) -> None:
        self.code = error.code
        self.catalog_message = error.message
        self.message = message or error.message
        self.status_code = status_code
        super().__init__(self.message)


def code_for_status(status: int) -> str:
    return _BY_STATUS.get(status, StoreErrorCodes.INTERNAL_ERROR).code


def error_response(
    request: Request,
    *,
    status: int,
    code: str | None = None,
    details: Optional[List[Dict[str, Any]]] = None,
) -> JSONResponse:
    reason = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "Error"
    payload = ErrorResponseDTO(
        timestamp=datetime.now(timezone.utc).isoformat(),
        status=status,
        error=reason,
        message=code or code_for_status(status),
        service="store-api",
        path=request.url.path,
        details=details,
    )
    return JSONResponse(status_code=status, content=payload.model_dump(exclude_none=True))


def install_error_handlers(app: Any) -> None:
    @app.exception_handler(StoreException)
    async def domain_error(request: Request, exc: StoreException):
        logger.warning("%s %s: %s", exc.status_code, exc.code, exc.message)
        return error_response(request, status=exc.status_code, code=exc.code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [
            {"path": ".".join(map(str, item["loc"])), "type": item["type"]}
            for item in exc.errors()
        ]
        return error_response(request, status=422, details=details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        logger.warning("HTTP %s on %s: %s", exc.status_code, request.url.path, exc.detail)
        return error_response(request, status=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s", request.url.path, exc_info=exc)
        return error_response(request, status=500)


#: OpenAPI declaration of the error envelope, applied to every route via
#: `FastAPI(responses=...)` so consumers get a typed DTO for failures instead of
#: FastAPI's bare `{"detail": ...}` default (which no longer matches what the
#: handlers above actually return).
ERROR_RESPONSES: Dict[Union[int, str], Dict[str, Any]] = {
    status: {"model": ErrorResponseDTO, "description": error.message}
    for status, error in _BY_STATUS.items()
}
