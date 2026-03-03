"""Date parsing and range helpers."""

import re
from datetime import date, datetime
from typing import Optional


# Redfin uses "Month-DD-YYYY" format like "June-16-2025"
_REDFIN_DATE_PATTERN = re.compile(
    r"^(\w+)-(\d{1,2})-(\d{4})$"
)

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_redfin_date(date_str: str) -> Optional[date]:
    """Parse a Redfin date string like 'June-16-2025' into a date object.

    Returns None if the string cannot be parsed.
    """
    if not date_str or not date_str.strip():
        return None

    match = _REDFIN_DATE_PATTERN.match(date_str.strip())
    if not match:
        # Try ISO format as fallback
        try:
            return date.fromisoformat(date_str.strip())
        except ValueError:
            return None

    month_name, day_str, year_str = match.groups()
    month = _MONTH_MAP.get(month_name.lower())
    if month is None:
        return None

    try:
        return date(int(year_str), month, int(day_str))
    except ValueError:
        return None


def parse_fred_date(date_str: str) -> Optional[date]:
    """Parse a FRED date string (YYYY-MM-DD) into a date object."""
    if not date_str or not date_str.strip():
        return None
    try:
        return date.fromisoformat(date_str.strip())
    except ValueError:
        return None


def date_range_days(start: date, end: date) -> int:
    """Return the number of days between two dates."""
    return (end - start).days
