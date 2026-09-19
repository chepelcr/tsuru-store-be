"""The order-date coercion, pinned.

These columns held `DD/MM/YYYY` from the Excel import and `YYYY-MM-DD` from the
POS, in the same VARCHAR, and are becoming real dates (migration d3e4f5a6b7c8).
`as_date` is what lets every reader work on both sides of that migration.

The case that matters most is the ambiguous one: 12 of 45 live rows have a day
<= 12, so "02/03/2026" is either 2 March or 3 February depending on who reads it.
Postgres's DateStyle here is MDY, which is why a bare cast gets those wrong and
why this helper never delegates to one.

Run: `python -m pytest tests/test_order_dates_unit.py -q`
"""

from datetime import date, datetime

import pytest

from app.utils.order_dates import DISPLAY_FORMAT, as_date, as_display, as_iso


class TestAsDate:
    @pytest.mark.parametrize("raw,expected", [
        # Day-first, and the day is <= 12 — the shape a naive cast misreads.
        ("02/03/2026", date(2026, 3, 2)),
        ("09/02/2026", date(2026, 2, 9)),
        # Day-first, unambiguous.
        ("25/05/2026", date(2026, 5, 25)),
        # ISO, as the POS and the storefront write it.
        ("2026-09-14", date(2026, 9, 14)),
        ("2026-09-14T00:00:00", date(2026, 9, 14)),
    ])
    def test_parses_both_formats(self, raw, expected):
        assert as_date(raw) == expected

    def test_day_first_is_never_read_as_month_first(self):
        """The whole reason this helper exists."""
        assert as_date("09/02/2026") == date(2026, 2, 9)     # 9 February
        assert as_date("09/02/2026") != date(2026, 9, 2)     # not 2 September

    @pytest.mark.parametrize("raw,expected", [
        (date(2026, 1, 5), date(2026, 1, 5)),
        (datetime(2026, 1, 5, 13, 30), date(2026, 1, 5)),
    ])
    def test_passes_through_real_dates(self, raw, expected):
        """After the migration the column hands back a date already."""
        assert as_date(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "not a date", "13/13/2026"])
    def test_absent_rather_than_invented(self, raw):
        """An unparseable date must not become a plausible wrong one."""
        assert as_date(raw) is None

    def test_tolerates_padding(self):
        assert as_date("  04/06/2026  ") == date(2026, 6, 4)


class TestFormatting:
    def test_display_is_day_first(self):
        # What a PDF, a ticket, an email and a spreadsheet cell expect.
        assert as_display("2026-09-14") == "14/09/2026"
        assert DISPLAY_FORMAT == "%d/%m/%Y"

    def test_iso_is_for_the_wire(self):
        assert as_iso("14/09/2026") == "2026-09-14"

    def test_the_two_formats_round_trip(self):
        assert as_iso(as_display("2026-09-14")) == "2026-09-14"

    def test_absent_display_is_the_default(self):
        assert as_display(None) == ""
        assert as_display(None, default="—") == "—"
        assert as_iso(None) is None


class TestSearchDateRanges:
    """Date filters on a DATE column, which is where two traps met.

    While the column was VARCHAR, a `deliveryDate` range was a raw STRING
    comparison — day-first lexicographic, so "02/03/2026" sorted before
    "19/02/2026" and an ISO-dated manual order never matched a DD/MM range at
    all. Once the column became a real date the remaining trap was the cast: this
    server's DateStyle is MDY, so handing Postgres '02/03/2026' as text gets 3
    February, and handing it a range as text is refused outright with
    `operator does not exist: date >= character varying`.
    """

    @staticmethod
    def _date_column():
        from sqlalchemy import Column, Date
        return Column("delivery_date", Date)

    def test_recognises_a_date_column(self):
        from sqlalchemy import Column, DateTime, String

        from app.utils.search_utils import SearchUtils

        assert SearchUtils._is_date_column(self._date_column()) is True
        # A timestamp is left alone — rewriting it would change the question.
        assert SearchUtils._is_date_column(Column("created_on", DateTime)) is False
        assert SearchUtils._is_date_column(Column("name", String(20))) is False

    @pytest.mark.parametrize("low,high", [
        ("2026-03-01", "2026-03-31"),        # what the POS sends
        ("01/03/2026", "31/03/2026"),        # what an older client sends
    ])
    def test_both_range_shapes_become_dates(self, low, high):
        from app.utils.search_utils import SearchUtils

        bounds = SearchUtils._range_bounds(self._date_column(), [low, high])
        assert bounds == (date(2026, 3, 1), date(2026, 3, 31))

    def test_an_unparseable_end_leaves_the_range_alone(self):
        """Both ends or neither — a half-typed range matches nothing."""
        from app.utils.search_utils import SearchUtils

        bounds = SearchUtils._range_bounds(self._date_column(), ["2026-03-01", "garbage"])
        assert bounds == ("2026-03-01", "garbage")

    def test_a_non_date_column_is_untouched(self):
        from sqlalchemy import Column, String

        from app.utils.search_utils import SearchUtils

        bounds = SearchUtils._range_bounds(Column("code", String(20)), ["a", "b"])
        assert bounds == ("a", "b")
