"""Product type enumeration.

The `products.type` column is the storefront catalog classification:

    - product:  a tangible good (the default)
    - service:  a service offering
    - program:  a structured program / course (storefront "programs" section)

``on_sale`` remains the price-discount mechanic and ``is_offer`` is the
storefront "Oferta" flag — both orthogonal to ``type``.

Hacienda classification is separate: CABYS owns the fiscal product type.
"""

from enum import Enum


class ProductType(str, Enum):
    """Canonical product kind values stored in ``products.type``."""

    PRODUCT = "product"
    SERVICE = "service"
    PROGRAM = "program"

    @classmethod
    def values(cls) -> list[str]:
        """Return all valid type string values."""
        return [t.value for t in cls]

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Check whether a string is a valid product type."""
        return value in cls.values()
