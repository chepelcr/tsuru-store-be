"""Imported-order line rebuild: header-discount allocation + line recompute.

These cover the seam between a customer's spreadsheet and a billable pedido.
The spreadsheet has no tax structure and — in practice — often no line-level
discounts either, so the import has to derive both. Getting either wrong is
silent: the order looks right and the invoice built from it overcharges.

The helpers under test are pure, so they are loaded out of `order_service`
without importing the module — which reaches for boto3, S3 and a wkhtmltopdf
binary that no unit-test environment should need. The dependencies they DO use
(`app.utils.money`, the calculators, the DTOs) are bound from the real modules,
so these tests exercise the shipped code rather than a copy of it.
"""
from __future__ import annotations

import ast
import pathlib
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.dtos.requests.manual_order_dto import ManualOrderLineDTO
from app.dtos.requests.product_request_dto import (
    ProductDiscountDTO,
    ProductTaxDTO,
    TaxAmountDTO,
    TaxFactorDTO,
    TaxRateDTO,
    TaxSpecialFieldsDTO,
)
from app.enums.hacienda_codes import DiscountType
from app.enums.hacienda_codes import ProductCodeType, TaxType
from app.utils.product_fiscal_defaults import repair_tax_rows
from app.services.line_calculation_service import LineCalculator, LineInput
from app.utils.money import (
    allocate_money,
    q_money,
    round_money,
    sum_money,
    to_decimal,
)

D = Decimal

_HELPERS = {
    "_round_money",
    "canonical_line_dtos",
    "_line_amounts",
    "_normalize_tax_row",
    "_normalize_discount_row",
    "_imported_line_discounts",
    "_imported_line_taxes",
    "_imported_line_net_price",
    "_allocate_header_discount",
    "_imported_line_codes",
    "_line_input_from_structured",
    "_recompute_imported_line",
    "_resum_order_totals",
    "allocate_order_header_discount",
    "clear_derived_base_amounts",
    "refill_line_fiscal_fields",
    "_product_exemption_row",
}


def _load_helpers() -> dict:
    """Exec just the pure helpers from `order_service`, with their deps bound."""
    source = pathlib.Path("app/services/order_service.py").read_text()
    tree = ast.parse(source)
    module = ast.Module(
        body=[
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in _HELPERS
        ],
        type_ignores=[],
    )
    namespace = {
        "Decimal": Decimal,
        "ROUND_HALF_UP": ROUND_HALF_UP,
        "DiscountType": DiscountType,
        "ProductDiscountDTO": ProductDiscountDTO,
        "ProductTaxDTO": ProductTaxDTO,
        "TaxAmountDTO": TaxAmountDTO,
        "TaxFactorDTO": TaxFactorDTO,
        "TaxRateDTO": TaxRateDTO,
        "TaxSpecialFieldsDTO": TaxSpecialFieldsDTO,
        "LineCalculator": LineCalculator,
        "LineInput": LineInput,
        "ManualOrderLineDTO": ManualOrderLineDTO,
        "ProductCodeType": ProductCodeType,
        "allocate_money": allocate_money,
        "q_money": q_money,
        "round_money": round_money,
        "sum_money": sum_money,
        "to_decimal": to_decimal,
        "MANUAL_ORDER_SOURCE": "manual",
        "TaxType": TaxType,
        "_IVA_FAMILY_TAX_CODES": frozenset(
            {TaxType.IVA.value, TaxType.IVACE.value, TaxType.IVARBU.value}
        ),
        "repair_tax_rows": repair_tax_rows,
    }
    exec(compile(module, "order_service_helpers", "exec"), namespace)
    return namespace


helpers = _load_helpers()


class Row:
    """Minimal stand-in for a parsed spreadsheet line / an `OrderLine`."""

    def __init__(self, **fields) -> None:
        self.__dict__.update(fields)


def _parsed_line(line_number: int, unit_price: float, qty: int, discount: float = 0):
    return Row(
        line_number=line_number,
        unit_price=unit_price,
        quantity_ordered=qty,
        units_ordered=qty,
        discount=discount,
    )


class TestHeaderDiscountAllocation:
    """Real chain spreadsheets leave every line at 0 and total the discount."""

    def test_allocates_in_proportion_to_line_gross(self) -> None:
        parsed = Row(
            discounts=1000.0,
            lines=[_parsed_line(1, 100.0, 10), _parsed_line(2, 200.0, 15)],
        )
        allocated = helpers["_allocate_header_discount"](parsed)
        # Gross is 1 000 and 3 000, so 25% / 75% of the 1 000 discount.
        assert allocated[1] == pytest.approx(250.0)
        assert allocated[2] == pytest.approx(750.0)

    def test_allocation_sums_back_to_the_header_exactly(self) -> None:
        # Three equal lines cannot be split evenly at 5 dp; the rounding
        # remainder has to land somewhere or the order stops reconciling.
        parsed = Row(
            discounts=10.0,
            lines=[_parsed_line(i, 10.0, 1) for i in range(1, 4)],
        )
        allocated = helpers["_allocate_header_discount"](parsed)
        assert sum(D(str(v)) for v in allocated.values()) == D("10")

    def test_lines_with_their_own_discounts_are_left_alone(self) -> None:
        # A spreadsheet that fills the column in is authoritative; allocating on
        # top of it would double-discount the order.
        parsed = Row(
            discounts=1000.0,
            lines=[_parsed_line(1, 100.0, 10, discount=50), _parsed_line(2, 200.0, 15)],
        )
        assert helpers["_allocate_header_discount"](parsed) == {}

    def test_header_discount_larger_than_the_order_is_capped(self) -> None:
        # Bad data, not a 100% discount — capping keeps a line from going
        # negative and turning into an invoice that pays the customer.
        parsed = Row(discounts=100.0, lines=[_parsed_line(1, 10.0, 1)])
        allocated = helpers["_allocate_header_discount"](parsed)
        assert sum(D(str(v)) for v in allocated.values()) == D("10")

    def test_no_header_discount_allocates_nothing(self) -> None:
        parsed = Row(discounts=0, lines=[_parsed_line(1, 10.0, 1)])
        assert helpers["_allocate_header_discount"](parsed) == {}


class TestImportedLineRecompute:
    def _line(self, **overrides):
        base = dict(
            quantity_ordered=10,
            units_ordered=10,
            unit_price=1000.0,
            net_price=1000.0,
            cabys=None,
            discount=250.0,
            tax=0.0,
            line_total=0.0,
            discounts=helpers["_imported_line_discounts"](250.0),
            taxes=[
                {
                    "tax_type_id": "01",
                    "tax_rate": {"id": "r", "percentage": 13.0, "code": "08"},
                }
            ],
        )
        base.update(overrides)
        return Row(**base)

    def test_recomputes_over_the_order_quantity(self) -> None:
        line = self._line()
        helpers["_recompute_imported_line"](line)
        # 10 x 1 000 = 10 000 gross, less 250, taxed at 13%.
        assert line.discount == pytest.approx(250.0)
        assert line.tax == pytest.approx(9750 * 0.13)
        assert line.line_total == pytest.approx(9750 * 1.13)

    def test_import_discount_is_commercial_not_royalty(self) -> None:
        """07, never 01/03 — the difference is who owes the IVA.

        Natures 01 and 03 route the line's IVA into
        `ImpuestoAsumidoEmisorFabrica`, so mis-typing a supplier's trade
        discount as one of them would make the issuer absorb tax the customer
        actually pays.
        """
        rows = helpers["_imported_line_discounts"](250.0)
        assert rows[0]["discount_type_id"] == DiscountType.COMMERCIAL.value
        assert rows[0]["reason"] is None

    def test_zero_discount_produces_no_discount_row(self) -> None:
        assert helpers["_imported_line_discounts"](0) is None

    def test_line_without_structured_detail_is_untouched(self) -> None:
        """Nothing to derive a rate from — the customer's figures stand."""
        line = self._line(discounts=None, taxes=None, tax=3.0, line_total=497.0)
        helpers["_recompute_imported_line"](line)
        assert line.tax == 3.0
        assert line.line_total == 497.0

    def test_product_taxes_are_copied_without_their_amounts(self) -> None:
        """The product's own `amount` was computed against the PRODUCT's price.

        Carrying it onto the line would assert a figure that has nothing to do
        with the order quantity; `_recompute_imported_line` derives the real one.
        """
        product = Row(taxes=[{"tax_type_id": "01", "amount": 42.0}])
        assert helpers["_imported_line_taxes"](product) == [{"tax_type_id": "01"}]

    def test_net_price_prefers_the_catalog_over_the_spreadsheet(self) -> None:
        parsed = _parsed_line(1, 900.0, 1)
        assert helpers["_imported_line_net_price"](parsed, Row(unit_price=1000.0)) == 1000.0
        assert helpers["_imported_line_net_price"](parsed, Row(unit_price=None)) == 900.0
        assert helpers["_imported_line_net_price"](parsed, Row(unit_price=0)) == 900.0


class TestOrderTotals:
    def test_totals_are_summed_from_the_lines(self) -> None:
        """The header the chain sent is not what the invoice will carry."""
        order = Row(
            lines=[
                Row(unit_price=100.0, quantity_ordered=10, units_ordered=10,
                    discount=50.0, tax=123.5),
                Row(unit_price=200.0, quantity_ordered=5, units_ordered=5,
                    discount=0.0, tax=130.0),
            ],
            subtotal=0, discounts=0, net_total=0, taxes=0, grand_total=0,
            line_count=0, total_quantities=0,
        )
        helpers["_resum_order_totals"](order)
        assert order.subtotal == pytest.approx(2000.0)
        assert order.discounts == pytest.approx(50.0)
        assert order.net_total == pytest.approx(1950.0)
        assert order.taxes == pytest.approx(253.5)
        assert order.grand_total == pytest.approx(2203.5)
        assert order.line_count == 2
        assert order.total_quantities == 15


class TestLegacyRowNormalization:
    """Two spellings of the same column had to be readable by one reader.

    Manual orders persisted the request shape (`code` / `rate` / `nature`);
    imported orders persisted the canonical `ProductTaxDTO` dump. New writes are
    all canonical, but the older rows are still in the database — and they are
    exactly the ones a backfill exists to repair, so it has to read them.
    """

    def test_canonical_tax_row_passes_through_untouched(self) -> None:
        row = {"tax_type_id": "01", "tax_rate": {"percentage": 13.0}}
        assert helpers["_normalize_tax_row"](row) is row

    def test_legacy_tax_row_is_translated(self) -> None:
        row = {"code": "01", "rate": 13.0, "rate_code": "08"}
        assert helpers["_normalize_tax_row"](row) == {
            "tax_type_id": "01",
            "tax_rate": {"id": "08", "percentage": 13.0, "code": "08"},
        }

    def test_legacy_tax_row_keeps_special_fields(self) -> None:
        special = {"quantity": 0.355, "volume_consumption": 0.355}
        row = {"code": "05", "special_fields": special}
        translated = helpers["_normalize_tax_row"](row)
        assert translated["tax_type_id"] == "05"
        assert translated["special_fields"] == special

    def test_legacy_discount_row_is_translated(self) -> None:
        row = {"code": "07", "nature": "trade", "amount": 250.0}
        assert helpers["_normalize_discount_row"](row) == {
            "discount_type_id": "07",
            "reason": "trade",
            "percentage": None,
            "amount": 250.0,
            "is_amount": True,
        }


class TestPosLineRoundTrip:
    """A POS-captured excise line has to survive being stored and re-read.

    The path is: POS payload -> canonical JSONB -> recompute (reprocess or
    backfill) -> the invoice. Every hop has to produce the same money, or the
    pedido the customer signed for and the factura they receive differ.
    """

    def _beer_line(self) -> ManualOrderLineDTO:
        # 12 cans of 355 ml beer at 4.5%, ISEBA + 13% IVA, 10% trade discount.
        return ManualOrderLineDTO(
            line_number=1,
            description="Cerveza 355ml",
            quantity=12,
            unit_price=1000,
            cabys="2434001000000",
            taxes=[
                {
                    "code": "04",
                    "special_fields": {
                        "quantity": 0.355,
                        "percentage": 4.5,
                        "tax_amount_id": 7,
                        "tax_unit_amount": 3500,
                    },
                },
                {"code": "01", "rate": 13.0, "rate_code": "08"},
            ],
            discounts=[{"code": "07", "percentage": 10.0}],
        )

    def test_excise_line_prices_correctly_at_capture(self) -> None:
        subtotal, discount, tax, total = helpers["_line_amounts"](self._beer_line())

        assert subtotal == pytest.approx(10800.0)   # 12 000 less 10%
        assert discount == pytest.approx(1200.0)
        # ISEBA: volume 0.355 rounds to 0.36 L, proportion 0.0162,
        # 12 x 0.0162 x 3 500 = 680.40. The issuer absorbs it (-476), so it is
        # NOT in the customer's tax — but it still builds the IVA base (-454):
        # (10 800 + 680.40) x 13% = 1 492.452, stored at the order's two
        # decimals as 1 492.45.
        assert tax == pytest.approx(1492.45)
        assert total == pytest.approx(12292.45)

    def test_stored_shape_recomputes_to_the_same_numbers(self) -> None:
        line = self._beer_line()
        subtotal, discount, tax, total = helpers["_line_amounts"](line)

        discount_dtos, tax_dtos = helpers["canonical_line_dtos"](line)
        stored = Row(
            quantity_ordered=12,
            units_ordered=12,
            unit_price=1000.0,
            net_price=1000.0,
            cabys="2434001000000",
            discount=0.0,
            tax=0.0,
            line_total=0.0,
            taxes=[t.model_dump() for t in tax_dtos],
            discounts=[d.model_dump() for d in discount_dtos],
        )
        helpers["_recompute_imported_line"](stored)

        assert stored.discount == pytest.approx(discount)
        assert stored.tax == pytest.approx(tax)
        assert stored.line_total == pytest.approx(total)

    def test_special_fields_survive_the_round_trip(self) -> None:
        """A per-unit excise cannot be recovered from a total.

        If the volume, the degree and the per-unit amount do not reach storage,
        billing the pedido later has no way back to the excise — which is why
        the manual-order DTO carries them at all.
        """
        _, tax_dtos = helpers["canonical_line_dtos"](self._beer_line())
        special = tax_dtos[0].special_fields
        assert special is not None
        assert special.quantity == 0.355
        assert special.percentage == 4.5
        assert special.tax_amount.amount == 3500.0

    def test_a_legacy_row_still_computes(self) -> None:
        """Rows written before the shapes were unified are still in the database.

        They are precisely the ones a backfill exists to repair, so failing to
        read them would skip the orders that need it most.
        """
        legacy = Row(
            quantity_ordered=12,
            units_ordered=12,
            unit_price=1000.0,
            net_price=1000.0,
            cabys=None,
            discount=0.0,
            tax=0.0,
            line_total=0.0,
            taxes=[{"code": "01", "rate": 13.0, "rate_code": "08"}],
            discounts=[{"code": "07", "percentage": 10.0, "nature": None}],
        )
        helpers["_recompute_imported_line"](legacy)
        assert legacy.tax == pytest.approx(10800 * 0.13)


class TestOrderMoneyPrecision:
    """Order money is two decimals, and the parts have to add up to the whole.

    The colón has no sub-céntimo, the spreadsheets these orders come from carry
    whole colones, and every surface formats at two. Storing five decimals made
    the stored figures disagree with the displayed ones — and, worse, made the
    lines stop adding up to the total, because a total rounded at the end is not
    the sum of the lines rounded individually.
    """

    def test_line_money_is_stored_at_two_decimals(self) -> None:
        line = Row(
            quantity_ordered=3,
            units_ordered=3,
            unit_price=1495.0,
            net_price=1495.0,
            cabys=None,
            discount=0.0,
            tax=0.0,
            line_total=0.0,
            discounts=helpers["_imported_line_discounts"](145.5035),
            taxes=[
                {
                    "tax_type_id": "01",
                    "tax_rate": {"id": "r", "percentage": 13.0, "code": "08"},
                }
            ],
        )
        helpers["_recompute_imported_line"](line)

        for value in (line.discount, line.tax, line.line_total):
            assert value == round(value, 2), f"{value} carries sub-céntimo noise"

    def test_a_line_total_equals_its_own_rounded_parts(self) -> None:
        # 4 903.63104 stored as 4 903.63 — and it must equal the rounded
        # subtotal plus the rounded tax, not the rounded sum of raw ones.
        line = Row(
            quantity_ordered=3,
            units_ordered=3,
            unit_price=1495.0,
            net_price=1495.0,
            cabys=None,
            discount=0.0,
            tax=0.0,
            line_total=0.0,
            discounts=helpers["_imported_line_discounts"](145.5035),
            taxes=[
                {
                    "tax_type_id": "01",
                    "tax_rate": {"id": "r", "percentage": 13.0, "code": "08"},
                }
            ],
        )
        helpers["_recompute_imported_line"](line)
        subtotal = round(3 * 1495.0 - line.discount, 2)
        assert line.line_total == pytest.approx(subtotal + line.tax)

    def test_order_total_equals_the_sum_of_the_line_totals(self) -> None:
        """The regression this whole change exists for.

        With a header discount allocated across lines and tax applied to each,
        summing raw values and rounding the result diverged from the sum of the
        rounded lines on ~47% of randomly generated multi-line orders. On screen
        that reads as an order whose lines do not add up.
        """
        parsed = Row(
            discounts=1000.0,
            lines=[
                _parsed_line(1, 1495.0, 3),
                _parsed_line(2, 2350.0, 7),
                _parsed_line(3, 899.0, 11),
            ],
        )
        allocated = helpers["_allocate_header_discount"](parsed)

        lines = []
        for parsed_line in parsed.lines:
            line = Row(
                quantity_ordered=parsed_line.quantity_ordered,
                units_ordered=parsed_line.units_ordered,
                unit_price=parsed_line.unit_price,
                net_price=parsed_line.unit_price,
                cabys=None,
                discount=allocated[parsed_line.line_number],
                tax=0.0,
                line_total=0.0,
                discounts=helpers["_imported_line_discounts"](
                    allocated[parsed_line.line_number]
                ),
                taxes=[
                    {
                        "tax_type_id": "01",
                        "tax_rate": {"id": "r", "percentage": 13.0, "code": "08"},
                    }
                ],
            )
            helpers["_recompute_imported_line"](line)
            lines.append(line)

        order = Row(
            lines=lines,
            subtotal=0, discounts=0, net_total=0, taxes=0, grand_total=0,
            line_count=0, total_quantities=0,
        )
        helpers["_resum_order_totals"](order)

        assert order.grand_total == pytest.approx(
            round(sum(line.line_total for line in lines), 2)
        )
        assert order.discounts == pytest.approx(1000.0)
        assert order.taxes == pytest.approx(round(sum(line.tax for line in lines), 2))

    def test_allocation_shares_are_whole_centimos(self) -> None:
        parsed = Row(
            discounts=1000.0,
            lines=[_parsed_line(1, 1495.0, 3), _parsed_line(2, 2350.0, 7)],
        )
        for share in helpers["_allocate_header_discount"](parsed).values():
            assert share == round(share, 2)


class TestLineCodes:
    """The line's own codes, not the product's."""

    def test_builds_the_canonical_shape_from_the_spreadsheet_line(self) -> None:
        parsed = Row(
            internal_code="INT-1",
            code="MFR-9",
            client_article_code="WM-777",
        )
        assert helpers["_imported_line_codes"](parsed) == [
            {"code_type_id": "04", "number": "INT-1"},
            {"code_type_id": "03", "number": "MFR-9"},
            {"code_type_id": "02", "number": "WM-777"},
        ]

    def test_omits_codes_the_line_does_not_carry(self) -> None:
        parsed = Row(internal_code="INT-1", code="", client_article_code=None)
        assert helpers["_imported_line_codes"](parsed) == [
            {"code_type_id": "04", "number": "INT-1"}
        ]

    def test_a_line_with_no_codes_at_all_stores_none(self) -> None:
        # None rather than [] so the mapper can fall back to the product for
        # rows written before the line had a column of its own.
        parsed = Row(internal_code=None, code=None, client_article_code="   ")
        assert helpers["_imported_line_codes"](parsed) is None

class TestFiscalRepair:
    """`refill_line_fiscal_fields` — what makes Reprocess a repair, not a recompute.

    Recomputing money over a line with no tax structure is a no-op, and that was
    all Reprocess did unless the original spreadsheet was still in S3. So the
    orders that most needed fixing — a storefront order, a manual one, or any
    whose file was deleted — were exactly the ones it skipped.
    """

    def _product(self, **overrides):
        base = dict(
            cabys=Row(code="2718000000100"),
            unit_measure="Sp",
            commercial_unit_measure="Lata",
            customs_part="2203.00.00",
            iva_collected_factory=None,
            unit_price=1000.0,
            codes=[{"code_type_id": "04", "number": "INT-1"}],
            taxes=[
                {
                    "tax_type_id": "01",
                    "tax_rate": {"id": "8", "percentage": 13.0, "code": "08"},
                }
            ],
        )
        base.update(overrides)
        return Row(**base)

    def _bare_line(self, product, **overrides):
        """A line as an older import left it: money only, no fiscal structure."""
        base = dict(
            line_id=1,
            line_number=1,
            quantity_ordered=10,
            units_ordered=10,
            unit_price=1000.0,
            net_price=None,
            cabys=None,
            taxes=None,
            discounts=None,
            codes=None,
            unit_measure=None,
            commercial_unit_measure=None,
            customs_part=None,
            iva_collected_factory=None,
            base_amount=None,
            discount=0.0,
            tax=0.0,
            line_total=0.0,
            product=product,
        )
        base.update(overrides)
        return Row(**base)

    def test_fills_cabys_taxes_and_unit_from_the_product(self) -> None:
        product = self._product()
        line = self._bare_line(product)
        order = Row(source="import", discounts=0.0, lines=[line])

        changes = helpers["refill_line_fiscal_fields"](order)

        assert line.cabys == "2718000000100"
        # Without a unit Hacienda's line falls back to "Unid", wrong for
        # anything sold by weight or volume.
        assert line.unit_measure == "Sp"
        assert line.net_price == 1000.0
        # The rate CODE must come across, not just the percentage — sales-api
        # derives the rate from the code alone for the IVA family.
        assert line.taxes[0]["tax_rate"]["code"] == "08"
        assert changes, "a repair that changed something must say so"

    def test_never_overwrites_what_the_line_already_has(self) -> None:
        # A hand-edited line's detail is the operator's, not ours to replace.
        product = self._product()
        line = self._bare_line(
            product,
            cabys="9999999999999",
            unit_measure="kg",
            taxes=[{"tax_type_id": "02", "tax_rate": {"percentage": 10.0, "code": "08"}}],
        )
        order = Row(source="import", discounts=0.0, lines=[line])

        helpers["refill_line_fiscal_fields"](order)

        assert line.cabys == "9999999999999"
        assert line.unit_measure == "kg"
        assert line.taxes[0]["tax_type_id"] == "02"

    def test_reports_nothing_when_nothing_was_missing(self) -> None:
        product = self._product()
        line = self._bare_line(
            product,
            cabys="2718000000100",
            net_price=1000.0,
            unit_measure="Sp",
            taxes=product.taxes,
            codes=product.codes,
            discounts=[],
            discount=0.0,
        )
        order = Row(source="import", discounts=0.0, lines=[line])
        assert helpers["refill_line_fiscal_fields"](order) == []

    def test_allocates_a_header_discount_the_lines_do_not_carry(self) -> None:
        product = self._product()
        a = self._bare_line(product, line_id=1, line_number=1, unit_price=1000.0)
        b = self._bare_line(product, line_id=2, line_number=2, unit_price=3000.0)
        order = Row(source="import", discounts=400.0, lines=[a, b])

        helpers["refill_line_fiscal_fields"](order)

        # Pro-rata on gross: 10 000 and 30 000 → 25% / 75% of 400.
        assert a.discount == 100.0
        assert b.discount == 300.0
        assert a.discounts[0]["discount_type_id"] == "07"

    def test_allocation_rounds_at_two_decimals_like_order_money(self) -> None:
        # The backfill script used to quantize this at 5 dp while the service
        # rounded at 2, so a repaired order's line discounts did not add back to
        # its header at the precision order money is stored in.
        product = self._product()
        lines = [
            self._bare_line(product, line_id=i, line_number=i, unit_price=1000.0)
            for i in (1, 2, 3)
        ]
        order = Row(source="import", discounts=100.0, lines=lines)

        shares = helpers["allocate_order_header_discount"](order)

        assert sum(shares.values()) == 100.0
        for value in shares.values():
            assert round(value, 2) == value

    def test_repairs_a_stored_line_tax_that_lost_its_rate_code(self) -> None:
        """The case that blocked the repair on the very orders it exists for.

        A line that copied its taxes from a product back when the save path was
        stripping the rate code carries an IVA row with a percentage and a null
        code. Filling in *missing* fields never touched it, and once
        `ProductTaxDTO` began rejecting that shape the recompute could not parse
        the line at all — so the backfill failed on exactly those orders.
        """
        product = self._product()
        line = self._bare_line(
            product,
            cabys="2718000000100",
            net_price=1000.0,
            unit_measure="Sp",
            # No `code` on the rate — the poisoned shape.
            taxes=[{"tax_type_id": "01", "tax_rate": {"id": "8", "percentage": 13.0}}],
            codes=product.codes,
            discounts=[],
        )
        order = Row(source="import", discounts=0.0, lines=[line])

        changes = helpers["refill_line_fiscal_fields"](order)

        assert line.taxes[0]["tax_rate"]["code"] == "08"
        assert any("rate code <- 08" in c for c in changes)

    def test_does_not_guess_a_rate_code_for_a_zero_percent_line(self) -> None:
        # Exento (10), no sujeto (11) and crédito pleno (01) are all 0%, so the
        # repair reports it instead of picking one.
        product = self._product()
        line = self._bare_line(
            product,
            cabys="2718000000100",
            net_price=1000.0,
            unit_measure="Sp",
            taxes=[{"tax_type_id": "01", "tax_rate": {"percentage": 0.0}}],
            codes=product.codes,
            discounts=[],
        )
        order = Row(source="import", discounts=0.0, lines=[line])

        changes = helpers["refill_line_fiscal_fields"](order)

        assert "code" not in line.taxes[0]["tax_rate"]
        assert any("NEEDS ATTENTION" in c for c in changes)

    def test_leaves_line_discounts_alone_when_they_declare_their_own(self) -> None:
        product = self._product()
        line = self._bare_line(product, discount=250.0)
        order = Row(source="import", discounts=400.0, lines=[line])
        assert helpers["allocate_order_header_discount"](order) == {}


class TestDerivedBaseAmountClearing:
    """`base_amount` is the editable-base OVERRIDE, not a derived figure."""

    def test_clears_a_copied_base_on_an_imported_order(self) -> None:
        line = Row(base_amount=1000.0)
        order = Row(source="import", lines=[line])
        helpers["clear_derived_base_amounts"](order)
        assert line.base_amount is None

    def test_leaves_a_manual_order_alone(self) -> None:
        # Only a manual order legitimately carries an operator-set base, for tax
        # code 07 or IVACobradoFabrica 01.
        line = Row(base_amount=5000.0)
        order = Row(source="manual", lines=[line])
        helpers["clear_derived_base_amounts"](order)
        assert line.base_amount == 5000.0

class TestProductExonerationOnImportedLines:
    """A product's catalog exoneration reaches the line's IVA row.

    `Product` stores the exoneration as three flat columns because it is a
    property of the ARTICLE — a free-trade-zone good is always exonerated — while
    the document hangs `Exoneracion` off each `Impuesto`. This is the reshape.
    """

    def _product(self, **overrides):
        base = dict(
            exemption_authorization_code="08",
            exempted_rate=100.0,
            exemption_amount=130.0,
            taxes=[
                {
                    "tax_type_id": "01",
                    "tax_rate": {"id": "8", "percentage": 13.0, "code": "08"},
                }
            ],
        )
        base.update(overrides)
        return Row(**base)

    def test_copies_the_authorization_and_rate_onto_the_iva_row(self) -> None:
        out = helpers["_imported_line_taxes"](self._product())
        assert out[0]["exemption"] == {"type": "08", "percentage": 100.0}

    def test_does_not_copy_the_amount(self) -> None:
        # `MontoExonerado` is derived as tax x percentage/100 against THIS line's
        # tax. The product's figure was computed against one unit, so carrying it
        # would pin a 23-unit line's exonerated amount to one unit's — the same
        # trap `base_amount` sets.
        out = helpers["_imported_line_taxes"](self._product())
        assert "amount" not in out[0]["exemption"]

    def test_never_attaches_an_exoneration_to_an_excise(self) -> None:
        # Nota 10.1 authorizations forgive VAT, not the specific consumption
        # taxes, so an ISEBA row must come through untouched.
        product = self._product(
            taxes=[
                {"tax_type_id": "04", "special_fields": {"quantity": 0.355}},
                {"tax_type_id": "01", "tax_rate": {"percentage": 13.0, "code": "08"}},
            ]
        )
        out = helpers["_imported_line_taxes"](product)
        assert "exemption" not in out[0]
        assert out[1]["exemption"]["type"] == "08"

    def test_leaves_an_exoneration_the_tax_row_already_carries(self) -> None:
        product = self._product(
            taxes=[
                {
                    "tax_type_id": "01",
                    "tax_rate": {"percentage": 13.0, "code": "08"},
                    "exemption": {"type": "02", "percentage": 50.0},
                }
            ]
        )
        out = helpers["_imported_line_taxes"](product)
        assert out[0]["exemption"] == {"type": "02", "percentage": 50.0}

    def test_no_exoneration_when_the_product_has_no_authorization(self) -> None:
        product = self._product(exemption_authorization_code=None)
        out = helpers["_imported_line_taxes"](product)
        assert "exemption" not in out[0]
        assert helpers["_product_exemption_row"](product) is None

