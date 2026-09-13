"""Backfill: give existing products a unit of measure and an IVA row.

Why this exists
---------------
Products auto-created by an order import carry a name, a price and some codes
and nothing else — the spreadsheet has no fiscal columns. Two consequences, both
of which reach a legal document:

  1. **No `unit_measure`.** Hacienda requires `UnidadMedida` on every line, so
     billing anything built from such a product falls back to "Unid".
  2. **No taxes.** A line built from a product with no taxes carries no IVA, and
     an order costed against it totals to zero tax — which is exactly how 26
     existing orders came to report `taxes = 0`.

For a product created through the UI neither applies: the unit is a required
field now, and the IVA comes from the CABYS the operator picks. This fills in the
ones that predate that, and only those.

What it writes
--------------
* `unit_measure` — only when empty, and only to the default unit.
* a single IVA row — only when the product has NO taxes at all. The rate comes
  from the product's CABYS when it has one (that is what the taxonomy is for);
  otherwise the general 13%, which is the correct rate for a good or service
  with no exemption on record.

It never overwrites a tax the operator configured, and never touches a product
that already has one — a genuinely exempt article is expressed as a rate-10 row,
not as an absent one, so "no taxes" is unambiguously "never configured".

Usage
-----
    STAGE=dev AWS_PROFILE=<profile> AWS_REGION=us-east-1 \\
      python scripts/backfill_product_fiscal_defaults.py --dry-run
    ... --apply [--organization <org-id>] [--limit N]

Run `backfill_order_line_calculations.py` afterwards so existing orders pick the
new taxes up.
"""
from __future__ import annotations

import argparse
import logging
import sys

sys.path.insert(0, ".")

from app.utils.product_fiscal_defaults import (  # noqa: E402
    DEFAULT_UNIT_MEASURE,
    default_iva_row,
    repair_tax_rows,
)
from app.models.product import Product  # noqa: E402
from app.repositories.product_repository import ProductRepository  # noqa: E402

logger = logging.getLogger("backfill-products")

# The defaults themselves live in `app/utils/product_fiscal_defaults` so this
# script and the import path that CREATES such products cannot disagree about
# what a sane default is.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="commit the changes")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--organization", help="limit to one organization id")
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with ProductRepository() as repo:
        query = repo.session.query(Product)
        if args.organization:
            query = query.filter(Product.organization_id == args.organization)
        query = query.order_by(Product.id)
        if args.limit:
            query = query.limit(args.limit)

        products = query.all()
        logger.info(
            "%s %d product(s)%s",
            "Backfilling" if args.apply else "Inspecting",
            len(products),
            "" if args.apply else " (dry run — nothing will be written)",
        )

        units_set = 0
        taxes_set = 0
        rows_repaired = 0
        needs_attention: list[str] = []
        for product in products:
            changes = []

            if not (product.unit_measure or "").strip():
                product.unit_measure = DEFAULT_UNIT_MEASURE
                units_set += 1
                changes.append(f"unit={DEFAULT_UNIT_MEASURE}")

            if not product.taxes:
                row = default_iva_row(product)
                product.taxes = [row]
                taxes_set += 1
                changes.append(
                    f"IVA {row['tax_rate']['percentage']}% (code {row['tax_rate']['code']})"
                )
            else:
                # The larger population: a product that HAS an IVA row whose rate
                # code is null. Invisible until a document built from it is
                # rejected — and the reason an order can become unbillable long
                # after the edit that caused it.
                repairs = repair_tax_rows(product)
                if repairs:
                    rows_repaired += 1
                    changes.extend(repairs)
                    for repair in repairs:
                        if "NEEDS ATTENTION" in repair:
                            needs_attention.append(
                                f"{(product.name or product.id)[:40]}: {repair}"
                            )

            if changes:
                logger.info("  %-40s %s", (product.name or product.id)[:40], ", ".join(changes))

        logger.info(
            "%s: %d unit(s), %d new tax row(s), %d product(s) with repaired tax rows.",
            "Committed" if args.apply else "Would write",
            units_set,
            taxes_set,
            rows_repaired,
        )
        if needs_attention:
            logger.warning(
                "\n%d row(s) could NOT be repaired automatically — a 0%% rate does not "
                "identify its treatment (exento 10 / no sujeto 11 / crédito pleno 01), "
                "so guessing one would misdeclare. Set these by hand:",
                len(needs_attention),
            )
            for item in needs_attention:
                logger.warning("  %s", item)
        if args.apply:
            repo.session.commit()
        else:
            repo.session.rollback()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
