"""Every branch-type management operation requires its own org-scoped grant."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.controllers.branch_types_controller import BranchTypesController


@pytest.fixture
def client():
    app = FastAPI()
    BranchTypesController(app)
    return TestClient(app)


@pytest.mark.parametrize("method,suffix,body,action", [
    ("get", "", None, "read"),
    ("post", "", {"code": "shop", "name": "Shop"}, "create"),
    ("put", "/type-id", {"name": "Shop"}, "update"),
    ("delete", "/type-id", None, "delete"),
])
def test_denies_without_action_grant(client, method, suffix, body, action):
    with patch("app.controllers.branch_types_controller.require_permission") as guard, patch(
        "app.controllers.branch_types_controller.branch_type_service"
    ) as service:
        guard.side_effect = HTTPException(status_code=403, detail="Permission denied")
        kwargs = {"headers": {"x-user-id": "user-123"}}
        if body is not None:
            kwargs["json"] = body
        response = getattr(client, method)("/api/organizations/org-123/branch-types" + suffix, **kwargs)
        assert response.status_code == 403
        guard.assert_called_once_with("org-123", "user-123", "admin", action, "branch-types")
        assert not service.mock_calls


def test_authorized_empty_catalog_stays_empty(client):
    with patch("app.controllers.branch_types_controller.require_permission"), patch(
        "app.controllers.branch_types_controller.branch_type_service.get_branch_types",
        return_value={"data": []},
    ):
        response = client.get("/api/organizations/org-123/branch-types", headers={"x-user-id": "user-123"})
        assert response.status_code == 200
        assert response.json() == {"data": []}
