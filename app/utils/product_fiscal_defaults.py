"""The fiscal defaults a product must have to be billable.

A product created through the UI gets these from the operator: the unit of
measure is a required field and the IVA comes from the CABYS they pick. A product
created by an **order import** gets neither, because the customer's spreadsheet
has no fiscal columns — and the consequences both reach a legal document:

  1. **No `unit_measure`.** Hacienda requires `UnidadMedida` on every line, so an
     invoice built from such a product falls back to "Unid", wrong for anything
     sold by weight or volume.
  2. **No taxes.** A line built from a taxless product carries no IVA at all, and
     the order costed against it totals to zero tax. That is exactly how 26
     existing orders came to report `taxes = 0`.

Defined here, once, so the import path that CREATES such products and the
backfill that repairs the ones already in the database cannot disagree about what
a sane default is.
"""

from __future__ import annotations

from app.enums.hacienda_codes import TaxRateCode, TaxType

#: Hacienda's general IVA bracket — the right answer for a good or service with
#: no exemption on record.
GENERAL_RATE_CODE = TaxRateCode.GENERAL_13.value
GENERAL_RATE_PERCENTAGE = 13.0

#: `UnidadMedida` for a discrete unit. The fallback when nothing better is known,
#: but recorded explicitly on the product rather than guessed at invoice time.
DEFAULT_UNIT_MEASURE = "Unid"


def default_iva_row(product) -> dict:
    """The IVA row a product should carry when it has none.

    Prefers the rate on the product's CABYS: that taxonomy exists precisely to
    say which rate applies, so a reduced or exempt article gets its real rate
    rather than the general one. Falls back to 13% when there is no CABYS, which
    is the case for every import-created product.

    The rate CODE always travels with the percentage. The percentage alone does
    not identify the treatment — exento (10), no sujeto (11) and crédito pleno
    (01) are all "0%" — and a tax stored without the code is rejected downstream
    with `tax.rate_code is required when tax.code='01'`, which is how a product
    saved without it made every pedido built from it unbillable.
    """
    rate = getattr(product, "cabys", None)
    rate = rate.tax_rate if rate is not None else None

    percentage = (
        float(rate.percentage)
        if rate is not None and rate.percentage is not None
        else GENERAL_RATE_PERCENTAGE
    )
    code = (rate.code if rate is not None and rate.code else None) or GENERAL_RATE_CODE

    return {
        "tax_type_id": TaxType.IVA.value,
        "tax_rate": {
            # `id` carries the Hacienda rate CODE, not the data-services row id.
            # The code identifies the treatment and is what the document
            # carries; the row id is environment-specific and a reseed can
            # renumber it. `_normalize_tax_row` has always read this field as
            # the rate code, so writing a row id here made the two disagree.
            "id": code,
            "percentage": percentage,
            "code": code,
        },
    }


#: Tax codes whose percentage is derived from the rate CODE rather than from a
#: supplied rate, and which therefore cannot be filed without one.
IVA_FAMILY_TAX_CODES = frozenset(
    {TaxType.IVA.value, TaxType.IVACE.value, TaxType.IVARBU.value}
)


def repair_tax_rows(product) -> list[str]:
    """Fill in what a product's EXISTING tax rows are missing.

    `default_iva_row` only helps a product with no taxes at all. The larger
    population is products that DO have an IVA row whose `tax_rate.code` is null
    — written by a client that sent the percentage and not the code — and those
    are invisible until a document built from them is rejected with
    `tax.rate_code is required when tax.code='01'`.

    Two repairs, both conservative:

      * **the missing rate code**, derived from the percentage the row already
        carries. The mapping is one-way safe everywhere except 0%: exento (10),
        no sujeto (11) and crédito pleno (01) are all "0%", so a 0% row is left
        alone and reported rather than guessed — picking one would put a wrong
        tax treatment on a legal document.
      * **the missing percentage**, when a row has a code and no rate.

    Never overwrites a populated value, and never touches a non-IVA tax: only the
    IVA family derives its rate from a code.

    Returns a description of each change, so a dry run can be read.
    """
    rows = getattr(product, "taxes", None)
    if not rows:
        return []

    # Rate code → percentage, from the Hacienda Nota 8.1 table. The transitional
    # brackets (05/06/07) are present because a stored row may legitimately carry
    # one on a credit note.
    percentage_by_code = {
        "01": 0.0, "02": 1.0, "03": 2.0, "04": 4.0, "05": 0.0,
        "06": 4.0, "07": 8.0, "08": 13.0, "09": 0.5, "10": 0.0, "11": 0.0,
    }
    # The reverse, restricted to the percentages only ONE code can mean. 0% is
    # absent deliberately, and 4%/8% resolve to the ordinary brackets because the
    # transitional ones are NC/ND-only and unreachable on a product line.
    code_by_percentage = {13.0: "08", 4.0: "04", 2.0: "03", 1.0: "02", 0.5: "09"}

    changes: list[str] = []
    repaired = []
    for row in rows:
        row = dict(row)
        code = str(row.get("tax_type_id") or "")
        if code in IVA_FAMILY_TAX_CODES:
            rate = row.get("tax_rate") or {}
            rate = dict(rate)
            existing_code = (rate.get("code") or "").strip()
            percentage = rate.get("percentage")

            # `id` must be the rate CODE. Rows written earlier hold a
            # data-services row id ("8") where the code ("08") belongs, and the
            # product form bound its rate selector to that id — so a row with a
            # code but no id, which is most of them, rendered as unselected.
            previous_id = rate.get("id")
            if existing_code and str(previous_id or "") != existing_code:
                rate["id"] = existing_code
                changes.append(
                    f"tax {code}: rate id <- {existing_code} (was {previous_id!r})"
                )

            if not existing_code and percentage is not None:
                derived = code_by_percentage.get(float(percentage))
                if derived:
                    rate["code"] = derived
                    rate["id"] = derived
                    changes.append(f"tax {code}: rate code <- {derived} (from {percentage}%)")
                else:
                    # 0% and anything unrecognised. Reported, not guessed.
                    changes.append(
                        f"tax {code}: NEEDS ATTENTION — {percentage}% has no unambiguous "
                        f"rate code (0% splits across 01/10/11); set it by hand"
                    )
            elif existing_code and percentage is None:
                known = percentage_by_code.get(existing_code)
                if known is not None:
                    rate["percentage"] = known
                    changes.append(f"tax {code}: percentage <- {known}% (from code {existing_code})")

            if rate:
                row["tax_rate"] = rate
        repaired.append(row)

    if changes:
        # Reassign rather than mutate in place: SQLAlchemy does not track
        # in-place edits to a JSON column, so a mutated list is never persisted.
        product.taxes = repaired
    return changes
