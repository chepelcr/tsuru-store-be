"""Backfill: recompute existing orders' line amounts with the current engine.

Why this exists
---------------
Orders captured before the fiscal detail reached imported lines carry flat
numbers copied straight off the customer's spreadsheet: a `discount` that is
frequently zero even when the order header totals one, a `tax` nobody derived,
and no `taxes` / `discounts` / `cabys` / `net_price` at all. Such an order
cannot be billed without inventing a rate at invoice time.

This walks the existing rows and brings them up to what `order_service` now
produces on import:

  1. lines missing their fiscal detail get it from the linked product (CABYS,
     net price, the configured taxes, the unit of measure and the rest of the
     document line) and from the order (the discount, as **07 Descuento
     Comercial**);
  2. an order whose lines all show a zero discount while the HEADER totals one
     has that discount allocated across the lines in proportion to their gross —
     the same rule the import applies;
  3. every line is then recomputed through `LineCalculator`, and the order
     totals are re-added from the lines.

A line that ends up with no structured detail — no product, or a product with no
taxes configured — is left exactly as it was. Inventing a tax rate is worse than
carrying the customer's own figure.

Usage
-----
    STAGE=dev AWS_PROFILE=<profile> AWS_REGION=us-east-1 \\
      python scripts/backfill_order_line_calculations.py --dry-run
    STAGE=dev AWS_PROFILE=<profile> AWS_REGION=us-east-1 \\
      python scripts/backfill_order_line_calculations.py --apply

    # narrow it down while checking the result
    ... --apply --organization <org-id> --document <document-number> --limit 10

`--dry-run` is the default and prints the before/after totals per order without
writing anything. Nothing is committed unless `--apply` is passed.
"""
from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal

sys.path.insert(0, ".")

from app.models.order import Order  # noqa: E402
from app.repositories.order_repository import OrderRepository  # noqa: E402
from app.repositories.product_repository import ProductRepository  # noqa: E402
from app.services.order_service import (  # noqa: E402
    _recompute_imported_line,
    _resum_order_totals,
    clear_derived_base_amounts,
    refill_line_fiscal_fields,
)

logger = logging.getLogger("backfill")


def backfill_order(order: Order, product_repo: ProductRepository) -> dict:
    """Bring one order's lines up to date. Returns a before/after summary.

    The repair itself lives in `order_service` — `clear_derived_base_amounts`
    and `refill_line_fiscal_fields` — and is the SAME code the Reprocess button
    runs. It used to be duplicated here, and the copies had drifted: this one
    quantized the header-discount allocation at 5 decimal places where the
    service rounds at 2, so a backfilled order's line discounts did not add back
    to its header at the precision order money is stored in.
    """
    before = {
        "discounts": float(order.discounts or 0),
        "taxes": float(order.taxes or 0),
        "grand_total": float(order.grand_total or 0),
    }

    clear_derived_base_amounts(order)
    repairs = refill_line_fiscal_fields(order)
    for line in (order.lines or []):
        _recompute_imported_line(line, line.product)
    _resum_order_totals(order)

    after = {
        "discounts": float(order.discounts or 0),
        "taxes": float(order.taxes or 0),
        "grand_total": float(order.grand_total or 0),
    }
    return {"before": before, "after": after, "repairs": repairs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="commit the changes")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--organization", help="limit to one organization id")
    parser.add_argument("--document", help="limit to one document number")
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    apply_changes = args.apply

    with OrderRepository() as repo:
        product_repo = ProductRepository.from_session(repo.session)

        query = repo.session.query(Order)
        if args.organization:
            query = query.filter(Order.company_id == args.organization)
        if args.document:
            query = query.filter(Order.document_number == args.document)
        query = query.order_by(Order.order_id)
        if args.limit:
            query = query.limit(args.limit)

        orders = query.all()
        logger.info(
            "%s %d order(s)%s",
            "Backfilling" if apply_changes else "Inspecting",
            len(orders),
            "" if apply_changes else " (dry run — nothing will be written)",
        )

        changed = 0
        for order in orders:
            try:
                summary = backfill_order(order, product_repo)
            except Exception as exc:  # one bad order must not stop the run
                logger.warning("  %s: FAILED — %s", order.document_number, exc)
                continue

            # A repair counts as a change even when the money lands on the same
            # figure: filling in a missing CABYS or unit of measure is exactly
            # what makes the order billable, and it moves no total.
            moved = summary["before"] != summary["after"] or bool(summary["repairs"])
            if moved:
                changed += 1
            logger.info(
                "  %-16s total %12.2f -> %12.2f   tax %10.2f -> %10.2f%s",
                order.document_number,
                summary["before"]["grand_total"],
                summary["after"]["grand_total"],
                summary["before"]["taxes"],
                summary["after"]["taxes"],
                "" if moved else "   (unchanged)",
            )
            for repair in summary["repairs"]:
                logger.info("      fiscal: %s", repair)

        if apply_changes:
            repo.session.commit()
            logger.info("Committed. %d order(s) changed.", changed)
        else:
            repo.session.rollback()
            logger.info("Dry run complete. %d order(s) WOULD change.", changed)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
