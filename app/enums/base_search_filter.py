"""
Base search filter class for all entity-specific search filter enums.

This module provides a common base class that all search filter enums
should inherit from, ensuring consistent behavior and interface.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Set


class BaseSearchFilter(Enum):
    """
    Base class for all search filter enums.
    
    All entity-specific search filter enums (ProductSearchFilters, 
    ClientSearchFilters, etc.) should inherit from this class.
    
    Each enum value should contain:
    - entity_field: The field name in the database entity
    - json_field: The field name in the JSON request
    - is_join_field: Whether this field requires a join
    - join_field: The relationship name for joins (if applicable)
    - is_controller_filter: Whether this is a searchable filter in controllers
    - applicable_entities: Set of entity names this filter can be applied to
    - allows_like: Whether LIKE operations are allowed
    - allows_between: Whether BETWEEN operations are allowed
    - sortable: Whether this field can be used for sorting
    - always_like: Whether to always use LIKE (even without wildcards)
    """

    def __init__(
        self,
        entity_field: Optional[str],
        json_field: Optional[str],
        is_join_field: bool,
        join_field: Optional[str],
        is_controller_filter: bool,
        applicable_entities: Optional[Set[str]] = None,
        allows_like: bool = False,
        allows_between: bool = False,
        sortable: bool = False,
        always_like: bool = False,
    ) -> None:
        """
        Initialize the search filter.

        Args:
            entity_field: The field name in the database entity
            json_field: The field name in the JSON request
            is_join_field: Whether this field requires a join
            join_field: The relationship name for joins
            is_controller_filter: Whether searchable in controllers
            applicable_entities: Set of entity names this filter applies to
            allows_like: Whether LIKE operations are allowed
            allows_between: Whether BETWEEN operations are allowed
            sortable: Whether this field can be used for sorting
            always_like: Whether to always use LIKE (even without wildcards)
        """
        self._entity_field = entity_field
        self._json_field = json_field
        self._is_join_field = is_join_field
        self._join_field = join_field
        self._is_controller_filter = is_controller_filter
        self._applicable_entities = applicable_entities or set()
        self._allows_like = allows_like
        self._allows_between = allows_between
        self._sortable = sortable
        self._always_like = always_like

    @property
    def entity_field(self) -> Optional[str]:
        """Get the entity field name."""
        return self._entity_field

    @property
    def json_field(self) -> Optional[str]:
        """Get the JSON field name."""
        return self._json_field

    @property
    def is_join_field(self) -> bool:
        """Check if this filter requires a join."""
        return self._is_join_field

    @property
    def join_field(self) -> Optional[str]:
        """Get the join field/relationship name."""
        return self._join_field

    @property
    def is_controller_filter(self) -> bool:
        """Check if this is a controller-level searchable filter."""
        return self._is_controller_filter

    @property
    def allows_like(self) -> bool:
        """Check if LIKE operations are allowed."""
        return self._allows_like

    @property
    def allows_between(self) -> bool:
        """Check if BETWEEN operations are allowed."""
        return self._allows_between

    @property
    def sortable(self) -> bool:
        """Check if this field can be used for sorting."""
        return self._sortable

    @property
    def always_like(self) -> bool:
        """Check if this field should always use LIKE (even without wildcards)."""
        return self._always_like

    @classmethod
    def get_filter_by_json_field(cls, json_field: str) -> Optional[BaseSearchFilter]:
        """
        Get a filter enum member by its JSON field name.

        Args:
            json_field: The JSON field name to search for

        Returns:
            The matching filter member, or None if not found

        Example:
            >>> ProductSearchFilters.get_filter_by_json_field("name")
            <ProductSearchFilters.NAME: ...>
        """
        # Wire fields are snake_case only; a camelCase name does not resolve.
        for filter_enum in cls:
            if filter_enum.json_field and filter_enum.json_field == json_field:
                return filter_enum
        return None
