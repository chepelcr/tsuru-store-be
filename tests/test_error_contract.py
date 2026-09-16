from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.error_contract import StoreErrorCodes, StoreException, install_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/domain")
    async def domain():
        raise StoreException(StoreErrorCodes.ORGANIZATION_NOT_FOUND, status_code=404)

    @app.get("/legacy")
    async def legacy():
        raise HTTPException(status_code=409, detail="sensitive internal state")

    @app.get("/unexpected")
    async def unexpected():
        raise RuntimeError("database password must never reach the wire")

    return TestClient(app, raise_server_exceptions=False)


def test_enum_exception_uses_catalog_code_as_message():
    response = _client().get("/domain")
    assert response.status_code == 404
    assert response.json()["message"] == "ORGANIZATION_NOT_FOUND"
    assert response.json()["service"] == "store-api"


def test_http_exception_is_normalized_without_leaking_detail():
    response = _client().get("/legacy")
    assert response.status_code == 409
    assert response.json()["message"] == "COMMON_409"
    assert "sensitive" not in response.text


def test_unexpected_exception_is_normalized_without_leaking_detail():
    response = _client().get("/unexpected")
    assert response.status_code == 500
    assert response.json()["message"] == "COMMON_500"
    assert "password" not in response.text
