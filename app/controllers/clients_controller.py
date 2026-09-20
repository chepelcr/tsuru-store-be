from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Body, FastAPI, HTTPException, Path, Query

from app.dtos.requests.client_request_dto import ClientRequestDTO
from app.dtos.requests.client_status_request_dto import ClientStatusRequestDTO
from app.dtos.responses.client_dto import ClientListResponse, ClientResponse
from app.services import client_service


class ClientsController:
    def __init__(self, app: FastAPI):
        self.register_routes(app)

    def register_routes(self, app: FastAPI):

        @app.get(
            "/api/organizations/{organization_id}/clients",
            response_model=ClientListResponse,
            tags=["clients"],
            summary="Get all clients for an organization",
            description="""Get a paginated list of clients with optional search filters.

**Search filters**
- `clientName`: Client name (supports wildcards)
- `clientGln`: Client GLN code
- `status`: Client status (0=Pending, 1=Active, 2=Inactive, 3=Deleted)
- `nationality`: Client nationality code (e.g., CR, US)
- `idNumber`: Identification number

**Sorting**
- `orderBy>field` (Ascending)
- `orderBy<field` (Descending)
- Sortable fields: `clientName`, `clientGln`, `status`, `nationality`, `createdOn`, `updatedOn`

**Examples:**
- Search by name: `clientName:*corp*`
- Search pending clients: `status:0`
- Search by nationality and ID: `nationality:CR,idNumber:123456789`
- Combined: `status:0,nationality:CR,orderBy>clientName`
""",
        )
        async def list_clients(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            search: Optional[str] = Query(
                None,
                description=(
                    "Search filter string. Syntax: field:value,field2:value2. "
                    "Supports operators: : (equal), ! (not equal), > (greater), < (less), ~ (like). "
                    "Example: clientName:*Test*,orderBy>clientName"
                ),
            ),
            page: int = Query(1, ge=1, description="Page number (1-indexed)"),
            page_size: int = Query(12, ge=1, le=100, description="Items per page"),
        ):
            try:
                return client_service.get_clients(
                    organization_id, page, page_size, search
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get(
            "/api/organizations/{organization_id}/clients/{client_id}",
            response_model=ClientResponse,
            tags=["clients"],
            summary="Get a specific client by ID",
        )
        async def get_client(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            client_id: Annotated[str, Path(description="Client UUID")],
        ):
            try:
                import uuid as uuid_mod

                result = client_service.get_client(organization_id, uuid_mod.UUID(client_id))
                if not result:
                    raise HTTPException(status_code=404, detail="Client not found")
                return result
            except HTTPException:
                raise
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid client ID format")
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/clients",
            response_model=ClientResponse,
            status_code=201,
            tags=["clients"],
            summary="Create a new client or reactivate deleted one",
            description="""Create a new client. If a deleted client exists with the same company_id, client_gln, and nationality, it will be reactivated and updated with the new information.""",
        )
        async def create_client(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            body: ClientRequestDTO,
        ):
            try:
                return client_service.create_client(organization_id, body)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.put(
            "/api/organizations/{organization_id}/clients/{client_id}",
            response_model=ClientResponse,
            tags=["clients"],
            summary="Update an existing client",
            description="""Update an existing client. Cannot update deleted clients (status=3). Use POST to reactivate deleted clients.""",
        )
        async def update_client(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            client_id: Annotated[str, Path(description="Client UUID")],
            body: ClientRequestDTO,
        ):
            try:
                result = client_service.update_client(organization_id, client_id, body)
                if not result:
                    raise HTTPException(status_code=404, detail="Client not found")
                return result
            except HTTPException:
                raise
            except ValueError as e:
                # `str(e)`, not a fixed string. This said "Invalid client ID
                # format" for every ValueError, including the service's own
                # "Cannot update deleted client. Use POST to reactivate." — so
                # the one message that tells the caller what to do next was
                # replaced by one that is simply untrue.
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.patch(
            "/api/organizations/{organization_id}/clients/{client_id}/status",
            response_model=ClientResponse,
            tags=["clients"],
            summary="Update client status",
            description="""Update client status. Cannot update deleted clients (status=3). Use POST to reactivate deleted clients.

**Status codes:**
- `1`: Active
- `2`: Inactive
- `3`: Deleted

Moved here from `PATCH /clients/{client_id}`, which every other resource in this
service reserves for nothing and this one used for status. The POS sent its
customer-edit payload to that path expecting a field update and got a 422 for a
missing `status` on every save, while its status mutation pointed at
`/clients/{client_id}/status` — the convention every other controller follows —
and hit no route at all. Both were off by exactly one path.
""",
        )
        async def update_client_status(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            client_id: Annotated[str, Path(description="Client UUID")],
            body: ClientStatusRequestDTO = Body(...),
        ):
            try:
                result = client_service.update_client_status(organization_id, client_id, body.status)
                if not result:
                    raise HTTPException(status_code=404, detail="Client not found")
                return result
            except HTTPException:
                raise
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
