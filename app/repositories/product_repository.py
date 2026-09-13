from __future__ import annotations

import logging
from typing import List, Optional, Tuple
import uuid

from sqlalchemy import asc, func, select, and_
from sqlalchemy.exc import SQLAlchemyError

from app.configuration.database_connection import DatabaseConnection
from app.dtos.requests.product_request_dto import ProductCodeDTO
from app.enums.hacienda_codes import ProductCodeType
from app.utils.product_fiscal_defaults import DEFAULT_UNIT_MEASURE, default_iva_row
from app.enums.product_status import ProductStatus
from app.models.category import Category
from app.models.product import Product

DEFAULT_CATEGORY_ID = "uncategorized"

logger = logging.getLogger(__name__)


class ProductRepository(DatabaseConnection):

    def __init__(self):
        super().__init__()

    def find_by_id_and_company(self, product_id: str, company_id: str) -> Optional[Product]:
        try:
            stmt = (
                select(Product)
                .where(
                    and_(
                        Product.id == product_id,
                        Product.organization_id == company_id,
                        Product.status != ProductStatus.DELETED,
                    )
                )
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error finding product {product_id} for company {company_id}: {e}", exc_info=True)
            raise

    def find_by_company_and_any_code(
        self, company_id: str, code: str
    ) -> Optional[Product]:
        """Find a product by code NUMBER, whatever code type it is filed under.

        A scanner hands over digits with no indication of whether they are the
        EAN, the internal code or the client's article code — so unlike
        `find_by_company_and_code` this matches on the number alone.

        JSONB containment matches partial objects, so probing with just
        `{"number": ...}` hits any entry in the codes array regardless of its
        `code_type_id`.
        """
        try:
            from sqlalchemy import cast
            from sqlalchemy.dialects.postgresql import JSONB

            stmt = select(Product).where(
                and_(
                    Product.organization_id == company_id,
                    Product.status != ProductStatus.DELETED,
                    Product.codes.op("@>")(cast([{"number": code}], JSONB)),
                )
            )
            # A code should be unique per org, but duplicates exist in real
            # catalogs; first match beats raising at the till.
            return self.session.execute(stmt).scalars().first()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding product by code {code} for company {company_id}: {e}",
                exc_info=True,
            )
            raise

    def find_by_company_and_code(
        self, company_id: str, hacienda_code: str, code: str, exclude_product_id: Optional[str] = None
    ) -> Optional[Product]:
        """Find product by Hacienda code type and code number in JSONB codes array.
        
        Args:
            company_id: Organization ID
            hacienda_code: Code type (01, 02, 03, 04, 99)
            code: Code number
            exclude_product_id: Optional product ID to exclude from search (for update validation)
        """
        try:
            from sqlalchemy import cast
            from sqlalchemy.dialects.postgresql import JSONB

            # Build the containment object from the canonical DTO so the
            # JSONB keys can never drift from the rest of the codebase.
            probe = ProductCodeDTO(code_type_id=hacienda_code, number=code).model_dump(exclude_none=True)

            conditions = [
                Product.organization_id == company_id,
                Product.status != ProductStatus.DELETED,
                Product.codes.op("@>")(cast([probe], JSONB)),
            ]
            
            # Exclude current product when validating updates
            if exclude_product_id:
                conditions.append(Product.id != exclude_product_id)
            
            stmt = select(Product).where(and_(*conditions))
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding product by code {hacienda_code}-{code} for company {company_id}: {e}",
                exc_info=True,
            )
            raise

    def find_by_company_and_internal_code(self, company_id: str, internal_code: str) -> Optional[Product]:
        """Find product by internal code (type 04) in JSONB codes array."""
        try:
            from sqlalchemy import cast
            from sqlalchemy.dialects.postgresql import JSONB

            probe = ProductCodeDTO(
                code_type_id=ProductCodeType.INTERNAL, number=internal_code
            ).model_dump(exclude_none=True)

            stmt = (
                select(Product)
                .where(
                    and_(
                        Product.organization_id == company_id,
                        Product.status != ProductStatus.DELETED,
                        Product.codes.op("@>")(cast([probe], JSONB)),
                    )
                )
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding product by internal code {internal_code} for company {company_id}: {e}",
                exc_info=True,
            )
            raise

    def find_all_by_company(
        self,
        company_id: str,
        search_filters: list | None = None,
        order_by: tuple | None = None,
        page: int = 1,
        page_size: int = 12,
    ) -> tuple[List[Product], int]:
        try:
            base_conditions = [
                Product.organization_id == company_id,
                Product.status != ProductStatus.DELETED,
            ]
            if search_filters:
                base_conditions.extend(search_filters)

            base_filter = and_(*base_conditions)
            
            # Check if we need to join with categories table
            # This happens when search includes categoryName filter
            needs_category_join = self._needs_category_join(search_filters)

            # Count total - use distinct if joining
            if needs_category_join:
                count_stmt = (
                    select(func.count(func.distinct(Product.id)))
                    .select_from(Product)
                    .join(Category, Product.category_id == Category.id)
                    .where(base_filter)
                )
            else:
                count_stmt = select(func.count()).select_from(Product).where(base_filter)
            
            total = self.session.execute(count_stmt).scalar() or 0

            # Build query - use distinct if joining
            if needs_category_join:
                stmt = (
                    select(Product)
                    .distinct()
                    .join(Category, Product.category_id == Category.id)
                    .where(base_filter)
                )
            else:
                stmt = select(Product).where(base_filter)

            # Apply sorting
            if order_by:
                stmt = stmt.order_by(order_by[0])
            else:
                stmt = stmt.order_by(asc(Product.name))

            # Apply pagination
            offset = (page - 1) * page_size
            stmt = stmt.offset(offset).limit(page_size)

            products = list(self.session.execute(stmt).scalars().all())
            return products, total
        except SQLAlchemyError as e:
            logger.error(
                f"Error finding products for company {company_id}: {e}", exc_info=True
            )
            raise
    
    def get_price_bounds(self, company_id: str) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Return (net_min, net_max, sale_min, sale_max) across the organization's non-deleted products.

        Any side may be `None` when no products exist or no `sale_price` is set; callers should
        fall back to a sensible default in that case.
        """
        try:
            stmt = (
                select(
                    func.min(Product.price),
                    func.max(Product.price),
                    func.min(Product.sale_price),
                    func.max(Product.sale_price),
                )
                .where(
                    and_(
                        Product.organization_id == company_id,
                        Product.status != ProductStatus.DELETED,
                    )
                )
            )
            row = self.session.execute(stmt).one_or_none()
            if not row:
                return (None, None, None, None)
            net_min, net_max, sale_min, sale_max = row
            return (
                float(net_min) if net_min is not None else None,
                float(net_max) if net_max is not None else None,
                float(sale_min) if sale_min is not None else None,
                float(sale_max) if sale_max is not None else None,
            )
        except SQLAlchemyError as e:
            logger.error(f"Error computing price bounds for company {company_id}: {e}", exc_info=True)
            raise

    def _needs_category_join(self, search_filters: list | None) -> bool:
        """Check if any search filter references the Category table."""
        if not search_filters:
            return False
        
        # Convert filters to string and check if Category is referenced
        for filter_obj in search_filters:
            filter_str = str(filter_obj)
            if 'categories.name' in filter_str.lower() or 'category.name' in filter_str.lower():
                return True
        
        return False

    def _ensure_default_category(self, company_id: str) -> str:
        """Ensure the default 'uncategorized' category exists for the org."""
        stmt = select(Category).where(Category.id == DEFAULT_CATEGORY_ID)
        existing = self.session.execute(stmt).scalar_one_or_none()
        if not existing:
            cat = Category(
                id=DEFAULT_CATEGORY_ID,
                organization_id=company_id,
                name="Sin categoría",
                slug="sin-categoria",
                description="Productos sin categoría asignada",
                background_color="#FFFFFF",
                button_color="#000000",
                is_active=True,
                sort_order=999,
            )
            self.session.add(cat)
            self.session.flush()
        return DEFAULT_CATEGORY_ID

    def upsert_by_internal_code(
        self,
        company_id: str,
        internal_code: str,
        description: str = None,
        original_code: str = None,
        client_article_code: str = None,
        code: str = None,
        units_per_box: int = None,
        price: float = None,
    ) -> Product:
        """Upsert product by internal code (type 04).
        
        Builds codes array from the provided code parameters.
        """
        try:
            existing = self.find_by_company_and_internal_code(company_id, internal_code)

            # Build codes via the canonical DTO; serialize once at the JSONB seam.
            code_dtos: list[ProductCodeDTO] = []
            if internal_code:
                code_dtos.append(ProductCodeDTO(code_type_id=ProductCodeType.INTERNAL, number=internal_code))
            if original_code:
                code_dtos.append(ProductCodeDTO(code_type_id=ProductCodeType.VENDOR, number=original_code))
            if client_article_code:
                code_dtos.append(ProductCodeDTO(code_type_id=ProductCodeType.BUYER, number=client_article_code))
            if code:
                code_dtos.append(ProductCodeDTO(code_type_id=ProductCodeType.MANUFACTURER, number=code))
            codes_array = [c.model_dump(exclude_none=True) for c in code_dtos]

            if existing:
                if description is not None:
                    existing.description = description
                if units_per_box is not None:
                    existing.units_per_box = units_per_box
                if price is not None and price > 0 and existing.price == 0:
                    existing.price = price
                # Update codes array
                existing.codes = codes_array
                self.session.flush()
                return existing

            category_id = self._ensure_default_category(company_id)

            product = Product(
                id=str(uuid.uuid4()),
                organization_id=company_id,
                name=description or internal_code,
                description=description or internal_code,
                price=price if price is not None else 0,
                category_id=category_id,
                status=ProductStatus.ACTIVE,
                units_per_box=units_per_box,
                codes=codes_array,
                # A product created here has no operator behind it — the
                # spreadsheet that produced it has no fiscal columns — so it
                # used to arrive with no unit of measure and no taxes at all.
                # An order line copies its product's taxes verbatim, so such a
                # product made every order built from it total to zero tax
                # (26 of them, before the TSR-236 backfill) and file with no
                # IVA. Seeding the defaults here fixes it at the source instead
                # of leaving a backfill as the only repair.
                unit_measure=DEFAULT_UNIT_MEASURE,
                taxes=[default_iva_row(None)],
            )
            self.session.add(product)
            self.session.flush()
            return product
        except SQLAlchemyError as e:
            logger.error(
                f"Error upserting product by internal code {internal_code} for company {company_id}: {e}",
                exc_info=True,
            )
            raise

    def save(self, product: Product) -> Product:
        try:
            product = self.session.merge(product)
            self.session.flush()
            return product
        except SQLAlchemyError as e:
            logger.error(f"Error saving product: {e}", exc_info=True)
            raise
