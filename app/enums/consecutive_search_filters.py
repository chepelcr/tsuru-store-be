from __future__ import annotations

from enum import Enum
from typing import Optional, Set


ENTITY_CONSECUTIVE = "Consecutive"
ENTITY_ALL = {ENTITY_CONSECUTIVE}


class ConsecutiveSearchFilters(Enum):
    """`search=` fields for GET /consecutives.

    The join fields resolve through the view-only relationships on
    `Consecutive` (`terminal`, `terminal.branch`, `document_type`); the
    repository always joins those tables, so filtering on them is safe.

    Mirrored by the POS enum `ConsecutiveSearchFilter`
    (fe/pos-system/src/lib/consecutiveSearchBuilder.ts) — keep them in sync.
    """

    TERMINAL_ID = ("terminal_id", "terminal_id", False, None, True, ENTITY_ALL, False, False, True, False)
    DOCUMENT_TYPE_ID = ("document_type_id", "document_type_id", False, None, True, ENTITY_ALL, False, False, True, False)
    CURRENT_NUMBER = ("current_number", "current_number", False, None, True, ENTITY_ALL, False, True, True, False)
    UPDATED_ON = ("updated_on", "updated_on", False, None, True, ENTITY_ALL, False, True, True, False)
    # Branch: terminals carry branch_id, so one join is enough.
    BRANCH_ID = ("branch_id", "branch_id", True, "terminal", True, ENTITY_ALL, False, False, False, False)
    BRANCH_CODE = ("code", "branch_code", True, "terminal.branch", True, ENTITY_ALL, False, False, False, False)
    TERMINAL_CODE = ("code", "terminal_code", True, "terminal", True, ENTITY_ALL, False, False, False, False)
    DOCUMENT_TYPE_CODE = ("code", "document_type_code", True, "document_type", True, ENTITY_ALL, False, False, False, False)
    ORDER_BY = (None, "order_by", False, None, False, ENTITY_ALL, False, False, False, False)

    def __init__(self, entity_field, json_field, is_join_field, join_field, is_controller_filter,
                 applicable_entities=None, allows_like=False, allows_between=False, sortable=False, always_like=False):
        self._entity_field = entity_field
        self._json_field = json_field
        self._is_join_field = is_join_field
        self._join_field = join_field
        self._is_controller_filter = is_controller_filter
        self._applicable_entities = applicable_entities or ENTITY_ALL
        self._allows_like = allows_like
        self._allows_between = allows_between
        self._sortable = sortable
        self._always_like = always_like

    @property
    def entity_field(self): return self._entity_field
    @property
    def json_field(self): return self._json_field
    @property
    def is_join_field(self): return self._is_join_field
    @property
    def join_field(self): return self._join_field
    @property
    def is_controller_filter(self): return self._is_controller_filter
    @property
    def allows_like(self): return self._allows_like
    @property
    def allows_between(self): return self._allows_between
    @property
    def sortable(self): return self._sortable
    @property
    def always_like(self): return self._always_like

    @classmethod
    def get_filter_by_json_field(cls, json_field):
        for f in cls:
            if f.json_field and f.json_field == json_field:
                return f
        return None
