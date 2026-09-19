from typing import Optional

from datetime import date

from pydantic import BaseModel, Field, ConfigDict

from .pagination_dto import PaginationResponse


class ConfirmationOrderSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    order_id: int = Field(..., description="Internal order identifier")
    document_number: str = Field(..., description="Order document number")
    delivery_date: Optional[date] = Field(
        None, description="Order delivery date (ISO `YYYY-MM-DD`)")
    deliver_to_code: Optional[str] = Field(None, description="Delivery destination code")
    deliver_to_name: Optional[str] = Field(None, description="Delivery destination name")
    order_status: Optional[str] = Field(None, description="Order status")


class ConfirmationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    confirmation_id: int = Field(..., description="Internal confirmation identifier")
    company_id: str = Field(..., description="Company identifier")
    confirmation_number: str = Field(..., description="User-provided confirmation number")
    delivery_date: Optional[date] = Field(
        None, description="Delivery date (ISO `YYYY-MM-DD`)")
    deliver_to_code: Optional[str] = Field(None, description="Delivery destination code")
    deliver_to_name: Optional[str] = Field(None, description="Delivery destination name")
    confirmation_status: Optional[str] = Field(None, description="Confirmation status (pending, processing, shipped, delivered, cancelled)")
    orders: list[ConfirmationOrderSummary] = Field(
        default_factory=list, description="Orders linked to this confirmation"
    )


class ConfirmationListResponse(BaseModel):
    data: list[ConfirmationResponse] = Field(default_factory=list)
    pagination: PaginationResponse
