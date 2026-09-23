"""Branch/client phones are stored with the ISO country code, whatever arrived."""
from app.models.country import Country
from app.services.phone_country import iso_country_code, phone_digits

CATALOG = {
    "188": Country(iso_code="188", iso="CR", phone_code="+506"),
    "840": Country(iso_code="840", iso="US", phone_code="+1"),
    "124": Country(iso_code="124", iso="CA", phone_code="+1"),
    "659": Country(iso_code="659", iso="KN", phone_code="+1-869"),
}


class _Scalars:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class FakeSession:
    def get(self, model, key):
        return CATALOG.get(key)

    def execute(self, stmt):
        wanted = {str(v) for v in stmt.whereclause.right.value}
        return _Scalars([c.iso_code for c in CATALOG.values() if c.phone_code in wanted])


def test_an_iso_code_is_kept():
    assert iso_country_code(FakeSession(), "188") == "188"


def test_an_older_event_dialing_code_becomes_iso():
    assert iso_country_code(FakeSession(), "506") == "188"
    assert iso_country_code(FakeSession(), "+506") == "188"


def test_a_shared_dialing_code_falls_back_to_costa_rica():
    assert iso_country_code(FakeSession(), "1") == "188"


def test_country_splits_a_dashed_dialing_code():
    assert (CATALOG["659"].dial_code, CATALOG["659"].dial_area) == ("1", "869")
    assert (CATALOG["188"].dial_code, CATALOG["188"].dial_area) == ("506", None)


def test_phone_digits():
    assert phone_digits("+506 8989-0512") == "50689890512"
    assert phone_digits("") is None
