from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.configuration import observability_events


def test_every_request_is_audited_and_only_5xx_emits_error(monkeypatch):
    captured = []

    async def capture(*args, **kwargs):
        captured.append((args, kwargs))

    monkeypatch.setattr(observability_events, "_publish_async", capture)
    app = FastAPI()
    observability_events.install_observability_events(app, "store-api")

    @app.get("/health")
    def health():
        return JSONResponse({"status": "unhealthy"}, status_code=500)

    @app.get("/api/organizations/org-1/products")
    def products():
        return JSONResponse({"message": "COMMON_500"}, status_code=500)

    @app.get("/bad-request")
    def bad_request():
        return JSONResponse({"message": "COMMON_422"}, status_code=422)

    @app.get("/crash")
    def crash():
        raise RuntimeError("critical service failure")

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/health").status_code == 500
    assert client.get("/bad-request").status_code == 422
    assert client.get("/api/organizations/org-1/products", headers={"x-user-id": "user-1"}).status_code == 500
    assert client.get("/crash").status_code == 500

    audits = [item for item in captured if item[0][1] == "AUDIT_REQUEST_COMPLETED"]
    errors = [item for item in captured if item[0][1] == "BACKEND_ERROR_OCCURRED"]
    assert len(audits) == 3
    assert len(errors) == 2
    product = next(item for item in audits if item[0][3]["route"].endswith("/products"))
    assert product[0][3]["organizationId"] == "org-1"
    assert product[0][3]["userId"] == "user-1"
    assert product[0][3]["requestType"] == "GET /api/organizations/org-1/products"
    crash = next(item for item in errors if item[0][3]["route"] == "/crash")
    assert crash[0][3]["errorName"] == "RuntimeError"
    assert "critical service failure" in crash[0][3]["errorMessage"]
