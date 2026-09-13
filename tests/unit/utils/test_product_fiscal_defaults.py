"""The product fiscal defaults and the tax-row repair.

These matter because `repair_tax_rows` is run against a live database by
`scripts/backfill_product_fiscal_defaults.py`, and its job is to fill in a rate
code that a document will otherwise be rejected for. Getting the 0% case wrong
would write a WRONG tax treatment onto real products rather than leaving them
visibly broken.
"""

from app.utils.product_fiscal_defaults import (
    DEFAULT_UNIT_MEASURE,
    GENERAL_RATE_CODE,
    default_iva_row,
    repair_tax_rows,
)


class _Row:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def _product(taxes=None, cabys=None):
    return _Row(taxes=taxes, cabys=cabys)


class TestDefaultIvaRow:
    def test_falls_back_to_the_general_rate_with_no_cabys(self) -> None:
        row = default_iva_row(_product())
        assert row["tax_type_id"] == "01"
        assert row["tax_rate"]["code"] == GENERAL_RATE_CODE
        assert row["tax_rate"]["percentage"] == 13.0

    def test_prefers_the_rate_on_the_products_cabys(self) -> None:
        # The CABYS taxonomy exists precisely to say which rate applies, so a
        # reduced or exempt article gets its real rate rather than the general one.
        cabys = _Row(tax_rate=_Row(id=4, percentage=4.0, code="04"))
        row = default_iva_row(_product(cabys=cabys))
        # `id` is the Hacienda rate CODE, not the data-services row id (4).
        assert row["tax_rate"] == {"id": "04", "percentage": 4.0, "code": "04"}

    def test_id_is_never_a_data_services_row_id(self) -> None:
        # The row id is environment-specific — a reseed renumbers it — and means
        # nothing to Hacienda. Same class of bug as sending DB id "17" as a
        # discount_type_id.
        cabys = _Row(tax_rate=_Row(id=8, percentage=13.0, code="08"))
        row = default_iva_row(_product(cabys=cabys))
        assert row["tax_rate"]["id"] == row["tax_rate"]["code"] == "08"

    def test_always_carries_a_code_even_when_the_cabys_lacks_one(self) -> None:
        cabys = _Row(tax_rate=_Row(id=None, percentage=13.0, code=None))
        row = default_iva_row(_product(cabys=cabys))
        assert row["tax_rate"]["code"] == GENERAL_RATE_CODE

    def test_the_default_unit_is_a_discrete_unit(self) -> None:
        assert DEFAULT_UNIT_MEASURE == "Unid"


class TestRepairTaxRows:
    def test_derives_the_missing_rate_code_from_the_percentage(self) -> None:
        # This is the population the broken save path created.
        product = _product(taxes=[{"tax_type_id": "01", "tax_rate": {"percentage": 13.0}}])
        changes = repair_tax_rows(product)
        assert product.taxes[0]["tax_rate"]["code"] == "08"
        # `id` is set to the code at the same time, not left absent.
        assert product.taxes[0]["tax_rate"]["id"] == "08"
        assert changes and "rate code <- 08" in changes[0]

    def test_rewrites_a_data_services_row_id_to_the_rate_code(self) -> None:
        # Rows written before this held the catalog row id ("8") where the
        # Nota 8.1 code ("08") belongs, and the product form bound its rate
        # selector to that id.
        product = _product(
            taxes=[{"tax_type_id": "01", "tax_rate": {"id": "8", "code": "08", "percentage": 13.0}}]
        )
        changes = repair_tax_rows(product)
        assert product.taxes[0]["tax_rate"]["id"] == "08"
        assert any("rate id <- 08" in c for c in changes)

    def test_fills_an_absent_id_from_the_code(self) -> None:
        product = _product(
            taxes=[{"tax_type_id": "01", "tax_rate": {"id": None, "code": "08", "percentage": 13.0}}]
        )
        repair_tax_rows(product)
        assert product.taxes[0]["tax_rate"]["id"] == "08"

    def test_a_row_already_correct_reports_no_change(self) -> None:
        product = _product(
            taxes=[{"tax_type_id": "01", "tax_rate": {"id": "08", "code": "08", "percentage": 13.0}}]
        )
        assert repair_tax_rows(product) == []

    def test_derives_each_unambiguous_percentage(self) -> None:
        for percentage, code in ((0.5, "09"), (1.0, "02"), (2.0, "03"), (4.0, "04"), (13.0, "08")):
            product = _product(taxes=[{"tax_type_id": "01", "tax_rate": {"percentage": percentage}}])
            repair_tax_rows(product)
            assert product.taxes[0]["tax_rate"]["code"] == code

    def test_refuses_to_guess_a_code_for_0_percent(self) -> None:
        # Exento (10), no sujeto (11) and crédito pleno (01) are all 0%. Writing
        # one of them would put a wrong tax treatment on every document built
        # from this product.
        product = _product(taxes=[{"tax_type_id": "01", "tax_rate": {"percentage": 0.0}}])
        changes = repair_tax_rows(product)
        assert "code" not in product.taxes[0]["tax_rate"]
        assert changes and "NEEDS ATTENTION" in changes[0]

    def test_never_overwrites_a_code_the_row_already_has(self) -> None:
        # 13% carrying an explicit "exenta" code is odd but it is the
        # operator's, and only the `id` is brought into line with it.
        product = _product(
            taxes=[{"tax_type_id": "01", "tax_rate": {"id": "10", "percentage": 13.0, "code": "10"}}]
        )
        assert repair_tax_rows(product) == []
        assert product.taxes[0]["tax_rate"]["code"] == "10"

    def test_fills_a_missing_percentage_from_the_code(self) -> None:
        product = _product(taxes=[{"tax_type_id": "01", "tax_rate": {"code": "04"}}])
        repair_tax_rows(product)
        assert product.taxes[0]["tax_rate"]["percentage"] == 4.0

    def test_repairs_the_whole_iva_family(self) -> None:
        for code in ("01", "07", "08"):
            product = _product(taxes=[{"tax_type_id": code, "tax_rate": {"percentage": 13.0}}])
            repair_tax_rows(product)
            assert product.taxes[0]["tax_rate"]["code"] == "08"

    def test_leaves_non_iva_taxes_alone(self) -> None:
        # Only the IVA family derives its rate from a code; ISC carries a rate.
        product = _product(taxes=[{"tax_type_id": "02", "tax_rate": {"percentage": 10.0}}])
        assert repair_tax_rows(product) == []
        assert "code" not in product.taxes[0]["tax_rate"]

    def test_leaves_an_excise_with_no_rate_block_alone(self) -> None:
        product = _product(taxes=[{"tax_type_id": "04", "special_fields": {"quantity": 0.355}}])
        assert repair_tax_rows(product) == []

    def test_reassigns_the_list_so_sqlalchemy_persists_it(self) -> None:
        # SQLAlchemy does not track in-place edits to a JSON column, so a mutated
        # list would never reach the database.
        original = [{"tax_type_id": "01", "tax_rate": {"percentage": 13.0}}]
        product = _product(taxes=original)
        repair_tax_rows(product)
        assert product.taxes is not original

    def test_no_taxes_is_a_no_op(self) -> None:
        assert repair_tax_rows(_product()) == []
        assert repair_tax_rows(_product(taxes=[])) == []
