"""Per-Hacienda-code unit tests for `TaxCalculator`.

One method per code (01–08, 12, 99), plus the two rules that decide who PAYS
each row: the factory-assumed excises (03/04/05/12, always the issuer) and the
line-level assumption (royalty/bonus natures, `IVACobradoFabrica` 01).

The expected numbers here are written from the Hacienda rules and from what the
biller (`jbiller_common.hacienda.services.tax_service`) files, not derived from
this implementation — a divergence between the two means an order and the
invoice it becomes disagree.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.dtos.requests.product_request_dto import (
    ProductTaxDTO,
    TaxAmountDTO,
    TaxFactorDTO,
    TaxRateDTO,
    TaxSpecialFieldsDTO,
)
from app.enums.hacienda_codes import CabysSpecialPrefix, TaxRateCode, TaxType
from app.services.tax_calculation_service import TaxCalculator

D = Decimal


#: Codes whose percentage is derived from the rate CODE rather than a supplied
#: rate, and which therefore cannot be represented without one.
_IVA_FAMILY = (TaxType.IVA, TaxType.IVACE, TaxType.IVARBU)


def _make_tax(
    tax_type: TaxType,
    *,
    rate: Decimal | None = None,
    rate_code: TaxRateCode | None = None,
    factor: Decimal | None = None,
    sf_quantity: Decimal | None = None,
    sf_percentage: Decimal | None = None,
    sf_volume: Decimal | None = None,
    sf_amount: Decimal | None = None,
) -> ProductTaxDTO:
    # An IVA-family tax is not representable without its Nota 8.1 rate code —
    # sales-api derives the percentage from the code alone, so a row with a rate
    # and no code cannot be priced, and `ProductTaxDTO` now refuses it. The
    # fixtures default to the general 13% bracket so each test states only the
    # variable it is actually exercising; a test that cares about the bracket
    # passes `rate_code` explicitly.
    if tax_type in _IVA_FAMILY:
        if rate_code is None:
            rate_code = TaxRateCode.GENERAL_13
        if rate is None:
            rate = Decimal("13")

    return ProductTaxDTO(
        tax_type_id=tax_type.value,
        tax_rate=(
            TaxRateDTO(
                percentage=float(rate),
                code=rate_code.value if rate_code else None,
            )
            if rate is not None
            else None
        ),
        tax_factor=(
            TaxFactorDTO(id="factor-1", factor=float(factor)) if factor is not None else None
        ),
        special_fields=(
            TaxSpecialFieldsDTO(
                quantity=float(sf_quantity) if sf_quantity is not None else None,
                percentage=float(sf_percentage) if sf_percentage is not None else None,
                volume_consumption=float(sf_volume) if sf_volume is not None else None,
                tax_amount=(
                    TaxAmountDTO(id="ta-1", amount=float(sf_amount))
                    if sf_amount is not None
                    else None
                ),
            )
            if any(
                v is not None
                for v in (sf_quantity, sf_percentage, sf_volume, sf_amount)
            )
            else None
        ),
    )


def _run(calc, taxes, *, subtotal, cabys=None, detail_quantity=D("1")):
    return calc.compute_line_taxes(
        taxes=taxes,
        subtotal=subtotal,
        detail_quantity=detail_quantity,
        cabys_code=cabys,
        monto_total_original=subtotal,
    )


class TestTaxCalculator:
    def setup_method(self) -> None:
        self.calc = TaxCalculator()

    def test_iva_01_general_13(self) -> None:
        # 13% IVA on a 1000 subtotal = 130.
        result = _run(
            self.calc,
            [_make_tax(TaxType.IVA, rate=D("13"), rate_code=TaxRateCode.GENERAL_13)],
            subtotal=D("1000"),
        )
        assert result.iva_tax_total == D("130")
        assert result.net_tax == D("130")
        assert result.base_amount == D("1000")
        assert result.factory_assumed_tax == D("0")

    def test_isc_02_increments_base(self) -> None:
        # 10% ISC on 1000 = 100; base climbs from 1000 to 1100.
        result = _run(
            self.calc,
            [_make_tax(TaxType.ISC, rate=D("10"))],
            subtotal=D("1000"),
        )
        assert result.per_tax[0].amount == D("100")
        assert result.other_tax_total == D("100")
        assert result.base_amount == D("1100")

    def test_iuc_03_per_unit_and_is_issuer_assumed(self) -> None:
        # 5 units × 200 = 1000; IUC does not build the IVA base (-454 names
        # 02/04/05/12, not 03), and the ISSUER absorbs it (-476).
        result = _run(
            self.calc,
            [_make_tax(TaxType.IUC, sf_quantity=D("5"), sf_amount=D("200"))],
            subtotal=D("1000"),
        )
        assert result.per_tax[0].amount == D("1000")
        assert result.base_amount == D("1000")
        assert result.factory_assumed_tax == D("1000")
        assert result.net_tax == D("0")

    def test_iseba_04_with_detail_quantity(self) -> None:
        # detail_quantity (2) × (qty 4 × pct 50% / 100) × unit 100 = 2 × 2 × 100 = 400.
        result = _run(
            self.calc,
            [
                _make_tax(
                    TaxType.ISEBA,
                    sf_quantity=D("4"),
                    sf_percentage=D("50"),
                    sf_amount=D("100"),
                )
            ],
            subtotal=D("1000"),
            detail_quantity=D("2"),
        )
        assert result.per_tax[0].amount == D("400")
        # ISEBA grows the base (-454) but is absorbed by the issuer (-476), so
        # it never reaches what the customer owes.
        assert result.base_amount == D("1400")
        assert result.factory_assumed_tax == D("400")
        assert result.net_tax == D("0")

    def test_iseba_04_rounds_the_volume_to_two_decimals_first(self) -> None:
        """The millilitre trap.

        `CantidadUnidadMedida` allows 2 fraction digits, not 5, so a 355 ml can
        is declared as 0.36 L — and `Proporcion` has to be derived from THAT,
        or the declared quantity and the declared proportion disagree and
        Hacienda recomputes a different amount.

            0.36 × 4.5 / 100 = 0.0162      (not 0.355 × 4.5 / 100 = 0.015975)
            12 × 0.0162 × 3500 = 680.40    (not 670.95)
        """
        result = _run(
            self.calc,
            [
                _make_tax(
                    TaxType.ISEBA,
                    sf_quantity=D("0.355"),
                    sf_percentage=D("4.5"),
                    sf_amount=D("3500"),
                )
            ],
            subtotal=D("1000"),
            detail_quantity=D("12"),
        )
        assert result.per_tax[0].amount == D("680.40000")

    def test_isebec_05_beverage_divides_by_the_consumption_volume(self) -> None:
        """The DEFAULT formula, per the Hacienda calculation rules for code 05.

            Monto = Cantidad × CantidadUnidadMedida
                    × (ImpuestoUnidad / VolumenUnidadConsumo)

        4 × 2 × (10 / 2) = 40. This branch used to be gated on CABYS "2202", a
        Harmonized System heading that matches no CABYS at all, so it never ran
        and every code-05 line took the soap formula instead.
        """
        result = _run(
            self.calc,
            [
                _make_tax(
                    TaxType.ISEBEC,
                    sf_quantity=D("2"),
                    sf_volume=D("2"),
                    sf_amount=D("10"),
                )
            ],
            subtotal=D("1000"),
            cabys=CabysSpecialPrefix.ISEBEC_PACKAGED_BEVERAGE.value + "001000000",
            detail_quantity=D("4"),
        )
        assert result.per_tax[0].amount == D("40")

    def test_isebec_05_toilet_soap_multiplies_by_the_volume_field(self) -> None:
        """Soap is the exception, and it is the one that inverts.

            Monto = Cantidad × VolumenUnidadConsumo × ImpuestoUnidad

        The volume field holds GRAMS here, `CantidadUnidadMedida` is unused, and
        the unit amount MULTIPLIES the volume where a beverage divides by it:
        6 × 90 g × 1.5 = 810.
        """
        result = _run(
            self.calc,
            [
                _make_tax(
                    TaxType.ISEBEC,
                    sf_quantity=D("1"),
                    sf_volume=D("90"),
                    sf_amount=D("1.5"),
                )
            ],
            subtotal=D("1000"),
            cabys=CabysSpecialPrefix.ISEBEC_TOILET_SOAP.value + "01",
            detail_quantity=D("6"),
        )
        assert result.per_tax[0].amount == D("810.00000")

    def test_ipt_06_per_unit_with_detail_quantity(self) -> None:
        # detail_quantity (3) × qty (4) × unit (5) = 60. IPT does not adjust base.
        result = _run(
            self.calc,
            [_make_tax(TaxType.IPT, sf_quantity=D("4"), sf_amount=D("5"))],
            subtotal=D("1000"),
            detail_quantity=D("3"),
        )
        assert result.per_tax[0].amount == D("60")
        assert result.base_amount == D("1000")

    def test_ivace_07_manual_base_override(self) -> None:
        # Manual base 2000 × 13% = 260 (regardless of the subtotal of 1000).
        result = self.calc.compute_line_taxes(
            taxes=[_make_tax(TaxType.IVACE, rate=D("13"))],
            subtotal=D("1000"),
            detail_quantity=D("1"),
            cabys_code=None,
            monto_total_original=D("1000"),
            ivace_base_override=D("2000"),
        )
        assert result.per_tax[0].amount == D("260")
        assert result.base_amount == D("2000")
        assert result.iva_tax_total == D("260")

    def test_ivarbu_08_factor_times_subtotal(self) -> None:
        # factor 0.13 × subtotal 1000 = 130.
        result = _run(
            self.calc,
            [_make_tax(TaxType.IVARBU, factor=D("0.13"))],
            subtotal=D("1000"),
        )
        assert result.per_tax[0].amount == D("130")
        assert result.iva_tax_total == D("130")

    def test_isec_12_fixed_percentage(self) -> None:
        # 5% × 1000 = 50; ISEC grows the base. Special-fields are required by
        # the DTO validator (§7.5) but the math reads from `tax_rate`.
        result = _run(
            self.calc,
            [
                _make_tax(
                    TaxType.ISEC,
                    rate=D("5"),
                    sf_quantity=D("1"),
                    sf_amount=D("1"),
                )
            ],
            subtotal=D("1000"),
        )
        assert result.per_tax[0].amount == D("50")
        assert result.base_amount == D("1050")

    def test_others_99_prices_off_the_subtotal_not_the_excise_base(self) -> None:
        """99 is rate-driven, and every rate-driven code bills the SUBTOTAL.

        ISC still grows the IVA base to 1100, but OTHERS is 5% × 1000 = 50, not
        5% × 1100. The excise-inclusive base belongs to the IVA family alone —
        the biller builds 02/12/99 against `line_subtotal` — and -45 checks the
        amount against the base the row itself declares.
        """
        taxes = [
            _make_tax(TaxType.ISC, rate=D("10")),
            _make_tax(TaxType.OTHERS, rate=D("5")),
        ]
        result = _run(self.calc, taxes, subtotal=D("1000"))
        others_rows = [r for r in result.per_tax if r.tax_type_id == TaxType.OTHERS.value]
        assert len(others_rows) == 1
        assert others_rows[0].amount == D("50")
        assert others_rows[0].base_amount == D("1000")
        assert result.base_amount == D("1100")

    def test_royalty_bonus_routes_iva_to_factory_assumed(self) -> None:
        # 13% IVA on 1000 = 130, but routed to factory_assumed when royalty/bonus present.
        result = self.calc.compute_line_taxes(
            taxes=[_make_tax(TaxType.IVA, rate=D("13"))],
            subtotal=D("1000"),
            detail_quantity=D("1"),
            cabys_code=None,
            royalty_bonus_present=True,
            monto_total_original=D("1000"),
        )
        assert result.iva_tax_total == D("0")
        assert result.factory_assumed_tax == D("130")
        assert result.per_tax[0].factory_assumed_amount == D("130")

    def test_royalty_bonus_uses_pre_discount_base_for_iva(self) -> None:
        # §7.1: post-discount subtotal is 900 but pre-discount original is
        # 1000, so 13% IVA must compute on 1000 (=130), not on 900 (=117).
        result = self.calc.compute_line_taxes(
            taxes=[_make_tax(TaxType.IVA, rate=D("13"))],
            subtotal=D("900"),  # discount-eroded subtotal
            detail_quantity=D("1"),
            cabys_code=None,
            royalty_bonus_present=True,
            monto_total_original=D("1000"),
        )
        assert result.iva_tax_total == D("0")
        assert result.factory_assumed_tax == D("130")
        assert result.per_tax[0].amount == D("130")
        assert result.per_tax[0].base_amount == D("1000")

    def test_iva_collected_at_factory_is_assumed_without_any_discount(self) -> None:
        """`IVACobradoFabrica` 01 routes the IVA exactly like a royalty does.

        No discount is involved: the VAT was settled at the factory, so the
        issuer declares it as assumed. Hacienda answers -451 when it is not —
        "al usar el código 01 del IVA cobrado a nivel de fábrica ... se deben
        asumir los impuestos IVA en el campo ImpuestoAsumidoEmisorFabrica".
        """
        result = self.calc.compute_line_taxes(
            taxes=[_make_tax(TaxType.IVA, rate=D("13"))],
            subtotal=D("1000"),
            detail_quantity=D("1"),
            cabys_code=None,
            monto_total_original=D("1000"),
            iva_collected_factory="01",
        )
        assert result.net_tax == D("0")
        assert result.factory_assumed_tax == D("130")

    def test_nature_02_taxes_the_discounted_base_and_the_customer_pays(self) -> None:
        """Nature 02 has no special base any more.

        It used to price the IVA on `monto_total_original` while still charging
        the customer. Hacienda rejects that: -45 pins the tax to `base imponible
        × tarifa` and -454 pins the base to the discounted subtotal, so a
        customer-paid tax on the ORIGINAL amount cannot be expressed. The
        calculator simply never sets the flag now, so 900 × 13% = 117.
        """
        result = self.calc.compute_line_taxes(
            taxes=[_make_tax(TaxType.IVA, rate=D("13"))],
            subtotal=D("900"),
            detail_quantity=D("1"),
            cabys_code=None,
            royalty_bonus_present=False,
            monto_total_original=D("1000"),
        )
        assert result.net_tax == D("117")
        assert result.factory_assumed_tax == D("0")
        assert result.per_tax[0].base_amount == D("900")

    def test_royalty_bonus_does_not_reroute_the_collected_excises(self) -> None:
        # Royalty/bonus re-routes the IVA family only. ISC (02) is a COLLECTED
        # excise — it is not in FACTORY_ASSUMED_EXCISES — so 10% × 1000 = 100
        # stays in `other_tax_total` and in `net_tax` even on a royalty line.
        result = self.calc.compute_line_taxes(
            taxes=[
                _make_tax(TaxType.ISC, rate=D("10")),
                _make_tax(TaxType.IVA, rate=D("13")),
            ],
            subtotal=D("1000"),
            detail_quantity=D("1"),
            cabys_code=None,
            royalty_bonus_present=True,
            monto_total_original=D("1000"),
        )
        assert result.other_tax_total == D("100")
        # ISC contributes 100 to net_tax; IVA was re-routed to factory_assumed.
        assert result.net_tax == D("100")
        # IVA on pre-discount original 1000 × 13% = 130, routed to factory.
        assert result.factory_assumed_tax == D("130")
        # The ISC row must not carry a factory_assumed_amount.
        isc_rows = [r for r in result.per_tax if r.tax_type_id == TaxType.ISC.value]
        assert isc_rows[0].factory_assumed_amount == D("0")
