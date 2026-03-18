"""SegmentContext prompt component.

Detected segment, buyer profile, confidence. This is the segment-aware
component that renders differently based on classification.

Phase D-1 (#38) of Epic #23.
"""

from __future__ import annotations

import logging

from homebuyer.services.faketor.prompts.templates import get_segment_template
from homebuyer.services.faketor.state.buyer import BuyerProfile

logger = logging.getLogger(__name__)


def render(
    segment_id: str | None,
    segment_confidence: float,
    profile: BuyerProfile,
) -> str:
    """Render the segment context prompt fragment.

    Returns empty string if confidence is too low (<0.1) to be useful.
    For low confidence (0.1–0.3), returns the fallback elicitation prompt.
    For reasonable confidence (>0.3), returns the segment-specific template.
    """
    if segment_id is None or segment_confidence < 0.1:
        return ""

    # Low confidence: use fallback elicitation
    if segment_confidence < 0.3:
        from homebuyer.services.faketor.prompts.fallback import render as render_fallback
        return render_fallback(profile)

    # Build profile summary for the template
    profile_summary = _build_profile_summary(profile)

    # Get the segment-specific template
    template = get_segment_template(segment_id)
    if template is None:
        logger.warning("No prompt template registered for segment %r", segment_id)
        return ""

    rendered = template(
        confidence=segment_confidence,
        profile_summary=profile_summary,
        profile=profile,
    )

    # Append confidence-aware nudge when classification is uncertain
    nudge = _build_confidence_nudge(segment_confidence, profile)
    if nudge:
        rendered = rendered + "\n\n" + nudge

    return rendered


# The 4 core factors the classifier uses to determine segment
_CORE_FACTORS = [
    ("capital", "budget or savings amount"),
    ("income", "household income"),
    ("owns_current_home", "whether they currently own or rent"),
    ("equity", "equity in current property (if they own)"),
]

_CONFIDENCE_NUDGE_THRESHOLD = 0.6


def _build_confidence_nudge(confidence: float, profile: BuyerProfile) -> str:
    """Build a nudge instruction when segment confidence is low.

    Tells the LLM which profile factors are missing and asks it to
    naturally elicit them after answering the user's question.
    """
    if confidence >= _CONFIDENCE_NUDGE_THRESHOLD:
        return ""

    missing = []
    for field_name, description in _CORE_FACTORS:
        if getattr(profile, field_name) is None:
            missing.append(description)

    if not missing:
        return ""

    missing_str = ", ".join(missing)
    confidence_pct = int(confidence * 100)

    return (
        f"=== CONFIDENCE NOTE ===\n"
        f"Segment confidence is low ({confidence_pct}%). "
        f"The segment guidance above is a best guess — prioritize answering "
        f"the user's explicit question over the segment's primary job.\n"
        f"\n"
        f"After answering their question, naturally ask about one of these "
        f"missing factors to improve your understanding: {missing_str}.\n"
        f"Keep it conversational — weave it into your response, don't list "
        f"questions like a form.\n"
        f"=== END CONFIDENCE NOTE ==="
    )


def _build_profile_summary(profile: BuyerProfile) -> str:
    """Build a one-line profile summary for inclusion in segment block."""
    parts: list[str] = []

    if profile.intent:
        parts.append(f"Intent: {profile.intent}")

    if profile.capital is not None:
        parts.append(f"${profile.capital:,} capital")

    if profile.equity is not None:
        parts.append(f"${profile.equity:,} equity")

    if profile.income is not None:
        parts.append(f"${profile.income:,} income")

    if profile.current_rent is not None:
        parts.append(f"${profile.current_rent:,}/mo rent")

    if profile.owns_current_home is True:
        parts.append("Owns current home")
    elif profile.owns_current_home is False:
        parts.append("Renter")

    if profile.is_first_time_buyer is True:
        parts.append("First-time buyer")

    if profile.sophistication:
        parts.append(f"Sophistication: {profile.sophistication}")

    return ". ".join(parts) if parts else "Limited profile data available"
