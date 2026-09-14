from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Body, FastAPI, HTTPException, Path, Query

from app.dtos.files import ExcelDTO
from app.dtos.requests.product_request_dto import ProductRequestDTO
from app.dtos.requests.product_status_request_dto import ProductStatusRequestDTO
from app.dtos.responses.product_bounds_dto import ProductPriceBoundsResponse
from app.dtos.responses.product_dto import ProductListResponse, ProductResponse
from app.exceptions.excel_parsing_exception import ExcelParsingException
from app.services import product_service
from app.services.product_excel_service import ProductExcelService


class ProductsController:
    def __init__(self, app: FastAPI):
        self.register_routes(app)

    def register_routes(self, app: FastAPI):

        @app.get(
            "/api/organizations/{organization_id}/products",
            response_model=ProductListResponse,
            tags=["products"],
            summary="Get all products for an organization",
            description="""Get a paginated list of products with optional search filters.

**Search filters**
- `description`: Product description (supports wildcards)
- `code`: Product code lookup in codes JSONB array
  - Format with code type: `code:01-123415` (searches for code_type_id "01" and number "123415")
  - Format without code type: `code:123415` (searches all code types for number "123415")
- `name`: Product name (supports wildcards)
- `category_id`: Filter by category ID (exact match)
- `category_name`: Filter by category name (supports wildcards)
- `status`: Filter by product status (1=Active, 2=Inactive, 3=Deleted)
- `type`: Filter by product kind (`type:product`, `type:service`, `type:program`)
- `is_offer`: Filter by storefront "Oferta" flag (`is_offer:true` / `is_offer:false`)
- `price`: Filter by net price (supports between with `~`)
  - Single value: `price:100` (exact match)
  - Range: `price:50~150` (between 50 and 150)
  - Greater than: `price>100`
  - Less than: `price<100`
- `sale_price`: Filter by sale price (supports between with `~`)
  - Single value: `sale_price:100` (exact match)
  - Range: `sale_price:50~150` (between 50 and 150)
  - Greater than: `sale_price>100`
  - Less than: `sale_price<100`

**Sorting**
- `order_by>field` (Ascending)
- `order_by<field` (Descending)
- Sortable fields: `description`, `name`, `price`, `sale_price`, `created_on`, `updated_on`

**Examples:**
- `name:*shampoo*,order_by>name` - Products with "shampoo" in name, sorted by name
- `category_id:cat-123` - Products in specific category
- `category_name:*electronics*,status:1` - Active products in electronics category
- `status:2` - Inactive products
- `status:1` - Active products only
- `type:product,is_offer:true` - Products flagged as offers (storefront "Ofertas")
- `type:program` - Programs only
- `price:50~150` - Products with net price between 50 and 150
- `sale_price:50~150` - Products with sale price between 50 and 150
- `price>100,order_by>price` - Products over 100, sorted by net price
- `category_name:*beauty*,sale_price<50,order_by>sale_price` - Beauty products under 50, sorted by sale price
""",
        )
        async def list_products(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            search: Optional[str] = Query(
                None,
                description=(
                    "Search filter string. Syntax: field:value,field2:value2. "
                    "Supports operators: : (equal), ! (not equal), > (greater), < (less), ~ (like). "
                    "Example: name:*shampoo*,order_by>internal_code"
                ),
            ),
            page: int = Query(1, ge=1, description="Page number (1-indexed)"),
            page_size: int = Query(12, ge=1, le=100, description="Items per page"),
        ):
            try:
                return product_service.get_products(
                    organization_id, page, page_size, search
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get(
            "/api/organizations/{organization_id}/products/price-bounds",
            response_model=ProductPriceBoundsResponse,
            tags=["products"],
            summary="Min/max bounds of net & sale price across the org's products",
            description=(
                "Used by the FE filter slider to size its thumbs to the org's actual price range. "
                "Any side may be null if no products exist."
            ),
        )
        async def get_product_price_bounds(
            organization_id: Annotated[str, Path(description="Organization identifier")],
        ):
            try:
                return product_service.get_price_bounds(organization_id)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get(
            "/api/organizations/{organization_id}/products/by-code/{code}",
            response_model=ProductResponse,
            tags=["products"],
            summary="Find a product by any of its codes (scanner lookup)",
            description="""Resolve a scanned code to a product.

Matches the code NUMBER against every entry in the product's `codes` array,
whatever type it is filed under — a scanner hands over digits without saying
whether they are the EAN, the internal code or the client's article code.

**Not gated by business type.** Scanning is how a POS is used; a ferretería, a
farmacia and a salón all do it. It rides the `commercial/read/products`
permission every organization already holds.

Returns **404** when nothing matches, so the caller can fall back to a normal
filtered search.""",
        )
        async def get_product_by_code(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            code: Annotated[str, Path(description="Scanned code (any code type)")],
        ):
            try:
                result = product_service.get_product_by_any_code(organization_id, code)
                if not result:
                    raise HTTPException(status_code=404, detail="Product not found")
                return result
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get(
            "/api/organizations/{organization_id}/products/{product_id}",
            response_model=ProductResponse,
            tags=["products"],
            summary="Get a specific product by ID",
        )
        async def get_product(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            product_id: Annotated[str, Path(description="Product ID")],
        ):
            try:
                result = product_service.get_product(organization_id, product_id)
                if not result:
                    raise HTTPException(status_code=404, detail="Product not found")
                return result
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get(
            "/api/organizations/{organization_id}/codes/{hacienda_code}/products/{code}",
            response_model=ProductResponse,
            tags=["products"],
            summary="Get a specific product by Hacienda code type and code number",
            description="""Get a product by searching the codes JSONB array.

**Hacienda Code Types:**
- `01`: Vendor code
- `02`: Buyer code
- `03`: Manufacturer code
- `04`: Internal code
- `99`: Other

**Example:** `/api/organizations/org-123/codes/01/products/VENDOR-001`
""",
        )
        async def get_product_by_code(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            hacienda_code: Annotated[
                str, Path(description="Hacienda code type (01=Vendor, 02=Buyer, 03=Manufacturer, 04=Internal, 99=Other)")
            ],
            code: Annotated[str, Path(description="Product code number")],
        ):
            try:
                result = product_service.get_product_by_code(organization_id, hacienda_code, code)
                if not result:
                    raise HTTPException(status_code=404, detail="Product not found")
                return result
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/products/parse",
            response_model=ProductListResponse,
            tags=["products"],
            summary="Parse and import products from Excel file",
            description="""Upload Excel file to create or update products in bulk.

**Excel Format:**
Required headers: COD_ARTIC, COD_BARRA, COD_INTERNO, DESCRIPCION, CANTIDAD_CAJA, UNIDAD_MEDIDA, PRECIO, CATEGORIA

**Behavior:**
- Creates new products if no matching code is found
- Updates category for existing products (preserves prices and other data)
- Processes each row independently (one failure doesn't affect others)
- Returns list of all successfully created/updated products

**Product Matching:**
Products are matched by codes in priority order:
1. COD_INTERNO (Internal code - type 04)
2. COD_BARRA (Barcode - type 03)
3. COD_ARTIC (Vendor code - type 01)

**Category Handling:**
- If category exists (case-insensitive match), uses existing category
- If category doesn't exist, creates new category
- If category is empty, uses default "uncategorized" category
""",
        )
        async def parse_products_excel(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            body: ExcelDTO = Body(...),
        ):
            try:
                return ProductExcelService.process_product_excel(organization_id, body)
            except ExcelParsingException as e:
                raise HTTPException(status_code=400, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post(
            "/api/organizations/{organization_id}/products",
            response_model=ProductResponse,
            status_code=201,
            tags=["products"],
            summary="Create a new product",
            description="""Create a new product for an organization.

An optional `image` field can be included with base64-encoded image data.
Supported image formats: PNG, JPEG, GIF, WEBP. Max size: 5MB.
""",
        )
        async def create_product(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            body: ProductRequestDTO,
        ):
            try:
                return product_service.create_product(organization_id, body)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.put(
            "/api/organizations/{organization_id}/products/{product_id}",
            response_model=ProductResponse,
            tags=["products"],
            summary="Update an existing product",
            description="""Update a product. Only provided fields are updated.

An optional `image` field can be included with base64-encoded image data.
Supported image formats: PNG, JPEG, GIF, WEBP. Max size: 5MB.
""",
        )
        async def update_product(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            product_id: Annotated[str, Path(description="Product ID")],
            body: ProductRequestDTO,
        ):
            try:
                return product_service.update_product(organization_id, product_id, body)
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.patch(
            "/api/organizations/{organization_id}/products/{product_id}/status",
            response_model=ProductResponse,
            tags=["products"],
            summary="Update product status",
            description="Update the status of a product (1=Active, 2=Inactive, 3=Deleted)",
        )
        async def update_product_status(
            organization_id: Annotated[str, Path(description="Organization identifier")],
            product_id: Annotated[str, Path(description="Product ID")],
            body: ProductStatusRequestDTO = Body(...),
        ):
            try:
                return product_service.update_product_status(
                    organization_id, product_id, body.status
                )
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
