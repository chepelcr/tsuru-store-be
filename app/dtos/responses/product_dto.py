from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.dtos.responses.pagination_dto import PaginationResponse


class CategoryResponse(BaseModel):
    model_config = {"from_attributes": True}
    
    category_id: str = Field(...)
    name: Optional[str] = Field(None)


# ---------------------------------------------------------------------------
# Fiscal / Hacienda e-invoicing nested response models (output only)
# ---------------------------------------------------------------------------

class CabysResponse(BaseModel):
    """Aligned with the data-services CABYS catalog. cross-app-be reads only.

    `description` is the canonical Hacienda-supplied name; `product_type_id`
    and `tax_rate_id` are the data-services catalog references (Hacienda
    product type 4/5/6, plus a suggested IVA rate). All non-id/code fields
    are optional because data-services may insert rows before every field
    is populated (e.g. via the Hacienda search path).
    """

    model_config = {"from_attributes": True}

    id: str = Field(...)
    code: str = Field(...)
    description: Optional[str] = Field(None)
    product_type_id: Optional[int] = Field(None)
    tax_rate_id: Optional[int] = Field(None)
    country_code: Optional[str] = Field(None)


class ProductCodeResponse(BaseModel):
    model_config = {"from_attributes": True}

    code_type_id: str = Field(...)
    number: str = Field(...)


class ProductDiscountResponse(BaseModel):
    model_config = {"from_attributes": True}

    discount_type_id: str = Field(...)
    percentage: Optional[float] = Field(None)
    amount: Optional[float] = Field(None)  # backend-computed
    reason: Optional[str] = Field(None)
    is_amount: Optional[bool] = Field(None)


class TaxRateResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: Optional[str] = Field(None)
    percentage: float = Field(...)
    code: Optional[str] = Field(None)


class TaxFactorResponse(BaseModel):
    model_config = {"from_attributes": True}
    
    id: str = Field(...)
    factor: float = Field(...)


class TaxAmountResponse(BaseModel):
    model_config = {"from_attributes": True}
    
    id: str = Field(...)
    amount: float = Field(...)


class TaxSpecialFieldsResponse(BaseModel):
    model_config = {"from_attributes": True}
    
    quantity: Optional[float] = Field(None)
    percentage: Optional[float] = Field(None)
    proportion: Optional[float] = Field(None)
    volume_consumption: Optional[float] = Field(None)
    tax_amount: Optional[TaxAmountResponse] = Field(None)


class ProductTaxResponse(BaseModel):
    model_config = {"from_attributes": True}
    
    tax_type_id: str = Field(...)
    amount: Optional[float] = Field(None)  # backend-computed
    tax_rate: Optional[TaxRateResponse] = Field(None)
    tax_factor: Optional[TaxFactorResponse] = Field(None)
    other_tax_type: Optional[str] = Field(None)
    special_fields: Optional[TaxSpecialFieldsResponse] = Field(None)
    is_amount: Optional[bool] = Field(None)


# ---------------------------------------------------------------------------
# Main product response
# ---------------------------------------------------------------------------

class ProductResponse(BaseModel):
    product_id: str = Field(...)
    company_id: str = Field(...)
    name: Optional[str] = Field(None)
    description: Optional[str] = Field(None)
    units_per_box: Optional[int] = Field(None)
    price: Optional[float] = Field(None)
    image_url: Optional[str] = Field(None)
    category: Optional[CategoryResponse] = Field(None)

    # Inventory / catalogue fields
    status: int = Field(1)
    stock_quantity: int = Field(0)
    low_stock_threshold: int = Field(10)
    track_inventory: bool = Field(True)
    is_service: bool = Field(False)
    type: str = Field("product")
    on_sale: bool = Field(False)
    is_offer: bool = Field(False)
    original_price: Optional[float] = Field(None)
    discount: Optional[int] = Field(None)
    created_on: Optional[datetime] = Field(None)
    updated_on: Optional[datetime] = Field(None)

    # Fiscal / Hacienda e-invoicing fields
    cabys: Optional[CabysResponse] = Field(None)
    unit_measure: Optional[str] = Field(None)
    commercial_unit_measure: Optional[str] = Field(None)
    is_packaged: Optional[bool] = Field(None)
    quantity: Optional[float] = Field(None)
    unit_price: Optional[float] = Field(None)
    customs_part: Optional[str] = Field(None)
    codes: List[ProductCodeResponse] = Field(default_factory=list)
    discounts: List[ProductDiscountResponse] = Field(default_factory=list)
    taxes: List[ProductTaxResponse] = Field(default_factory=list)
    # backend-computed totals — never set by FE
    base_amount: Optional[float] = Field(None)
    sale_price: Optional[float] = Field(None)

    # Exemption block (Hacienda v4.4 Exoneracion) + factory VAT indicator.
    exemption_authorization_code: Optional[str] = Field(None)
    exempted_rate: Optional[float] = Field(None)
    exemption_amount: Optional[float] = Field(None)
    iva_collected_factory: Optional[str] = Field(None)
    factory_tax_charge_id: Optional[int] = Field(None)

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    data: List[ProductResponse]
    pagination: PaginationResponse
