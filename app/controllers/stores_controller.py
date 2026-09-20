from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Body, FastAPI, HTTPException, Path, Query

from app.dtos.files import ExcelDTO
from app.dtos.requests.status_request_dto import StatusRequestDTO
from app.dtos.requests.store_request_dto import StoreRequestDTO
from app.dtos.responses.store_dto import (
    StoreListResponse,
    StoreResponse,
    StoreUploadResponse,
)
from app.services import store_service


class StoresController:
    def __init__(self, app: FastAPI):
        self.register_routes(app)

    def register_routes(self, app: FastAPI):

        @app.get(
            "/api/organizations/{organization_id}/clients/{client_id}/stores",
            response_model=StoreListResponse,
            tags=["stores"],
            summary="Get all stores for a client",
            description="""Get a paginated list of stores with optional search filters.

**Search filters**
- `storeCode`: Store code
- `storeName`: Store name (supports wildcards)
- `chain`: Chain name (supports wildcards)
- `slotId`: Slot ID

**Sorting**
- `orderBy>field` (Ascending)
- `orderBy<field` (Descending)

**Example:** `storeName:*test*,orderBy>storeCode`
""",
        )
        async def list_stores(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            client_id: Annotated[str, Path(description="Client UUID")],
            search: Optional[str] = Query(
                None,
                description=(
                    "Search filter string. Syntax: field:value,field2:value2. "
                    "Supports operators: : (equal), ! (not equal), > (greater), < (less), ~ (like). "
                    "Example: storeName:*Test*,orderBy>storeCode"
                ),
            ),
            page: int = Query(1, ge=1, description="Page number (1-indexed)"),
            page_size: int = Query(12, ge=1, le=100, description="Items per page"),
        ):
            try:
                return store_service.get_stores(
                    organization_id, client_id, page, page_size, search
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get(
            "/api/organizations/{organization_id}/clients/{client_id}/stores/{store_id}",
            response_model=StoreResponse,
            tags=["stores"],
            summary="Get a specific store by ID",
        )
        async def get_store(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            client_id: Annotated[str, Path(description="Client UUID")],
            store_id: Annotated[str, Path(description="Store UUID")],
        ):
            try:
                import uuid as uuid_mod

                result = store_service.get_store(organization_id, uuid_mod.UUID(store_id))
                if not result:
                    raise HTTPException(status_code=404, detail="Store not found")
                return result
            except HTTPException:
                raise
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid store ID format")
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/clients/{client_id}/stores/upload",
            response_model=StoreUploadResponse,
            tags=["stores"],
            summary="Upload stores from an Excel file",
            description="Upload an Excel file with columns: Codigo, Nombre, SLOT ID, Cadena",
        )
        async def upload_stores(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            client_id: Annotated[str, Path(description="Client UUID")],
            body: ExcelDTO = Body(...),
        ):
            try:
                count = store_service.upload_stores_excel(
                    organization_id, client_id, body
                )
                return {"message": f"Successfully uploaded {count} stores", "count": count}
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/clients/{client_id}/stores",
            response_model=StoreResponse,
            status_code=201,
            tags=["stores"],
            summary="Create a new store",
        )
        async def create_store(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            client_id: Annotated[str, Path(description="Client UUID")],
            body: StoreRequestDTO,
        ):
            try:
                return store_service.create_store(organization_id, client_id, body)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.put(
            "/api/organizations/{organization_id}/clients/{client_id}/stores/{store_id}",
            response_model=StoreResponse,
            tags=["stores"],
            summary="Update an existing store",
        )
        async def update_store(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            client_id: Annotated[str, Path(description="Client UUID")],
            store_id: Annotated[str, Path(description="Store UUID")],
            body: StoreRequestDTO,
        ):
            try:
                result = store_service.update_store(organization_id, store_id, body)
                if not result:
                    raise HTTPException(status_code=404, detail="Store not found")
                return result
            except HTTPException:
                raise
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid store ID format")
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.patch(
            "/api/organizations/{organization_id}/clients/{client_id}/stores/{store_id}",
            response_model=StoreResponse,
            tags=["stores"],
            summary="Update store status",
        )
        async def update_store_status(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            client_id: Annotated[str, Path(description="Client UUID")],
            store_id: Annotated[str, Path(description="Store UUID")],
            body: StatusRequestDTO = Body(...),
        ):
            try:
                result = store_service.update_store_status(organization_id, store_id, body.status)
                if not result:
                    raise HTTPException(status_code=404, detail="Store not found")
                return result
            except HTTPException:
                raise
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid store ID format")
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
