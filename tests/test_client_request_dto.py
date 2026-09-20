"""The client request contract — the two rules that were rejecting real edits.

There was no backend test for client update at all, which is why a verb/route
mismatch and a name rule the POS could not satisfy both shipped. Every other
resource in this service has a handler test; clients had none.
"""
import pytest
from pydantic import ValidationError

from app.dtos.requests.client_request_dto import ClientRequestDTO, IdentificationRequestDTO
from app.dtos.requests.client_status_request_dto import ClientStatusRequestDTO


class TestWhatIdentifiesAClient:
    def test_a_company_with_only_a_razon_social_is_accepted(self):
        """The reported save failure. The POS renders "Razón social" ->
        `business_name` for an EMPRESA and never fills `client_name`, so every
        company without a GLN was refused — while the form's own guard checked
        `business_name || client_gln` and let it through."""
        assert ClientRequestDTO(business_name="Acme S.A.").business_name

    @pytest.mark.parametrize("field", ["client_name", "business_name", "client_gln"])
    def test_any_one_name_is_enough(self, field):
        assert ClientRequestDTO(**{field: "x"})

    def test_a_client_with_no_name_at_all_is_refused(self):
        with pytest.raises(ValidationError):
            ClientRequestDTO(email="someone@example.com")


class TestIdentificationLength:
    """Mirrors `fe/pos-system/src/utils/idValidation.ts`. The two must agree, or
    the form accepts what the API refuses."""

    @pytest.mark.parametrize("code,number", [
        ("01", "112345678"),      # cédula física, raw
        ("01", "1-1234-5678"),    # cédula física, masked — the POS sends both
        ("02", "3102007223"),     # cédula jurídica
        ("02", "3-102-007223"),
        ("03", "11223344556"),    # DIMEX, 11
        ("03", "112233445566"),   # DIMEX, 12
        ("04", "1234567890"),     # NITE
        ("05", "AB1234"),         # passport — alphanumeric, counted whole
        ("05", "X12345678901"),
    ])
    def test_valid_numbers_are_accepted(self, code, number):
        assert IdentificationRequestDTO(code=code, number=number)

    @pytest.mark.parametrize("code,number", [
        ("01", "11234567"),       # 8 digits
        ("02", "310200722"),      # 9 — the flat min_length=9 used to allow this
        ("03", "1122334455"),     # 10, DIMEX needs 11
        ("05", "A1"),             # too short for a passport
    ])
    def test_wrong_lengths_are_refused(self, code, number):
        with pytest.raises(ValidationError):
            IdentificationRequestDTO(code=code, number=number)

    def test_a_passport_is_not_counted_by_its_digits(self):
        """`AB1234` has four digits and six characters. Counting digits would
        refuse every alphanumeric passport."""
        assert IdentificationRequestDTO(code="05", number="AB1234")

    def test_an_unknown_code_is_not_length_checked(self):
        """A catalog this service does not know about must not be guessed at."""
        assert IdentificationRequestDTO(code="99", number="whatever")

    def test_a_number_without_a_code_is_left_alone(self):
        assert IdentificationRequestDTO(number="112345678")


class TestClientStatus:
    @pytest.mark.parametrize("status", [1, 2, 3])
    def test_the_three_client_statuses_are_accepted(self, status):
        assert ClientStatusRequestDTO(status=status).status == status

    @pytest.mark.parametrize("status", [0, 4, 5])
    def test_order_statuses_are_refused(self, status):
        """This endpoint borrowed the shared `StatusRequestDTO`, documented as
        "Order status (1=pending … 5=cancelled)" and bounded 1..5, so it
        accepted 4 and 5 — values a client has no meaning for."""
        with pytest.raises(ValidationError):
            ClientStatusRequestDTO(status=status)
