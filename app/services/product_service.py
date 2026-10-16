from __future__ import annotations

import base64
import logging
import uuid
from decimal import Decimal
from typing import Optional

from app.dtos.requests.product_request_dto import ProductCodeDTO, ProductRequestDTO
from app.dtos.files import ImageDTO
from app.dtos.responses.product_dto import (
    CabysResponse,
    CategoryResponse,
    ProductCodeResponse,
    ProductDiscountResponse,
    ProductListResponse,
    ProductResponse,
    ProductTaxResponse,
)
from app.dtos.responses.pagination_dto import PaginationResponse
from app.dtos.responses.product_bounds_dto import ProductPriceBoundsResponse
from app.enums.product_search_filters import ProductSearchFilters
from app.enums.product_status import ProductStatus
from app.enums.product_type import ProductType
from app.models.product import Product
from app.repositories.product_repository import ProductRepository
from app.services import cabys_service
from app.services.line_calculation_service import LineCalculator, LineInput
from app.services.pdf_service import upload_file_to_s3
from app.utils.search_utils import SearchUtils

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB


def _validate_unique_codes(
    organization_id: str,
    codes: list[ProductCodeDTO],
    product_id: Optional[str],
    repo: ProductRepository,
) -> None:
    """Validate that no Hacienda (code_type_id, number) pair is duplicated across products.

    Raises:
        ValueError: If a duplicate code is found.
    """
    if not codes:
        return

    for code in codes:
        if not code.code_type_id or not code.number:
            continue

        existing = repo.find_by_company_and_code(
            organization_id,
            code.code_type_id,
            code.number,
            exclude_product_id=product_id,
        )

        if existing:
            raise ValueError(
                f"Product code conflict: another product (ID: {existing.id}) already has "
                f"code type '{code.code_type_id}' with number '{code.number}'"
            )


def _coerce_list(val) -> list:
    return val if isinstance(val, list) else []


def get_products(
    company_id: str,
    page: int = 1,
    page_size: int = 12,
    search: str = None,
) -> ProductListResponse:
    """Get paginated products for a company with optional search filters."""
    search_filters = None
    order_by = None

    if search:
        filters, order_result = SearchUtils.parse_search_filter(
            search, Product, ProductSearchFilters
        )
        if filters:
            search_filters = filters
        if order_result:
            order_by = order_result

    with ProductRepository() as repo:
        products, total = repo.find_all_by_company(
            company_id,
            search_filters=search_filters,
            order_by=order_by,
            page=page,
            page_size=page_size,
        )
        data = [_map_product(p) for p in products]

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    return ProductListResponse(
        data=data,
        pagination=PaginationResponse(
            page=page,
            page_size=page_size,
            total_elements=total,
            total_pages=total_pages,
        ),
    )


def get_price_bounds(organization_id: str) -> ProductPriceBoundsResponse:
    """Return net & sale price bounds for the org so the FE slider can size itself."""
    with ProductRepository() as repo:
        net_min, net_max, sale_min, sale_max = repo.get_price_bounds(organization_id)
    return ProductPriceBoundsResponse(
        net_min=net_min,
        net_max=net_max,
        sale_min=sale_min,
        sale_max=sale_max,
    )


def get_product(organization_id: str, product_id: str) -> Optional[ProductResponse]:
    """Get a single product by ID."""
    with ProductRepository() as repo:
        product = repo.find_by_id_and_company(product_id, organization_id)
        if not product:
            return None
        return _map_product(product)


def get_product_by_any_code(organization_id: str, code: str) -> Optional[ProductResponse]:
    """Resolve a scanned code to a product, whatever code type it is filed under.

    Ungated on purpose (TSR-155): scanning is how a POS is used, so this rides
    the `commercial/read/products` permission every organization already holds
    rather than a vertical module.
    """
    with ProductRepository() as repo:
        product = repo.find_by_company_and_any_code(organization_id, code)
        if not product:
            return None
        return _map_product(product)


def get_product_by_code(
    organization_id: str, hacienda_code: str, code: str
) -> Optional[ProductResponse]:
    """Get a single product by Hacienda code type and code number."""
    with ProductRepository() as repo:
        product = repo.find_by_company_and_code(organization_id, hacienda_code, code)
        if not product:
            return None
        return _map_product(product)


def create_product(organization_id: str, dto: ProductRequestDTO) -> ProductResponse:
    """Create a new product."""
    with ProductRepository() as repo:
        category_id = dto.category_id or repo._ensure_default_category(organization_id)

        product = Product(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            name=dto.name or dto.description or "",
            description=dto.description or dto.name or "",
            price=dto.price or 0,
            category_id=category_id,
            status=ProductStatus.ACTIVE,
            units_per_box=dto.units_per_box,
        )
        _apply_catalogue_fields(product, dto)
        repo.session.add(product)
        repo.session.flush()

        # Image: a pre-uploaded URL (org media library) is stored directly; a
        # base64 blob is uploaded here (legacy path).
        if dto.image and dto.image.data:
            url = _save_product_image(organization_id, product.id, dto.image)
            product.image_url = url
            repo.session.flush()
        elif dto.image_url is not None:
            product.image_url = dto.image_url or None
            repo.session.flush()

        _apply_fiscal_fields(product, dto, repo)
        repo.session.flush()

        return _map_product(product)


def update_product(
    organization_id: str, product_id: str, dto: ProductRequestDTO
) -> ProductResponse:
    """Update an existing product."""
    with ProductRepository() as repo:
        product = repo.find_by_id_and_company(product_id, organization_id)
        if not product:
            raise LookupError(f"Product '{product_id}' not found")

        if dto.name is not None:
            product.name = dto.name
        if dto.description is not None:
            product.description = dto.description
        if dto.units_per_box is not None:
            product.units_per_box = dto.units_per_box
        if dto.price is not None:
            product.price = dto.price
        if dto.category_id is not None:
            product.category_id = dto.category_id

        _apply_catalogue_fields(product, dto)

        if dto.image and dto.image.data:
            url = _save_product_image(organization_id, product.id, dto.image)
            product.image_url = url
        elif dto.image_url is not None:
            product.image_url = dto.image_url or None

        _apply_fiscal_fields(product, dto, repo)
        repo.save(product)
        return _map_product(product)


def update_product_status(
    organization_id: str, product_id: str, status: int
) -> ProductResponse:
    """
    Update a product's status.
    
    Args:
        organization_id: Organization ID
        product_id: Product ID
        status: New status (1=Active, 2=Inactive, 3=Deleted)
        
    Returns:
        Updated product response
        
    Raises:
        LookupError: If product not found
        ValueError: If status is invalid
    """
    # Validate status
    if not ProductStatus.is_valid(status):
        valid_statuses = ProductStatus.get_valid_statuses()
        raise ValueError(
            f"Invalid status value: {status}. Must be one of {valid_statuses} "
            f"(1=Active, 2=Inactive, 3=Deleted)"
        )
    
    with ProductRepository() as repo:
        product = repo.find_by_id_and_company(product_id, organization_id)
        if not product:
            raise LookupError(f"Product '{product_id}' not found")

        product.status = status
        repo.save(product)
        return _map_product(product)


def _apply_catalogue_fields(product: Product, dto: ProductRequestDTO) -> None:
    """Apply storefront catalogue fields without changing CABYS fiscal data."""
    if dto.type is not None:
        product.type = dto.type
    if dto.on_sale is not None:
        product.on_sale = dto.on_sale
    if dto.original_price is not None:
        product.original_price = dto.original_price
    if dto.discount is not None:
        product.discount = dto.discount
    if dto.is_offer is not None:
        product.is_offer = dto.is_offer
    if dto.stock_quantity is not None:
        product.stock_quantity = dto.stock_quantity
    if dto.low_stock_threshold is not None:
        product.low_stock_threshold = dto.low_stock_threshold
    if dto.track_inventory is not None:
        product.track_inventory = dto.track_inventory


def _apply_fiscal_fields(product: Product, dto: ProductRequestDTO, repo) -> None:
    """Apply all fiscal/Hacienda fields from dto onto product (mutates in place)."""

    # 1. CABYS link — data-services owns the row; we only set the FK.
    # The FK constraint validates existence at flush time.
    if dto.cabys_id is not None:
        try:
            product.cabys_id = uuid.UUID(dto.cabys_id)
        except (TypeError, ValueError):
            raise ValueError(
                f"cabys_id must be a valid UUID. Received: {dto.cabys_id!r}"
            )

    # 2. Scalar fiscal fields (only set if provided)
    if dto.unit_measure is not None:
        product.unit_measure = dto.unit_measure
    if dto.commercial_unit_measure is not None:
        product.commercial_unit_measure = dto.commercial_unit_measure
    if dto.is_packaged is not None:
        product.is_packaged = dto.is_packaged
    if dto.quantity is not None:
        product.quantity = Decimal(str(dto.quantity))
    if dto.unit_price is not None:
        product.unit_price = Decimal(str(dto.unit_price))
    if dto.customs_part is not None:
        product.customs_part = dto.customs_part

    # Exemption block + factory VAT indicator
    if dto.exemption_authorization_code is not None:
        product.exemption_authorization_code = dto.exemption_authorization_code
    if dto.exempted_rate is not None:
        product.exempted_rate = Decimal(str(dto.exempted_rate))
    if dto.exemption_amount is not None:
        product.exemption_amount = Decimal(str(dto.exemption_amount))
    if dto.iva_collected_factory is not None:
        product.iva_collected_factory = dto.iva_collected_factory
    if dto.factory_tax_charge_id is not None:
        product.factory_tax_charge_id = dto.factory_tax_charge_id

    # 3. Packaged validation
    if product.is_packaged:
        if product.quantity is None or product.unit_price is None:
            raise ValueError(
                "When is_packaged is True both quantity and unit_price are required."
            )

    # 4. Compute line amounts via the dedicated calc services. The DTO-level
    # validators (Pydantic) already handle per-discount / per-tax shape
    # validation; the calc raises DiscountValidationError for missing reason
    # gaps which bubbles up as a 422.
    discount_dtos = list(dto.discounts or [])
    tax_dtos = list(dto.taxes or [])

    # The CABYS code decides which ISEBEC (05) formula applies — toilet soap
    # prices per gram, everything else per volume — so it has to be resolved
    # from the linked row; the request only carries the FK.
    cabys_code_for_calc: Optional[str] = None
    if product.cabys_id is not None:
        cabys_row = cabys_service.get_by_id(str(product.cabys_id), session=repo.session)
        if cabys_row:
            cabys_code_for_calc = cabys_row.code

    # Pre-discount line subtotal = price × quantity for packaged products,
    # else just price (qty 1). The tax service uses this as the IVA base when a
    # royalty (01) or bonus (03) discount is present — Nota 20 leaves those
    # natures' base un-eroded.
    line_quantity = Decimal(str(product.quantity or 1))
    line_price = Decimal(str(product.price))
    monto_total_original = (
        line_price * line_quantity if bool(product.is_packaged) else line_price
    )

    line_input = LineInput(
        price=line_price,
        quantity=line_quantity,
        is_packaged=bool(product.is_packaged),
        detail_quantity=line_quantity,
        discounts=discount_dtos,
        taxes=tax_dtos,
        manual_base_amount=(
            Decimal(str(dto.base_amount)) if dto.base_amount is not None else None
        ),
        monto_total_original=monto_total_original,
        # `IVACobradoFabrica` 01 means the issuer absorbs this product's IVA,
        # so its `sale_price` must not include it. Without this the catalog
        # price carried tax the customer never pays, and every order line
        # copied from the product inherited the discrepancy.
        iva_collected_factory=product.iva_collected_factory,
    )
    result = LineCalculator().compute(line_input, cabys_code=cabys_code_for_calc)

    # 5. Codes — uniqueness check + JSONB storage
    if dto.codes is not None:
        _validate_unique_codes(product.organization_id, dto.codes, product.id, repo)
        product.codes = [c.model_dump() for c in dto.codes]

    # 6. Persist discount/tax JSONB enriched with the per-row computed amounts.
    product.discounts = _hydrate_discount_jsonb(discount_dtos, result.discount.per_discount)
    product.taxes = _hydrate_tax_jsonb(tax_dtos, result.tax.per_tax)
    product.base_amount = result.tax.base_amount
    product.sale_price = result.sale_price


def _hydrate_discount_jsonb(dtos, rows):
    """Merge per-row computed `amount` into the discount JSONB payload."""
    out = []
    for dto, row in zip(dtos, rows):
        payload = dto.model_dump()
        payload["amount"] = float(row.amount)
        out.append(payload)
    return out


def _hydrate_tax_jsonb(dtos, rows):
    """Merge each computed `amount` back onto the tax row it belongs to.

    Matched by tax CODE, not by position. `compute_line_taxes` returns its rows
    in Hacienda's evaluation order — specific excises, then 99, then the IVA
    family — which is NOT the order the request listed them in. Zipping the two
    put the ISC amount on the IVA row (and vice versa) for any product that
    declared its IVA first, which is the usual way round.
    """
    by_code: dict[str, list] = {}
    for row in rows:
        by_code.setdefault(row.tax_type_id, []).append(row)

    out = []
    for dto in dtos:
        payload = dto.model_dump()
        queue = by_code.get(dto.tax_type_id)
        if queue:
            payload["amount"] = float(queue.pop(0).amount)
        out.append(payload)
    return out


def _save_product_image(organization_id: str, product_id: str, image: ImageDTO) -> str:
    """Validate, decode, and upload a product image to S3."""
    if not image.data:
        raise ValueError("Image data is empty")

    content_type = (image.content_type or "").lower().strip()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(
            f"Invalid image type '{content_type}'. "
            f"Allowed: {', '.join(ALLOWED_IMAGE_TYPES.keys())}"
        )

    ext = ALLOWED_IMAGE_TYPES[content_type]

    # Strip data URL prefix if present (e.g. "data:image/png;base64,...")
    data = image.data
    if data.startswith("data:"):
        if "," in data:
            data = data.split(",", 1)[1]

    try:
        decoded = base64.b64decode(data)
    except Exception:
        raise ValueError("Invalid base64 image data")

    if len(decoded) > MAX_IMAGE_SIZE:
        raise ValueError(
            f"Image size ({len(decoded)} bytes) exceeds maximum allowed "
            f"({MAX_IMAGE_SIZE // (1024 * 1024)}MB)"
        )

    key = f"organizations/{organization_id}/products/{product_id}/image.{ext}"
    return upload_file_to_s3(decoded, key, content_type)


def _map_product(product: Product) -> ProductResponse:
    category = None
    if product.category:
        category = CategoryResponse(
            category_id=product.category_id,
            name=product.category.name if hasattr(product.category, "name") else None,
        )

    cabys_response = None
    if product.cabys:
        cabys_response = CabysResponse(
            id=str(product.cabys.id),
            code=product.cabys.code,
            description=product.cabys.description,
            product_type_id=product.cabys.product_type_id,
            tax_rate_id=product.cabys.tax_rate_id,
            country_code=product.cabys.country_code,
        )

    # JSONB rows are stored with the same snake_case shape as the response
    # DTOs, so we can validate straight from dict to model with no manual
    # field plumbing.
    codes = [ProductCodeResponse.model_validate(c) for c in _coerce_list(product.codes)]
    discounts = [
        ProductDiscountResponse.model_validate(d) for d in _coerce_list(product.discounts)
    ]
    taxes = [ProductTaxResponse.model_validate(t) for t in _coerce_list(product.taxes)]

    return ProductResponse(
        product_id=product.id,
        company_id=product.organization_id,
        name=product.name,
        description=product.description,
        units_per_box=product.units_per_box,
        price=product.price,
        image_url=product.image_url,
        category=category,
        status=product.status,
        stock_quantity=product.stock_quantity,
        low_stock_threshold=product.low_stock_threshold,
        track_inventory=product.track_inventory,
        type=product.type or ProductType.PRODUCT.value,
        on_sale=product.on_sale,
        is_offer=product.is_offer,
        original_price=product.original_price,
        discount=product.discount,
        cabys=cabys_response,
        unit_measure=product.unit_measure,
        commercial_unit_measure=product.commercial_unit_measure,
        is_packaged=product.is_packaged,
        quantity=float(product.quantity) if product.quantity is not None else None,
        unit_price=float(product.unit_price) if product.unit_price is not None else None,
        customs_part=product.customs_part,
        codes=codes,
        discounts=discounts,
        taxes=taxes,
        base_amount=float(product.base_amount) if product.base_amount is not None else None,
        sale_price=float(product.sale_price) if product.sale_price is not None else None,
        exemption_authorization_code=product.exemption_authorization_code,
        exempted_rate=(
            float(product.exempted_rate) if product.exempted_rate is not None else None
        ),
        exemption_amount=(
            float(product.exemption_amount)
            if product.exemption_amount is not None
            else None
        ),
        iva_collected_factory=product.iva_collected_factory,
        factory_tax_charge_id=product.factory_tax_charge_id,
    )
