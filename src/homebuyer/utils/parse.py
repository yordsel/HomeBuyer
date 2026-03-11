"""Shared parsing utilities for safe type conversion."""


def safe_float(val) -> float | None:
    """Convert a value to float, returning None on failure or NaN."""
    if val is None:
        return None
    try:
        result = float(val)
        if result != result:  # NaN check
            return None
        return result
    except (ValueError, TypeError):
        return None


def safe_int(val) -> int | None:
    """Convert a value to int, returning None on failure."""
    if val is None:
        return None
    try:
        result = float(val)
        if result != result:  # NaN check
            return None
        return int(result)
    except (ValueError, TypeError):
        return None
