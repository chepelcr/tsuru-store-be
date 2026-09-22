from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Type

from sqlalchemy import and_, or_, asc, desc
from sqlalchemy.orm import InstrumentedAttribute

from app.utils.order_dates import as_date
from app.enums.base_search_filter import BaseSearchFilter
from app.enums.search_operations import (
    SearchOperations,
    SIMPLE_OPERATION_SET,
    ZERO_OR_MORE_REGEX,
    BETWEEN_RANGE_SEPARATOR,
    LEFT_PARENTHESIS,
    RIGHT_PARENTHESIS,
)


@dataclass
class SearchCriteria:
    field: str
    operation: SearchOperations
    value: Any
    is_join_field: bool = False
    join_field: Optional[str] = None
    entity_field: Optional[str] = None
    search_filter: Optional[BaseSearchFilter] = None
    filter_enum_class: Type[BaseSearchFilter] = None

    def __post_init__(self) -> None:
        # Use the provided filter enum class, or skip if not provided
        if self.filter_enum_class:
            search_filter = self.filter_enum_class.get_filter_by_json_field(self.field)
            if search_filter:
                self.search_filter = search_filter
                self.is_join_field = search_filter.is_join_field
                self.join_field = search_filter.join_field
                self.entity_field = search_filter.entity_field
            else:
                self.entity_field = self.field
        else:
            self.entity_field = self.field


class SearchUtils:
    _ORDER_BY_PATTERN = re.compile(r"orderBy([<>])([a-zA-Z_][a-zA-Z0-9_]*)")

    # Fields valid for orderBy (only direct columns, not join fields)
    SORTABLE_FIELDS = {
        "documentNumber", "document_number",
        "deliveryDate", "delivery_date",
        "creationDate", "creation_date",
        "orderStatus", "order_status",
        "createdOn", "created_on",
        "updatedOn", "updated_on",
    }

    SORTABLE_FIELD_MAP = {
        "documentNumber": "document_number",
        "deliveryDate": "delivery_date",
        "creationDate": "creation_date",
        "orderStatus": "order_status",
        "createdOn": "created_on",
        "updatedOn": "updated_on",
    }

    @classmethod
    def parse_search_filter(cls, search: str, entity_class: Type, filter_enum_class: Type[BaseSearchFilter] = None) -> tuple:
        if not search or not search.strip():
            return [], None

        order_by = None
        tokens = cls._split_tokens(search)

        general_filters = []
        grouped_filters = []

        for token in tokens:
            token = token.strip()
            if not token:
                continue

            if token.startswith("orderBy"):
                order_result = cls._parse_order_by(token, entity_class, filter_enum_class)
                if order_result:
                    order_by = order_result
                continue

            if token.startswith(LEFT_PARENTHESIS) and token.endswith(RIGHT_PARENTHESIS):
                group_content = token[1:-1]
                group_tokens = cls._split_tokens(group_content)
                or_filters = []
                for gt in group_tokens:
                    gt = gt.strip()
                    if not gt:
                        continue
                    criteria = cls._parse_criteria(gt, filter_enum_class)
                    if criteria:
                        f = cls._build_filter(criteria, entity_class)
                        if f is not None:
                            or_filters.append(f)
                if or_filters:
                    grouped_filters.append(or_(*or_filters) if len(or_filters) > 1 else or_filters[0])
            else:
                criteria = cls._parse_criteria(token, filter_enum_class)
                if criteria:
                    f = cls._build_filter(criteria, entity_class)
                    if f is not None:
                        general_filters.append(f)

        all_filters = general_filters + grouped_filters
        if all_filters:
            if len(all_filters) == 1:
                return [all_filters[0]], order_by
            return [and_(*all_filters)], order_by

        return [], order_by

    @classmethod
    def _split_tokens(cls, search_string: str) -> list[str]:
        tokens = []
        current_token = ""
        paren_depth = 0

        for char in search_string:
            if char == LEFT_PARENTHESIS:
                paren_depth += 1
                current_token += char
            elif char == RIGHT_PARENTHESIS:
                paren_depth -= 1
                current_token += char
            elif char == "," and paren_depth == 0:
                if current_token.strip():
                    tokens.append(current_token.strip())
                current_token = ""
            else:
                current_token += char

        if current_token.strip():
            tokens.append(current_token.strip())

        return tokens

    @classmethod
    def _parse_criteria(cls, token: str, filter_enum_class: Type[BaseSearchFilter] = None) -> Optional[SearchCriteria]:
        if not token:
            return None

        for op_char in SIMPLE_OPERATION_SET:
            if op_char in token:
                parts = token.split(op_char, 1)
                if len(parts) == 2:
                    field = parts[0].strip()
                    value = parts[1].strip()
                    operation = SearchOperations.get_simple_operation(op_char)
                    if operation:
                        # Check for BETWEEN range separator in value
                        if BETWEEN_RANGE_SEPARATOR in value:
                            if filter_enum_class:
                                search_filter = filter_enum_class.get_filter_by_json_field(field)
                                if search_filter and search_filter.allows_between:
                                    if operation == SearchOperations.NEGATION:
                                        operation = SearchOperations.NEGATION_BETWEEN
                                    else:
                                        operation = SearchOperations.BETWEEN
                                    return SearchCriteria(
                                        field=field,
                                        operation=operation,
                                        value=value,
                                        filter_enum_class=filter_enum_class,
                                    )

                        operation, value = cls._process_wildcard_value(operation, value)
                        converted_value = cls._convert_value(value)
                        return SearchCriteria(
                            field=field,
                            operation=operation,
                            value=converted_value,
                            filter_enum_class=filter_enum_class,
                        )
        return None

    @classmethod
    def _process_wildcard_value(cls, operation: SearchOperations, value: str) -> tuple:
        if ZERO_OR_MORE_REGEX not in value:
            return operation, value

        # Value contains wildcards - convert to LIKE pattern
        starts_with_wildcard = value.startswith(ZERO_OR_MORE_REGEX)
        ends_with_wildcard = value.endswith(ZERO_OR_MORE_REGEX)

        # Replace wildcards with SQL LIKE wildcards
        processed_value = value.replace(ZERO_OR_MORE_REGEX, "%")

        if starts_with_wildcard and ends_with_wildcard:
            return SearchOperations.CONTAINS, processed_value
        elif starts_with_wildcard:
            return SearchOperations.ENDS_WITH, processed_value
        elif ends_with_wildcard:
            return SearchOperations.STARTS_WITH, processed_value

        # Middle wildcards - use CONTAINS
        return SearchOperations.CONTAINS, processed_value

    @classmethod
    def _convert_value(cls, value: str) -> Any:
        if not value:
            return value
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
        # A leading zero means a code, not a number: Hacienda document-type
        # "01" must not become 1 and then match nothing as the string "1".
        # Integer columns still get their int back in `_apply_operation`.
        if len(value) > 1 and value.startswith("0") and value.isdigit():
            return value
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value

    @classmethod
    def _build_filter(cls, criteria: SearchCriteria, entity_class: Type):
        if criteria.is_join_field and criteria.join_field:
            # Handle nested joins (e.g., "terminal.branch")
            join_parts = criteria.join_field.split(".")
            current_class = entity_class

            for join_name in join_parts:
                if not hasattr(current_class, join_name):
                    return None
                relationship_attr = getattr(current_class, join_name)
                # Get the related class from the relationship
                try:
                    # Try newer SQLAlchemy API first
                    if hasattr(relationship_attr.property, 'entity'):
                        current_class = relationship_attr.property.entity.class_
                    elif hasattr(relationship_attr.property, 'mapper'):
                        current_class = relationship_attr.property.mapper.class_
                    else:
                        # Fallback: try to get from the relationship itself
                        current_class = relationship_attr.property.argument
                        if callable(current_class):
                            current_class = current_class()
                except AttributeError:
                    return None

            # current_class is now the final related class after all joins
            related_class = current_class

            # Get the field from the related class
            field_name = criteria.entity_field or criteria.field
            if not hasattr(related_class, field_name):
                return None

            target_column = getattr(related_class, field_name)
            return cls._apply_operation(target_column, criteria.operation, criteria.value, criteria.field, criteria.search_filter)

        field_name = criteria.entity_field or criteria.field
        
        # Special handling for JSONB codes field in Product
        if field_name == "codes" and criteria.field == "code":
            return cls._build_codes_filter(entity_class, criteria.operation, criteria.value)
        
        if not hasattr(entity_class, field_name):
            return None
        column: InstrumentedAttribute = getattr(entity_class, field_name)
        return cls._apply_operation(column, criteria.operation, criteria.value, criteria.field, criteria.search_filter)

    @classmethod
    def _build_codes_filter(cls, entity_class: Type, operation: SearchOperations, value: Any):
        """Build filter for JSONB codes array with format: code:01-123415 or code:123415.

        The containment probe is built via ProductCodeDTO so the JSONB key
        shape can't drift from the rest of the codebase. The number-only
        path still uses a bare {"number": ...} since DTO would require a
        code_type_id we don't have.
        """
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB
        from app.dtos.requests.product_request_dto import ProductCodeDTO

        if not hasattr(entity_class, "codes"):
            return None

        codes_column = getattr(entity_class, "codes")
        value_str = str(value)

        if "-" in value_str:
            code_type, code_number = (p.strip() for p in value_str.split("-", 1))
            probe = ProductCodeDTO(
                code_type_id=code_type, number=code_number
            ).model_dump(exclude_none=True)
        else:
            # No code type specified — partial probe matches any code type
            # whose number equals value_str (JSONB containment).
            probe = {"number": value_str}

        if operation == SearchOperations.EQUALITY:
            return codes_column.op("@>")(cast([probe], JSONB))
        if operation == SearchOperations.NEGATION:
            return ~codes_column.op("@>")(cast([probe], JSONB))
        return None

    @staticmethod
    def _is_date_column(column) -> bool:
        """True only for a bare DATE.

        Exact match, not a prefix: SQLAlchemy renders `DateTime` as "DATETIME",
        which starts with "DATE" — so a prefix test swept timestamp columns in
        with the date ones and would have coerced `created_on` filters to whole
        days, silently dropping the time a caller asked to filter on.
        """
        return str(getattr(column, "type", "")).strip().upper() == "DATE"

    @staticmethod
    def _coerce_date_value(value: Any, operation: SearchOperations) -> Any:
        """A single filter value as a `date`.

        Ranges are NOT handled here — they are still one `a~b` string at this
        point, and the operator branches below split them. Returning a
        reformatted string for a range is what produced
        `operator does not exist: date >= character varying`: the endpoints were
        bound as text against a date column, which Postgres refuses outright.
        """
        if value is None or operation in (
            SearchOperations.BETWEEN, SearchOperations.NEGATION_BETWEEN
        ):
            return value
        parsed = as_date(value)
        return parsed if parsed else value

    @classmethod
    def _range_bounds(cls, column, parts):
        """The two ends of an `a~b` range, typed for the column.

        For a DATE column both ends become `date` objects, read day-first or ISO
        by `as_date` — never handed to Postgres as text, which would either be
        refused (`date >= character varying`) or, worse, cast under this server's
        MDY DateStyle and silently shift the month.
        """
        low, high = parts[0].strip(), parts[1].strip()
        if not cls._is_date_column(column):
            return low, high
        low_date, high_date = as_date(low), as_date(high)
        # Both or neither: a half-converted range compares a date against text.
        if low_date and high_date:
            return low_date, high_date
        return low, high

    @classmethod
    def _apply_operation(cls, column, operation: SearchOperations, value: Any, field_name: Optional[str] = None, search_filter = None):
        # Handle type conversions based on column type
        try:
            col_type = str(column.type)
            
            # Handle VARCHAR/TEXT columns - ensure value is string
            if "VARCHAR" in col_type.upper() or "TEXT" in col_type.upper() or "CHAR" in col_type.upper():
                if value is not None and operation not in (SearchOperations.BETWEEN, SearchOperations.NEGATION_BETWEEN):
                    value = str(value)
            
            # Handle INTEGER columns - ensure value is integer (no boolean conversion for status)
            elif "INTEGER" in col_type.upper():
                if isinstance(value, str) and value.isdigit():
                    value = int(value)
                elif isinstance(value, bool):
                    # Convert boolean to integer for backward compatibility
                    value = 1 if value else 2

            # DATE columns — parse the value ourselves rather than letting
            # Postgres cast it.
            #
            # `deliveryDate` and `creationDate` used to be VARCHAR, so a range
            # was a raw STRING comparison: day-first lexicographic, which put
            # 02/12/2025 before 03/01/2025 and never matched an ISO-dated manual
            # order at all. Now the column is a real date, and the remaining trap
            # is the cast: this server's DateStyle is MDY, so '02/03/2026'::date
            # is 3 February, not 2 March. `as_date` reads day-first explicitly,
            # and accepts ISO too, so a client sending either is understood.
            elif cls._is_date_column(column):
                value = cls._coerce_date_value(value, operation)
        except Exception:
            pass

        # Check if field has always_like property set to True
        always_like = False
        if search_filter and hasattr(search_filter, 'always_like'):
            always_like = search_filter.always_like

        # For always_like fields, convert EQUALITY to case-insensitive LIKE
        if operation == SearchOperations.EQUALITY and always_like:
            return column.ilike(f"%{value}%")

        if operation == SearchOperations.NEGATION and always_like:
            return ~column.ilike(f"%{value}%")

        if operation == SearchOperations.EQUALITY:
            return column == value
        elif operation == SearchOperations.NEGATION:
            return column != value
        elif operation == SearchOperations.GREATER_THAN:
            return column > value
        elif operation == SearchOperations.LESS_THAN:
            return column < value
        elif operation == SearchOperations.LIKE:
            return column.ilike(f"%{value}%")
        elif operation == SearchOperations.STARTS_WITH:
            # Value already has % from wildcard processing
            if isinstance(value, str) and "%" in value:
                return column.ilike(value)
            return column.ilike(f"{value}%")
        elif operation == SearchOperations.ENDS_WITH:
            # Value already has % from wildcard processing
            if isinstance(value, str) and "%" in value:
                return column.ilike(value)
            return column.ilike(f"%{value}")
        elif operation == SearchOperations.CONTAINS:
            # Value already has % from wildcard processing
            if isinstance(value, str) and "%" in value:
                return column.ilike(value)
            return column.ilike(f"%{value}%")
        elif operation == SearchOperations.BETWEEN:
            if isinstance(value, str) and BETWEEN_RANGE_SEPARATOR in value:
                parts = value.split(BETWEEN_RANGE_SEPARATOR)
                if len(parts) == 2:
                    min_val, max_val = cls._range_bounds(column, parts)
                    return and_(column >= min_val, column <= max_val)
            return column == cls._coerce_date_value(value, operation) \
                if cls._is_date_column(column) else column == value
        elif operation == SearchOperations.NEGATION_BETWEEN:
            if isinstance(value, str) and BETWEEN_RANGE_SEPARATOR in value:
                parts = value.split(BETWEEN_RANGE_SEPARATOR)
                if len(parts) == 2:
                    min_val, max_val = cls._range_bounds(column, parts)
                    return or_(column < min_val, column > max_val)
            return column != value
        else:
            return column == value

    @classmethod
    def _parse_order_by(cls, token: str, entity_class: Type, filter_enum_class: Type[BaseSearchFilter] = None):
        match = cls._ORDER_BY_PATTERN.match(token)
        if not match:
            return None

        direction_char = match.group(1)
        field_name = match.group(2)

        # Check if field exists in the filter enum
        if filter_enum_class:
            search_filter = filter_enum_class.get_filter_by_json_field(field_name)
            
            # If in filter enum, check if it's sortable
            if search_filter:
                if not hasattr(search_filter, 'sortable') or not search_filter.sortable:
                    raise ValueError(f"Cannot sort by field: {field_name}")
                entity_field_name = search_filter.entity_field
            # Otherwise check global sortable fields (for backward compatibility)
            elif field_name in cls.SORTABLE_FIELDS:
                entity_field_name = cls.SORTABLE_FIELD_MAP.get(field_name, field_name)
            else:
                raise ValueError(f"Cannot sort by field: {field_name}")
        else:
            # No filter enum provided, use global sortable fields
            if field_name in cls.SORTABLE_FIELDS:
                entity_field_name = cls.SORTABLE_FIELD_MAP.get(field_name, field_name)
            else:
                raise ValueError(f"Cannot sort by field: {field_name}")

        # Check if the entity has this field
        if not hasattr(entity_class, entity_field_name):
            raise ValueError(f"Cannot sort by field: {field_name} (entity field: {entity_field_name} not found)")

        column = getattr(entity_class, entity_field_name)
        if direction_char == ">":
            return asc(column), "ASC"
        else:
            return desc(column), "DESC"
