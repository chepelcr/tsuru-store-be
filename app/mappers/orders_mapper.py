from app.dtos import (
    CrossDockingData,
    ItemResponse,
    LocationDTO,
    OrderAttachmentsDTO,
    OrderDetailLineResponse,
    OrderDetailTotals,
    OrderListResponse,
    OrderResponse,
    PaginationResponse,
    PartyDTO,
    SalePointResponse,
    CrossDockingAttachmentsDTO,
)
from app.dtos.responses.department_dto import DepartmentDTO
from app.dtos.responses.party_dto import PartyIdentificationDTO
from app.models.order import Order
from app.utils.crossdocking_utils import build_summaries
from app.utils.product_codes import find_code_number as _get_code_from_array


def order_to_response(order: Order) -> OrderResponse:
    """Map an Order entity to an OrderResponse DTO."""
    lines = []
    for ln in (order.lines or []):
        p = ln.product
        # The LINE's own codes win over the product's.
        #
        # A chain assigns its own buyer article code, and the product's `codes`
        # array holds only what the most recent import wrote — so two customers
        # ordering the same product overwrite each other there, and an order
        # could display a different customer's codes entirely. The line carries
        # the codes that came with THIS order; the product is the fallback for
        # rows written before the line had a column of its own.
        line_codes = ln.codes or []
        product_codes = p.codes if p else []
        internal_code = _get_code_from_array(line_codes, "04") or _get_code_from_array(product_codes, "04")
        code = _get_code_from_array(line_codes, "03") or _get_code_from_array(product_codes, "03")
        client_article_code = _get_code_from_array(line_codes, "02") or _get_code_from_array(product_codes, "02")
        
        lines.append(
            OrderDetailLineResponse(
                line_number=ln.line_number or 0,
                internal_code=internal_code,
                code=code,
                client_article_code=client_article_code,
                # A manual line is not always a catalog product, so its own
                # description wins over the product's.
                description=(ln.description or (p.description if p else "") or ""),
                units_per_box=(p.units_per_box if p else 0) or 0,
                quantity_ordered=ln.quantity_ordered or 0,
                units_ordered=ln.units_ordered or 0,
                unit_price=float(ln.unit_price or 0),
                discount=float(ln.discount or 0),
                line_total=float(ln.line_total or 0),
                tax=float(ln.tax or 0),
                quantity_dispatched=ln.quantity_dispatched or 0,
                dispatch_rejection_reason=ln.dispatch_rejection_reason,
                quantity_received=ln.quantity_received or 0,
                article_code=ln.article_code or "",
                # Needed to rebuild a cart when the order is billed later.
                product_id=ln.product_id,
                cabys=ln.cabys or (p.cabys.code if p and p.cabys else None),
                net_price=float(ln.net_price) if ln.net_price is not None else None,
                taxes=ln.taxes,
                discounts=ln.discounts,
                codes=ln.codes,
                # The rest of the document line, so an invoice built from this
                # order needs no second lookup — `unit_measure` above all, which
                # Hacienda requires on every line.
                unit_measure=ln.unit_measure or (p.unit_measure if p else None),
                commercial_unit_measure=(
                    ln.commercial_unit_measure or (p.commercial_unit_measure if p else None)
                ),
                customs_part=ln.customs_part or (p.customs_part if p else None),
                base_amount=float(ln.base_amount) if ln.base_amount is not None else None,
                iva_collected_factory=(
                    ln.iva_collected_factory or (p.iva_collected_factory if p else None)
                ),
            )
        )

    order_totals = None
    if lines:
        order_totals = OrderDetailTotals(
            total_lines=len(lines),
            total_quantity_ordered=sum(ln.quantity_ordered for ln in lines),
            total_units_ordered=sum(ln.units_ordered for ln in lines),
            total_quantity_dispatched=sum(ln.quantity_dispatched for ln in lines),
            total_quantity_received=sum(ln.quantity_received for ln in lines),
            subtotal=float(order.subtotal or 0),
            # The model has carried these all along; the DTO simply never
            # exposed them, so a caller could not reconcile a total.
            discounts=float(order.discounts or 0),
            taxes=float(order.taxes or 0),
            net_total=float(order.net_total or 0),
            grand_total=float(order.grand_total or 0),
        )

    crossdocking = None
    if order.crossdocking_sale_points:
        crossdocking = build_crossdocking_data(order)

    # Build client DTO from relationship
    client_dto = None
    if order.client:
        client_dto = PartyDTO(
            name=order.client.client_name,
            gln=order.client.client_gln,
            # The identification travels with the order so the invoice built
            # from it can identify the receiver, and so the POS can tell
            # whether this customer is a retail chain that needs extra fields
            # on its documents. Both are keyed on the NUMBER, never the name.
            identification=(
                PartyIdentificationDTO(
                    code=order.client.identification_code,
                    number=order.client.identification_number,
                )
                if (order.client.identification_code or order.client.identification_number)
                else None
            ),
        )

    # Build supplier DTO from organization relationship
    # vendor number (NUM_VENDEDOR) is stored as department.supplier_code
    supplier_dto = None
    if order.organization:
        dept_vendor = order.department_rel.supplier_code if order.department_rel else None
        supplier_dto = PartyDTO(
            name=order.organization.name,
            gln=order.organization.gln,
            internal_code=dept_vendor or order.organization.internal_code,
            logo_url=order.organization.logo_url,
        )

    # Build delivery location from store relationship
    delivery_location_dto = None
    if order.deliver_to_store:
        delivery_location_dto = LocationDTO(
            code=order.deliver_to_store.store_code,
            name=order.deliver_to_store.store_name,
            gln=order.deliver_to_store.gln,
            latitude=order.latitude,
            longitude=order.longitude,
        )
    elif order.delivery_location_name or order.delivery_address:
        # A manual order whose delivery is the receiver's address or a
        # hand-picked one has no Store row to name.
        delivery_location_dto = LocationDTO(
            name=order.delivery_location_name or order.delivery_address,
            latitude=order.latitude,
            longitude=order.longitude,
        )
    elif order.latitude or order.longitude:
        delivery_location_dto = LocationDTO(
            latitude=order.latitude,
            longitude=order.longitude,
        )

    # Department from relationship
    department_value = None
    if order.department_rel:
        dept = order.department_rel
        department_value = DepartmentDTO(
            department_code=dept.department_code,
            name=dept.name,
            supplier_code=dept.supplier_code,
        )

    return OrderResponse(
        source=order.source,
        currency_code=order.currency_code,
        exchange_rate=float(order.exchange_rate) if order.exchange_rate is not None else None,
        is_quote=(order.order_status == "quote"),
        document_id=order.document_id,
        document_info=order.document_info if order.document_id else None,
        order_id=order.order_id,
        company_id=order.company_id,
        document_number=order.document_number,
        document_type=order.document_type,
        bgm011=order.bgm011,
        confirmation_id=order.confirmation_id,
        confirmation_number=order.confirmation_number,
        order_type=order.order_type,
        creation_date=order.creation_date,
        delivery_date=order.delivery_date,
        order_status=order.order_status or "pending",
        client=client_dto,
        client_id=str(order.client_id) if order.client_id else None,
        supplier=supplier_dto,
        delivery_location=delivery_location_dto,
        event=order.event,
        department=department_value,
        comment=order.comment,
        line_count=order.line_count,
        total_quantities=order.total_quantities,
        subtotal=float(order.subtotal or 0),
        discounts=float(order.discounts or 0),
        net_total=float(order.net_total or 0),
        taxes=float(order.taxes or 0),
        grand_total=float(order.grand_total or 0),
        attachments=OrderAttachmentsDTO(
            ticket_url=order.ticket_url,
            pdf_url=order.pdf_url,
            excel_url=order.excel_url,
            nuevo_reporte_url=order.nuevo_reporte_url,
        ) if order.pdf_url or order.excel_url or order.nuevo_reporte_url else None,
        lines=lines,
        order_totals=order_totals,
        crossdocking=crossdocking,
    )


def orders_to_list_response(orders: list, page: int, page_size: int, total: int) -> OrderListResponse:
    """Map a list of Order entities to an OrderListResponse DTO."""
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    
    return OrderListResponse(
        data=[order_to_response(o) for o in orders],
        pagination=PaginationResponse(
            page=page,
            page_size=page_size,
            total_elements=total,
            total_pages=total_pages,
        ),
    )


def build_crossdocking_data(order: Order) -> CrossDockingData:
    """Build the CrossDockingData DTO from an Order's sale points."""
    sale_points = []
    for sp in order.crossdocking_sale_points:
        store = sp.store
        items = []
        for it in (sp.items or []):
            p = it.product
            # Extract codes from JSONB array
            internal_code = _get_code_from_array(p.codes if p else [], "04")
            original_code = _get_code_from_array(p.codes if p else [], "01")
            
            items.append(
                ItemResponse(
                    internal_code=internal_code,
                    original_code=original_code,
                    # A crossdocking item is always a catalog product — the
                    # model has no description column of its own — so the
                    # description comes from the product.
                    #
                    # This line was pasted from order_to_response, which
                    # iterates `ln` over ORDER LINES and falls back to the
                    # line's own description because a manual line need not be
                    # a catalog product. Neither applies here: the stray `ln`
                    # made every crossdocking order 500 with "NameError: name
                    # 'ln' is not defined", and `it.description` would only
                    # have traded it for an AttributeError. The mangled
                    # indentation on these lines came from the same paste.
                    description=(p.description if p else "") or "",
                    quantity=it.quantity or 0,
                    units_per_box=(p.units_per_box if p else 0) or 0,
                    total_units=it.total_units or 0,
                    sent=it.sent or 0,
                    missing=it.missing or 0,
                )
            )
        sale_points.append(
            SalePointResponse(
                store_number=(store.store_code if store else "") or "",
                store_name=(store.store_name if store else "") or "",
                full_name=sp.full_name or "",
                slot_id=(store.slot_id if store else "") or "",
                items=items,
                total_boxes=sp.total_boxes or 0,
                total_units=sp.total_units or 0,
            )
        )

    item_summary, box_summary, totals = build_summaries(sale_points)

    return CrossDockingData(
        attachments=CrossDockingAttachmentsDTO(
            pdf_url=order.crossdocking_pdf_url,
            excel_url=order.crossdocking_excel_url,
        ) if order.crossdocking_pdf_url or order.crossdocking_excel_url else None,
        sale_points=sale_points,
        item_summary=item_summary,
        box_summary=box_summary,
        totals=totals,
    )
