"""Segment prompt templates — one renderer per segment.

Each segment gets a prompt injection block composed of tone, framing rules,
proactive behavior, and term definitions policy. These are substantial
(20-40 lines each) and differ qualitatively across segments.

Phase D-2 (#39) of Epic #23.
"""

from __future__ import annotations

from typing import Callable

# Type for segment template renderers
SegmentRenderer = Callable[..., str]

# Registry of segment template renderers
_TEMPLATES: dict[str, SegmentRenderer] = {}


def register(segment_id: str) -> Callable[[SegmentRenderer], SegmentRenderer]:
    """Decorator to register a segment template renderer."""
    def wrapper(fn: SegmentRenderer) -> SegmentRenderer:
        _TEMPLATES[segment_id] = fn
        return fn
    return wrapper


def get_segment_template(segment_id: str) -> SegmentRenderer | None:
    """Get the renderer for a segment, or None if not found."""
    return _TEMPLATES.get(segment_id)


# Import all template modules to trigger registration
from homebuyer.services.faketor.prompts.templates import (  # noqa: E402, F401
    not_viable,
    stretcher,
    first_time_buyer,
    down_payment_constrained,
    equity_trapped_upgrader,
    competitive_bidder,
    cash_buyer,
    equity_leveraging_investor,
    leveraged_investor,
    value_add_investor,
    appreciation_bettor,
)

__all__ = ["get_segment_template", "register"]
