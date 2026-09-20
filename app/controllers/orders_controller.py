import logging
from typing import Annotated, Optional

from pydantic import ValidationError

from fastapi import Body, FastAPI, Header, HTTPException, Path, Query

from app.dtos.files import ExcelDTO, ExcelAndColorDTO
from app.dtos import OrderListResponse, OrderResponse, SelectColorDTO
from app.dtos.requests.order_update_dto import OrderUpdateDTO
from app.dtos.requests.manual_order_dto import CreateManualOrderDTO
from app.dtos.requests.storefront_order_dto import CreateStorefrontOrderDTO
from app.dtos.responses.storefront_order_dto import StorefrontOrderCreatedResponse
from app.dtos.requests.invoice_link_dto import LinkOrderInvoiceDTO
from app.dtos.requests.sale_point_request_dto import (
    SalePointCreateDTO,
    SalePointItemsDTO,
    SalePointUpdateDTO,
)
from app.services import order_service, sale_point_service


logger = logging.getLogger(__name__)


class OrdersController:
    def __init__(self, app: FastAPI):
        self.register_routes(app)

    def register_routes(self, app: FastAPI):
        @app.post(
            "/api/organizations/{organization_id}/orders",
            status_code=201,
            tags=["orders"],
            summary="Create a pedido — storefront (anonymous) or manual (POS)",
            description="""Create a pedido. Two shapes share this route, told apart by `source`.

**`source: "manual"` — a POS pedido manual** (see `docs/MANUAL_ORDERS.md`).
Captured by hand in the document editor by an organization that does not (or
cannot yet) issue electronic documents. Carries lines with CABYS, taxes and
discounts, a client, a delivery target and optional payments.

- `document_number` is **user-writable**; omit it and the server assigns the
  next `PM-000123`. A collision returns **409**.
- `is_quote: true` opens the order in `quote` status — a proforma is an order in
  an early status, never a separate document type.
- `totals` in the body are a **hint**: the server recomputes every amount.
- Send `Idempotency-Key` (the POS outbox id) and **reuse it on every retry** —
  a pedido captured offline is replayed, and without the header it would become
  two orders.
- Delivery must resolve to either a registered `store_id` or a real address;
  there is deliberately no free-text-only mode.

**No `source` — an anonymous storefront pedido.** This route is unauthenticated
(no `x-user-id`), so guest visitors of a deployed storefront can order. Returns
the order id plus a public **tracking number** to hand off to WhatsApp.
""",
        )
        # DELIBERATELY no `response_model`. This route answers with one of two
        # genuinely different shapes — `OrderResponse` for a manual order,
        # `StorefrontOrderCreatedResponse` (id + public tracking number + status)
        # for an anonymous storefront pedido — discriminated by hand so the
        # storefront body, which predates `source`, keeps validating as before.
        #
        # A single model would strip the other's fields, and a `Union` is worse:
        # Pydantic would try `OrderResponse` first and, if it validates loosely,
        # silently drop the tracking number the customer needs to follow the order.
        # Documented here rather than papered over with a model that is wrong half
        # the time.
        async def create_order(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            body: dict = Body(...),
            idempotency_key: Annotated[
                Optional[str],
                Header(
                    alias="Idempotency-Key",
                    description="POS outbox id; reused on every retry to dedupe replays",
                ),
            ] = None,
            x_user_id: Annotated[
                Optional[str], Header(alias="x-user-id", description="Capturing user")
            ] = None,
        ):
            # Discriminated by hand rather than by a Pydantic Union so the
            # storefront body — which predates `source` and never sends it —
            # keeps validating exactly as before.
            is_manual = body.get("source") == "manual"
            try:
                if is_manual:
                    dto = CreateManualOrderDTO.model_validate(body)
                    return order_service.create_manual_order(
                        organization_id,
                        dto,
                        created_by=x_user_id,
                        idempotency_key=idempotency_key,
                    )
                storefront_dto = CreateStorefrontOrderDTO.model_validate(body)
                return order_service.create_storefront_order(
                    organization_id, storefront_dto
                )
            except ValidationError as e:
                raise HTTPException(status_code=422, detail=e.errors())
            except FileExistsError as e:
                raise HTTPException(status_code=409, detail=str(e))
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/orders/{document_number}/ticket",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Generate the order's 80mm thermal ticket",
            description="""Render the order as a receipt-roll PDF and return the order with
`attachments.ticket_url` set.

Generated **server-side**, like the order's other documents — not printed from
the browser — so the slip is identical however it is opened, and a reprint or an
emailed copy matches the original exactly.

Regenerating is intentional: a ticket reprinted after the order was invoiced
picks up the consecutive number, document key and QR it did not have before.

The heading names what the slip actually is: `PROFORMA` for a quote (with "no
es un comprobante fiscal" under it), `ORDEN DE TRABAJO` for a taller OT,
`PEDIDO` for a manual order.""",
        )
        async def generate_order_ticket(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            document_number: Annotated[str, Path(description="Order document number")],
        ):
            try:
                return order_service.generate_order_ticket(organization_id, document_number)
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/orders/{document_number}/invoice",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Record that a delivered order was billed",
            description="""Link an order to the electronic document that billed it.

Without this link the frontend cannot tell that a pedido is already invoiced,
so nothing prevents a second factura for the same order. Returns **409** if the
order is already linked to a different sale.
""",
        )
        async def link_order_invoice(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            document_number: Annotated[str, Path(description="Order document number")],
            body: LinkOrderInvoiceDTO = Body(...),
        ):
            try:
                return order_service.link_order_invoice(
                    organization_id,
                    document_number,
                    sale_id=body.sale_id,
                    document_type=body.document_type,
                    consecutive_number=body.consecutive_number,
                    document_key=body.document_key,
                    issued_on=body.issued_on,
                )
            except FileExistsError as e:
                raise HTTPException(status_code=409, detail=str(e))
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/orders/parse",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Parse and save an order details (DETALLES) Excel file",
        )
        async def parse_and_save_order(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            body: ExcelDTO = Body(...),
        ):
            try:
                return order_service.process_order_excel(organization_id, body)
            except ValueError as e:
                raise HTTPException(status_code=409, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=422, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/orders/{document_number}/crossdocking/sale-points",
            response_model=OrderResponse,
            status_code=201,
            tags=["orders"],
            summary="Capture a cross-docking sale point by hand",
            description="""Add a distribution point to an order **without** an Excel file.

Until now sale points could only be created by uploading a spreadsheet, so a
supplier who had the figures — from an email, a portal, a phone call — but not
the file could not record them. This is the same data by another route; the
Excel importer is untouched and the two coexist, so a partial upload can be
finished by hand.

- A point either names a registered `store_id` (bringing its GLN and chain) or
  carries a free `full_name`.
- **Totals are derived**, never sent: boxes and units are computed from the
  items and the product's `units_per_box`, the same way the parser does it, so a
  hand-captured order reconciles against an imported one.
- Allocating more of a product than the order line ordered returns **422**
  naming the line — the check the spreadsheet path gets from its template.
""",
        )
        async def create_sale_point(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            document_number: Annotated[str, Path(description="Order document number")],
            body: SalePointCreateDTO = Body(...),
        ):
            try:
                return sale_point_service.create_sale_point(organization_id, document_number, body)
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

        @app.patch(
            "/api/organizations/{organization_id}/orders/{document_number}/crossdocking/sale-points/{sale_point_id}",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Rename a sale point",
            description="Works on any sale point, including one that came from an Excel upload — which is the natural fix for a typo in a supplier's file.",
        )
        async def update_sale_point(
            organization_id: Annotated[str, Path()],
            document_number: Annotated[str, Path()],
            sale_point_id: Annotated[int, Path()],
            body: SalePointUpdateDTO = Body(...),
        ):
            try:
                return sale_point_service.update_sale_point(
                    organization_id, document_number, sale_point_id, body
                )
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

        @app.put(
            "/api/organizations/{organization_id}/orders/{document_number}/crossdocking/sale-points/{sale_point_id}/items",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Replace a sale point's item allocation",
            description="Totals are re-derived from the items; send boxes only, units follow from the product's `units_per_box`.",
        )
        async def set_sale_point_items(
            organization_id: Annotated[str, Path()],
            document_number: Annotated[str, Path()],
            sale_point_id: Annotated[int, Path()],
            body: SalePointItemsDTO = Body(...),
        ):
            try:
                return sale_point_service.set_sale_point_items(
                    organization_id, document_number, sale_point_id, body
                )
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

        @app.delete(
            "/api/organizations/{organization_id}/orders/{document_number}/crossdocking/sale-points/{sale_point_id}",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Remove a sale point and its items",
        )
        async def delete_sale_point(
            organization_id: Annotated[str, Path()],
            document_number: Annotated[str, Path()],
            sale_point_id: Annotated[int, Path()],
        ):
            try:
                return sale_point_service.delete_sale_point(
                    organization_id, document_number, sale_point_id
                )
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/orders/{document_number}/crossdocking/parse",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Parse and save a crossdocking Excel file for an existing order",
        )
        async def parse_and_save_crossdocking(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            document_number: Annotated[str, Path(description="Order document number")],
            body: ExcelAndColorDTO = Body(...),
        ):
            try:
                return order_service.process_crossdocking_excel(
                    organization_id, document_number, body
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/orders/{document_number}/reprocess",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Reprocess order: re-parse Excel files and regenerate all outputs",
        )
        async def reprocess_order(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            document_number: Annotated[str, Path(description="Order document number")],
            body: Optional[SelectColorDTO] = Body(None),
        ):
            try:
                color = body.color if body else None
                return order_service.reprocess_order(organization_id, document_number, color)
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get(
            "/api/organizations/{organization_id}/orders",
            response_model=OrderListResponse,
            tags=["orders"],
            summary="Get all orders for an organization",
            description="""Get a paginated list of orders with optional search filters.

**Search operators**
- `:` = Equal
- `!` = Not equal
- `<` = Less than
- `>` = Greater than
- `~` = Like (contains)

**Between (BETWEEN)**
- `field:value1~value2` = Between values (e.g. `deliveryDate:01/02/2025~28/02/2025`)
- `field!value1~value2` = Not between values

**Search filters**
- `documentNumber`: Document number (supports wildcards)
- `clientName`: Client name (supports wildcards)
- `supplierName`: Supplier name (supports wildcards)
- `deliveryDate`: Delivery date — dd/mm/yyyy (supports between)
- `creationDate`: Creation date — dd/mm/yyyy (supports between)
- `orderStatus`: Order status (pending, processing, shipped, delivered, cancelled)
- `deliverToCode`: Delivery place code
- `deliverToName`: Delivery place name (supports wildcards)
- `confirmationNumber`: Confirmation number (supports wildcards)

**Separators**
Filters are individual conditions separated by commas (,).
Logical AND and OR conditions can be applied:
- AND: All conditions separated by commas and outside parentheses are combined with AND
- OR: To apply OR conditions, group them inside parentheses

**Examples**
- `clientName:*corp*,orderStatus:pending` → Orders where client name contains "corp" **and** status is pending
- `(orderStatus:pending,orderStatus:processing)` → Orders with status pending **or** processing
- `clientName:*test*,(orderStatus:pending,orderStatus:shipped)` → Client name contains "test" **and** (status pending **or** shipped)
- `deliveryDate:01/02/2025~28/02/2025` → Orders with delivery date between Feb 1 and Feb 28

**Wildcards**
- `*ana*` = Contains (e.g. `clientName:*ana*` → Ariana, Melania)
- `Al*` = Starts with (e.g. `clientName:Al*` → Alberto, Alana)
- `*el` = Ends with (e.g. `clientName:*el` → Daniel, Miguel)

**Note:** Fields that support wildcards (`documentNumber`, `clientName`, `supplierName`, `deliverToName`, `confirmationNumber`) automatically apply case-insensitive contains matching even without `*` wildcards.

**Sorting**
- `orderBy>field` (Ascending)
- `orderBy<field` (Descending)
- Sortable fields: `documentNumber`, `clientName`, `supplierName`, `deliveryDate`, `creationDate`, `orderStatus`, `createdOn`, `updatedOn`

**Example with sorting:** `orderStatus:pending,orderBy>deliveryDate`
""",
        )
        async def get_orders(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            search: Optional[str] = Query(
                None,
                description=(
                    "Search filter string. Syntax: field:value,field2:value2. "
                    "Supports operators: : (equal), ! (not equal), > (greater), < (less), ~ (like). "
                    "Use () for OR grouping. Example: clientName:*Test*,orderStatus:pending,orderBy>deliveryDate"
                ),
                examples=["orderStatus:pending,orderBy>deliveryDate"],
            ),
            page: int = Query(1, ge=1, description="Page number (1-indexed)"),
            page_size: int = Query(12, ge=1, le=100, description="Items per page"),
        ):
            return order_service.get_orders(
                organization_id,
                search=search,
                page=page,
                page_size=page_size,
            )

        @app.get(
            "/api/organizations/{organization_id}/orders/{document_number}",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Get a specific order by document number (includes crossdocking if uploaded)",
        )
        async def get_order_by_number(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            document_number: Annotated[str, Path(description="Order document number")],
        ):
            try:
                return order_service.get_order(organization_id, document_number)
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))

        @app.patch(
            "/api/organizations/{organization_id}/orders/{document_number}",
            response_model=OrderResponse,
            tags=["orders"],
            summary="Update an order's status and/or delivery date",
            description=(
                "Both fields are optional; at least one is required, so a "
                "status-only body keeps working.\n\n"
                "**Delivery date** may be changed only while the order is "
                "`pending`, is not yet billed, and the new date is not in the "
                "past — moving it alters a commitment to the customer rather "
                "than recording what happened. The order's spreadsheets are "
                "rewritten to match, because `reprocess` re-reads them and would "
                "otherwise revert a database-only change.\n\n"
                "An illegal status transition or a refused date is **400**, not "
                "500: both are things the caller can correct."
            ),
        )
        async def update_order(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            document_number: Annotated[str, Path(description="Order document number")],
            body: OrderUpdateDTO = Body(...),
        ):
            try:
                return order_service.update_order(
                    organization_id,
                    document_number,
                    status_code=body.status,
                    delivery_date=body.delivery_date,
                )
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except ValueError as e:
                # An illegal transition, a billed order, a past date. These used
                # to fall through to the bare `except` below and return 500 for
                # what is plainly a client error.
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                logger.error(
                    "Error updating order %s: %s", document_number, e, exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
