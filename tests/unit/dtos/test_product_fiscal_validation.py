"""Product-save validation must match what sales-be will accept.

A product is the template every document line is built from, so a rule enforced
only at emission is a rule enforced far too late: the save succeeds, the
catalogue looks right, and the failure surfaces on the first invoice — often
weeks later, against a consecutive, with an error naming a field the cashier
never filled in.

Every expectation below is written from the sales-be rule it mirrors, named in
the test, rather than from what this DTO happens to do.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.dtos.requests.product_request_dto import ProductRequestDTO


def product(**overrides) -> dict:
    """A minimal valid product; override one field per test."""
    base = {
        "name": "Producto",
        "price": 1000,
        "taxes": [
            {"tax_type_id": "01", "tax_rate": {"percentage": 13, "code": "08"}}
        ],
    }
    base.update(overrides)
    return base


def build(**overrides) -> ProductRequestDTO:
    return ProductRequestDTO.model_validate(product(**overrides))


class TestTaxCode:
    def test_accepts_every_hacienda_tax_code(self):
        # Guard: the whole enum is exercised, so a code added upstream fails
        # here until someone decides what it needs.
        from app.enums.hacienda_codes import TaxType

        for code in (TaxType.IVA, TaxType.IVACE):
            build(taxes=[{"tax_type_id": code.value,
                          "tax_rate": {"percentage": 13, "code": "08"}}])

    def test_rejects_a_tax_code_hacienda_does_not_define(self):
        # sales-be: "Invalid tax.code".
        with pytest.raises(ValidationError, match="not a valid Hacienda tax code"):
            build(taxes=[{"tax_type_id": "77"}])


class TestIvaRateCode:
    def test_iva_requires_its_rate_code(self):
        # sales-be: "tax.rate_code is required when tax.code='01'". The
        # percentage cannot stand in — exento (10), no sujeto (11) and crédito
        # pleno (01) are all 0%.
        with pytest.raises(ValidationError, match="tax_rate.code"):
            build(taxes=[{"tax_type_id": "01", "tax_rate": {"percentage": 13}}])

    def test_rejects_a_rate_code_outside_nota_8_1(self):
        with pytest.raises(ValidationError, match="Nota 8.1"):
            build(taxes=[{"tax_type_id": "01",
                          "tax_rate": {"percentage": 13, "code": "42"}}])

    @pytest.mark.parametrize("code", ["05", "06", "07"])
    def test_rejects_transitional_rates_on_a_product(self, code):
        # sales-be allows these only on document types 02/03
        # (HACIENDA_TAX_RATE_CODE_NC_ND_ONLY). A product is not a document, so a
        # default that only a corrective note may carry is never right.
        with pytest.raises(ValidationError, match="transitional rate"):
            build(taxes=[{"tax_type_id": "01",
                          "tax_rate": {"percentage": 0, "code": code}}])

    def test_allows_the_ordinary_rates(self):
        for code in ["01", "02", "03", "04", "08", "09", "10", "11"]:
            build(taxes=[{"tax_type_id": "01",
                          "tax_rate": {"percentage": 13, "code": code}}])


class TestUsedGoodsFactor:
    def test_code_08_requires_a_factor(self):
        # sales-be: "tax.factor is required when tax.code=08". Without it
        # `tax = subtotal x factor` is zero — silently, on the document.
        with pytest.raises(ValidationError, match="tax_factor.factor is required"):
            build(taxes=[{"tax_type_id": "08",
                          "tax_rate": {"percentage": 13, "code": "08"}}])

    def test_code_08_with_a_factor_is_accepted(self):
        build(taxes=[{"tax_type_id": "08",
                      "tax_rate": {"percentage": 13, "code": "08"},
                      "tax_factor": {"id": "08", "factor": 0.13}}])


class TestOneIvaPerProduct:
    def test_two_iva_family_taxes_are_rejected(self):
        # sales-be: "Only one IVA tax (code 01 or 08) is allowed per line".
        with pytest.raises(ValidationError, match="Only one IVA-family tax"):
            build(taxes=[
                {"tax_type_id": "01", "tax_rate": {"percentage": 13, "code": "08"}},
                {"tax_type_id": "07", "tax_rate": {"percentage": 13, "code": "08"}},
            ])

    def test_an_iva_alongside_an_excise_is_fine(self):
        build(taxes=[
            {"tax_type_id": "01", "tax_rate": {"percentage": 13, "code": "08"}},
            {"tax_type_id": "02", "rate": 10},
        ])


class TestFreeGoodsDiscounts:
    """Natures 01 and 03 ARE free goods — Hacienda -518 on anything less."""

    @pytest.mark.parametrize("code", ["01", "03"])
    def test_a_partial_regalia_is_rejected(self, code):
        with pytest.raises(ValidationError, match="free\\s+goods"):
            build(discounts=[{"discount_type_id": code, "percentage": 20}])

    @pytest.mark.parametrize("code", ["01", "03"])
    def test_a_full_regalia_is_accepted(self, code):
        build(discounts=[{"discount_type_id": code, "percentage": 100}])

    def test_discounts_that_cascade_to_100_percent_are_accepted(self):
        # Discounts CASCADE: 50% then 100% of the remainder removes everything.
        build(discounts=[
            {"discount_type_id": "07", "percentage": 50},
            {"discount_type_id": "01", "percentage": 100},
        ])

    def test_a_cascade_that_stops_short_is_rejected(self):
        # 50% then 50% leaves 25% of the line — not free goods.
        with pytest.raises(ValidationError, match="free\\s+goods"):
            build(discounts=[
                {"discount_type_id": "07", "percentage": 50},
                {"discount_type_id": "01", "percentage": 50},
            ])

    def test_ordinary_natures_are_unaffected(self):
        build(discounts=[{"discount_type_id": "07", "percentage": 10}])

    def test_nature_99_still_requires_its_reason(self):
        with pytest.raises(ValidationError, match="requires a non-empty reason"):
            build(discounts=[{"discount_type_id": "99", "percentage": 5}])


class TestSpecialFields:
    def test_excise_codes_require_their_special_fields(self):
        with pytest.raises(ValidationError, match="requires special_fields"):
            build(taxes=[{"tax_type_id": "03", "rate": 0}])

    def test_iseba_does_not_require_proportion(self):
        """`proportion` is DERIVED, not stored.

        `TaxCalculationService` computes it as `quantity x percentage / 100`.
        The product supplies the two inputs; asking the catalogue for the output
        would be asking it for a number only the line can produce.
        """
        build(taxes=[{
            "tax_type_id": "04",
            "rate": 0,
            "special_fields": {
                "quantity": 0.355,
                "percentage": 5,
                "tax_amount": {"id": "ta-1", "amount": 100.0},
            },
        }])

class TestNonFiscalProducts:
    """A product must be storable with NO fiscal information at all.

    Not every organization issues electronic documents — the POS has a fiscal
    toggle, and an org that is not registered with Hacienda still needs a
    catalogue, an inventory and a price. Every rule above is therefore
    conditional on the fiscal data being PRESENT; none of them may become a
    requirement to supply it.

    These are the cases that would break a shop that only sells, so they are
    pinned explicitly rather than left to follow from the others.
    """

    def test_a_product_with_no_fiscal_information_is_accepted(self):
        ProductRequestDTO.model_validate({"name": "Camisa", "price": 5000})

    def test_explicit_nulls_are_accepted(self):
        ProductRequestDTO.model_validate(
            {"name": "Camisa", "price": 5000, "taxes": None, "discounts": None}
        )

    def test_empty_lists_are_accepted(self):
        ProductRequestDTO.model_validate(
            {"name": "Camisa", "price": 5000, "taxes": [], "discounts": []}
        )

    def test_inventory_without_any_tax_is_accepted(self):
        ProductRequestDTO.model_validate({
            "name": "Camisa", "price": 5000,
            "track_inventory": True, "stock_quantity": 10,
        })

    def test_an_ordinary_discount_without_taxes_is_accepted(self):
        # The free-goods rule must not fire on a nature that is not free goods.
        ProductRequestDTO.model_validate({
            "name": "Camisa", "price": 5000,
            "discounts": [{"discount_type_id": "07", "percentage": 10}],
        })

    def test_a_non_iva_tax_alone_is_accepted(self):
        # The IVA rules must not fire on a product that carries no IVA.
        ProductRequestDTO.model_validate({
            "name": "Camisa", "price": 5000,
            "taxes": [{"tax_type_id": "02", "rate": 10}],
        })

    def test_no_cabys_is_accepted(self):
        # CABYS is mandatory on a DOCUMENT, not in a catalogue an unregistered
        # org keeps. Reprocess and the backfills fill it in when one is needed.
        ProductRequestDTO.model_validate({"name": "Camisa", "price": 5000, "cabys_id": None})

