from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Path

from app.dtos.requests.branch_type_request_dto import (
    BranchTypeCreateRequestDTO,
    BranchTypeUpdateRequestDTO,
)
from app.dtos.responses.branch_type_dto import BranchTypeListResponse, BranchTypeResponse
from app.services import branch_type_service
from app.services.permission_guard import require_permission


class BranchTypesController:
    def __init__(self, app: FastAPI):
        self.register_routes(app)

    def register_routes(self, app: FastAPI):

        @app.get(
            "/api/organizations/{organization_id}/branch-types",
            response_model=BranchTypeListResponse,
            tags=["branch-types"],
            summary="Get the organization's branch-type catalog",
            description="""Every branch type configured for the organization, in display order.

Branch types replace the old hardcoded `stand`/`restaurant` enum: `code` is what gets
stored on `branches.type`, and `name`/`icon`/`color` drive how the POS labels a branch.

The response is unpaginated — this is a small selector catalog.""",
        )
        async def list_branch_types(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
        ) -> BranchTypeListResponse:
            require_permission(organization_id, x_user_id, "admin", "read", "branch-types")
            try:
                return branch_type_service.get_branch_types(organization_id, x_user_id)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/branch-types",
            response_model=BranchTypeResponse,
            status_code=201,
            tags=["branch-types"],
            summary="Create a branch type",
            description="""Add a branch type to the organization's catalog.

**Required fields:**
- `code`: lowercase slug (`[a-z0-9][a-z0-9_-]*`) — unique within the organization. Stored
  on `branches.type` and **immutable** afterwards.
- `name`: display label shown in the POS

**Optional fields:**
- `icon`: icon name from the design-system icon set (e.g. `store`, `home`)
- `color`: CSS-var color token name (e.g. `primary`, `info`)
- `sort_order`: display order in selectors (defaults to 0)
""",
        )
        async def create_branch_type(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
            body: BranchTypeCreateRequestDTO,
        ) -> BranchTypeResponse:
            require_permission(organization_id, x_user_id, "admin", "create", "branch-types")
            try:
                return branch_type_service.create_branch_type(organization_id, x_user_id, body)
            except HTTPException:
                raise
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.put(
            "/api/organizations/{organization_id}/branch-types/{branch_type_id}",
            response_model=BranchTypeResponse,
            tags=["branch-types"],
            summary="Update a branch type",
            description="""Update a branch type's presentation fields (`name`, `icon`, `color`, `sort_order`).

`code` cannot be changed: branches reference it by value, so renaming it would orphan
every branch already using it. Delete the type (only possible while unused) and create
a new one instead.""",
        )
        async def update_branch_type(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            branch_type_id: Annotated[str, Path(description="Branch type identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
            body: BranchTypeUpdateRequestDTO,
        ) -> BranchTypeResponse:
            require_permission(organization_id, x_user_id, "admin", "update", "branch-types")
            try:
                result = branch_type_service.update_branch_type(
                    organization_id, x_user_id, branch_type_id, body
                )
                if not result:
                    raise HTTPException(status_code=404, detail="Branch type not found")
                return result
            except HTTPException:
                raise
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.delete(
            "/api/organizations/{organization_id}/branch-types/{branch_type_id}",
            status_code=204,
            tags=["branch-types"],
            summary="Delete a branch type",
            description="""Remove a branch type from the catalog.

Refused with 409 while any branch still uses the type's code — reassign those branches
first.""",
        )
        async def delete_branch_type(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            branch_type_id: Annotated[str, Path(description="Branch type identifier")],
            x_user_id: Annotated[str, Header(description="User identifier from header")],
        ):
            require_permission(organization_id, x_user_id, "admin", "delete", "branch-types")
            try:
                success = branch_type_service.delete_branch_type(
                    organization_id, x_user_id, branch_type_id
                )
                if not success:
                    raise HTTPException(status_code=404, detail="Branch type not found")
                return None
            except HTTPException:
                raise
            except ValueError as e:
                # Still referenced by branches — a conflict, not a malformed request.
                raise HTTPException(status_code=409, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
