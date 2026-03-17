"""SegmentContext prompt component.

Detected segment, buyer profile, confidence. This is the segment-aware
component that renders differently based on classification.

Phase D-1 (#38) of Epic #23.
"""

from __future__ import annotations

from homebuyer.services.faketor.prompts.templates import get_segment_template
from homebuyer.services.faketor.state.buyer import BuyerProfile


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
        return ""

    return template(
        confidence=segment_confidence,
        profile_summary=profile_summary,
        profile=profile,
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
