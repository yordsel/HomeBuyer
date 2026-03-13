"""Shared formatting utilities for prices and display values.

Consolidates price formatting logic previously duplicated across
``services/fun_facts.py`` and ``services/accumulator.py``.
"""

from __future__ import annotations


def fmt_price(val: float | int | None) -> str:
    """Format a price as $X,XXX,XXX or $X.XM for millions.

    Examples::

        >>> fmt_price(1_500_000)
        '$1.5M'
        >>> fmt_price(1_000_000)
        '$1M'
        >>> fmt_price(750_000)
        '$750,000'
        >>> fmt_price(None)
        'N/A'
    """
    if val is None:
        return "N/A"
    val = int(val)
    if val >= 1_000_000:
        m = val / 1_000_000
        # Use one decimal if not a round number of millions
        return f"${m:.1f}M" if val % 100_000 else f"${m:.0f}M"
    return f"${val:,}"
