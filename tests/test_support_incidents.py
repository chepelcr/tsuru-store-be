from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.configuration import support_incidents


def test_real_5xx_and_uncaught_errors_are_forwarded_but_not_health_or_4xx(monkeypatch):
    captured = []
    monkeypatch.setattr(support_incidents, "_forward", captured.append)
    app = FastAPI()
    support_incidents.install_support_incident_reporting(app, "store-api")

    @app.get("/health")
    def health():
        return JSONResponse({"status": "unhealthy"}, status_code=500)

    @app.get("/api/organizations/00000000-0000-0000-0000-000000000001/products")
    def products():
        return JSONResponse({"error": "Database failure"}, status_code=500)

    @app.get("/bad-request")
    def bad_request():
        return JSONResponse({"error": "Invalid input"}, status_code=422)

    @app.get("/crash")
    def crash():
        raise RuntimeError("critical service failure")

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/health").status_code == 500
    assert client.get("/bad-request").status_code == 422
    assert client.get("/api/organizations/00000000-0000-0000-0000-000000000001/products").status_code == 500
    assert client.get("/crash").status_code == 500

    assert len(captured) == 2
    assert captured[0]["source"] == "backend-http"
    assert captured[0]["module"] == "products"
    assert captured[0]["status_code"] == 500
    assert captured[1]["source"] == "backend-exception"
    assert captured[1]["error_name"] == "RuntimeError"
    assert "critical service failure" in captured[1]["error_message"]
