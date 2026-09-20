from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import Body, FastAPI, Header, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from app.models.client_asset import ClientAsset
from app.models.verticals import Appointment, ProductLot
from app.services.lot_service import expiry_warning, sellable_lots
from app.services.verticals_service import VerticalsRepository


# ─── Response shapes ────────────────────────────────────────────────────────

class LotResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lot_id: str
    product_id: str
    lot_code: str
    expires_on: Optional[str] = None
    quantity: float = 0
    #: Days to expiry when inside the warning window; null when comfortably in
    #: date. 0 means "expires today" — a warning, not the absence of one.
    expires_in_days: Optional[int] = None


class AssetResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    asset_id: str
    client_id: str
    identifier: str
    kind: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    notes: Optional[str] = None


class AssetCreateDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    identifier: str = Field(..., min_length=1, max_length=50)
    kind: Optional[str] = Field(None, max_length=50)
    brand: Optional[str] = Field(None, max_length=100)
    model: Optional[str] = Field(None, max_length=100)
    year: Optional[int] = Field(None, ge=1900, le=2200)
    notes: Optional[str] = Field(None, max_length=500)


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    appointment_id: str
    branch_id: Optional[str] = None
    client_id: Optional[str] = None
    staff_user_id: Optional[str] = None
    service_product_id: Optional[str] = None
    asset_id: Optional[str] = None
    starts_at: str
    duration_minutes: int
    appointment_status: str
    notes: Optional[str] = None
    converted_document_id: Optional[str] = None


class AppointmentCreateDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    client_id: Optional[str] = None
    staff_user_id: Optional[str] = None
    service_product_id: Optional[str] = None
    #: Taller only: which vehicle/equipment is coming in.
    asset_id: Optional[str] = None
    starts_at: datetime
    duration_minutes: int = Field(default=30, gt=0)
    notes: Optional[str] = Field(None, max_length=500)


class AppointmentUpdateDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    starts_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(None, gt=0)
    staff_user_id: Optional[str] = None
    appointment_status: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = Field(None, max_length=500)
    converted_document_id: Optional[str] = Field(None, max_length=255)


class ListWrapper(BaseModel):
    data: list


class VerticalsController:
    """Lots, assets and appointments (TSR-159 / 162 / 163)."""

    def __init__(self, app: FastAPI):
        self.register_routes(app)

    def register_routes(self, app: FastAPI):
        org = "/api/organizations/{organization_id}"

        # ── Farmacia: lots ───────────────────────────────────────────────
        @app.get(
            f"{org}/products/{{product_id}}/lots",
            response_model=LotListResponse,
            tags=["verticals"],
            summary="Sellable lots for a product, in FEFO order",
            description="""**First Expiry, First Out** — not FIFO. For anything with a shelf life
the date that matters is when it goes bad, not when it arrived.

Expired and depleted lots are excluded, so the first entry is what the till
should default to. `expires_in_days` is present only inside the warning window;
**0 means expires today**, which is a warning rather than the absence of one.""",
        )
        async def list_lots(
            organization_id: Annotated[str, Path()],
            product_id: Annotated[str, Path()],
            x_user_id: Annotated[str, Header()],
        ):
            with VerticalsRepository() as repo:
                lots = sellable_lots(repo.lots_for_product(organization_id, product_id))
                return {
                    "data": [
                        LotResponse(
                            lot_id=str(l.lot_id),
                            product_id=l.product_id,
                            lot_code=l.lot_code,
                            expires_on=str(l.expires_on) if l.expires_on else None,
                            quantity=float(l.quantity or 0),
                            expires_in_days=expiry_warning(l),
                        )
                        for l in lots
                    ]
                }

        # ── Taller: client assets ────────────────────────────────────────
        @app.get(
            f"{org}/clients/{{client_id}}/assets",
            response_model=AssetListResponse,
            tags=["verticals"],
            summary="A client's assets (vehicle / equipment)",
            description="""Scoped to the client, exactly like departments and stores — which is
what makes per-asset history possible: "what did we do to this car last time"
only exists if the asset outlives the visit.""",
        )
        async def list_assets(
            organization_id: Annotated[str, Path()],
            client_id: Annotated[str, Path()],
            x_user_id: Annotated[str, Header()],
        ):
            with VerticalsRepository() as repo:
                assets = repo.assets_for_client(organization_id, uuid.UUID(client_id))
                return {
                    "data": [
                        AssetResponse(
                            asset_id=str(a.asset_id), client_id=str(a.client_id),
                            identifier=a.identifier, kind=a.kind, brand=a.brand,
                            model=a.model, year=a.year, notes=a.notes,
                        )
                        for a in assets
                    ]
                }

        @app.post(
            f"{org}/clients/{{client_id}}/assets",
            status_code=201,
            response_model=AssetResponse,
            tags=["verticals"],
            summary="Register an asset for a client",
            description="`identifier` (placa/serie) is unique per client — the same plate twice is a data-entry mistake, and the history view depends on it being one row.",
        )
        async def create_asset(
            organization_id: Annotated[str, Path()],
            client_id: Annotated[str, Path()],
            x_user_id: Annotated[str, Header()],
            body: AssetCreateDTO = Body(...),
        ):
            with VerticalsRepository() as repo:
                existing = [
                    a for a in repo.assets_for_client(organization_id, uuid.UUID(client_id))
                    if a.identifier.lower() == body.identifier.lower()
                ]
                if existing:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Asset '{body.identifier}' already exists for this client",
                    )
                asset = ClientAsset(
                    asset_id=uuid.uuid4(),
                    organization_id=organization_id,
                    client_id=uuid.UUID(client_id),
                    identifier=body.identifier,
                    kind=body.kind, brand=body.brand, model=body.model,
                    year=body.year, notes=body.notes,
                )
                asset = repo.save(asset)
                return AssetResponse(
                    asset_id=str(asset.asset_id), client_id=str(asset.client_id),
                    identifier=asset.identifier, kind=asset.kind, brand=asset.brand,
                    model=asset.model, year=asset.year, notes=asset.notes,
                )

        # ── Agenda: appointments (salón AND taller) ──────────────────────
        @app.get(
            f"{org}/appointments",
            response_model=AppointmentListResponse,
            tags=["verticals"],
            summary="Appointments in a date range",
            description="""One calendar, two verticals: a salón books a person, a taller books a
person **and** a vehicle (`asset_id`). Completing one opens a POS tab — a
work-order tab when the asset is set.""",
        )
        async def list_appointments(
            organization_id: Annotated[str, Path()],
            x_user_id: Annotated[str, Header()],
            date_from: Annotated[datetime, Query(alias="from")],
            date_to: Annotated[datetime, Query(alias="to")],
        ):
            with VerticalsRepository() as repo:
                rows = repo.appointments_in_range(organization_id, date_from, date_to)
                return {"data": [_map_appointment(a) for a in rows]}

        @app.post(
            f"{org}/appointments",
            status_code=201,
            response_model=AppointmentResponse,
            tags=["verticals"],
            summary="Book an appointment",
        )
        async def create_appointment(
            organization_id: Annotated[str, Path()],
            x_user_id: Annotated[str, Header()],
            body: AppointmentCreateDTO = Body(...),
        ):
            with VerticalsRepository() as repo:
                appt = Appointment(
                    appointment_id=uuid.uuid4(),
                    organization_id=organization_id,
                    client_id=uuid.UUID(body.client_id) if body.client_id else None,
                    staff_user_id=body.staff_user_id,
                    service_product_id=body.service_product_id,
                    asset_id=uuid.UUID(body.asset_id) if body.asset_id else None,
                    starts_at=body.starts_at,
                    duration_minutes=body.duration_minutes,
                    appointment_status="booked",
                    notes=body.notes,
                )
                appt = repo.save(appt)
                return _map_appointment(appt)

        @app.patch(
            f"{org}/appointments/{{appointment_id}}",
            response_model=AppointmentResponse,
            tags=["verticals"],
            summary="Reschedule, reassign, or complete an appointment",
        )
        async def update_appointment(
            organization_id: Annotated[str, Path()],
            appointment_id: Annotated[str, Path()],
            x_user_id: Annotated[str, Header()],
            body: AppointmentUpdateDTO = Body(...),
        ):
            with VerticalsRepository() as repo:
                appt = repo.session.get(Appointment, uuid.UUID(appointment_id))
                if not appt or appt.organization_id != organization_id:
                    raise HTTPException(status_code=404, detail="Appointment not found")

                for field in (
                    "starts_at", "duration_minutes", "staff_user_id",
                    "appointment_status", "notes", "converted_document_id",
                ):
                    value = getattr(body, field)
                    if value is not None:
                        setattr(appt, field, value)

                repo.session.flush()
                return _map_appointment(appt)


# ─── List envelopes ─────────────────────────────────────────────────────────
#
# The three list routes already returned `{"data": [...]}` — these name that shape
# so the routes can declare a `response_model`. Without one, the only description
# of these six endpoints was the code that happened to build them, and the
# generated API Gateway had nothing to publish.


class LotListResponse(BaseModel):
    """Sellable lots, already in FEFO order — first entry is the till's default."""

    data: List[LotResponse]


class AssetListResponse(BaseModel):
    data: List[AssetResponse]


class AppointmentListResponse(BaseModel):
    data: List[AppointmentResponse]


def _map_appointment(a: Appointment) -> AppointmentResponse:
    return AppointmentResponse(
        appointment_id=str(a.appointment_id),
        branch_id=str(a.branch_id) if a.branch_id else None,
        client_id=str(a.client_id) if a.client_id else None,
        staff_user_id=a.staff_user_id,
        service_product_id=a.service_product_id,
        asset_id=str(a.asset_id) if a.asset_id else None,
        starts_at=str(a.starts_at),
        duration_minutes=a.duration_minutes or 30,
        appointment_status=a.appointment_status or "booked",
        notes=a.notes,
        converted_document_id=a.converted_document_id,
    )
