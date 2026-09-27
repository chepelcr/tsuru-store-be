from __future__ import annotations

from typing import Set

from app.enums.base_search_filter import BaseSearchFilter


ENTITY_ORDER = "Order"
ENTITY_ALL = {ENTITY_ORDER}


class SearchFilters(BaseSearchFilter):
    """
    Search filters for Order entity.

    Format: (entity_field, json_field, is_join, join_field, is_controller, entities, allows_like, allows_between, sortable, always_like)
    """

    DOCUMENT_NUMBER = ("document_number", "document_number", False, None, True, ENTITY_ALL, True, False, True, True)
    CLIENT_NAME = ("client", "client_name", True, "client_name", True, ENTITY_ALL, True, False, False, True)
    SUPPLIER_NAME = ("organization", "supplier_name", True, "name", True, ENTITY_ALL, True, False, False, True)
    DELIVERY_DATE = ("delivery_date", "delivery_date", False, None, True, ENTITY_ALL, False, True, True, False)
    CREATION_DATE = ("creation_date", "creation_date", False, None, True, ENTITY_ALL, False, True, True, False)
    ORDER_STATUS = ("order_status", "order_status", False, None, True, ENTITY_ALL, False, False, True, False)
    DELIVER_TO_CODE = ("deliver_to_store", "deliver_to_code", True, "store_code", True, ENTITY_ALL, False, False, False, False)
    DELIVER_TO_NAME = ("deliver_to_store", "deliver_to_name", True, "store_name", True, ENTITY_ALL, True, False, False, True)
    CONFIRMATION_NUMBER = ("confirmation_number", "confirmation_number", False, None, True, ENTITY_ALL, True, False, True, True)
    CREATED_ON = ("created_on", "created_on", False, None, True, ENTITY_ALL, False, False, True, False)
    UPDATED_ON = ("updated_on", "updated_on", False, None, True, ENTITY_ALL, False, False, True, False)
    ORDER_BY = (None, "order_by", False, None, False, ENTITY_ALL, False, False, False, False)
