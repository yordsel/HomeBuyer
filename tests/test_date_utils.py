"""Tests for date parsing utilities."""

from datetime import date

from homebuyer.utils.date_utils import parse_redfin_date, parse_fred_date


def test_parse_redfin_date_standard():
    """Standard Redfin date format parses correctly."""
    assert parse_redfin_date("June-16-2025") == date(2025, 6, 16)
    assert parse_redfin_date("January-01-2021") == date(2021, 1, 1)
    assert parse_redfin_date("December-31-2024") == date(2024, 12, 31)


def test_parse_redfin_date_case_insensitive():
    """Month names are case-insensitive."""
    assert parse_redfin_date("june-16-2025") == date(2025, 6, 16)
    assert parse_redfin_date("JUNE-16-2025") == date(2025, 6, 16)


def test_parse_redfin_date_iso_fallback():
    """ISO format works as a fallback."""
    assert parse_redfin_date("2025-06-16") == date(2025, 6, 16)


def test_parse_redfin_date_empty():
    """Empty/null strings return None."""
    assert parse_redfin_date("") is None
    assert parse_redfin_date("   ") is None


def test_parse_redfin_date_invalid():
    """Invalid strings return None."""
    assert parse_redfin_date("not-a-date") is None
    assert parse_redfin_date("Smarch-32-2025") is None


def test_parse_fred_date():
    """FRED ISO dates parse correctly."""
    assert parse_fred_date("2024-01-04") == date(2024, 1, 4)
    assert parse_fred_date("") is None
    assert parse_fred_date("not-a-date") is None
