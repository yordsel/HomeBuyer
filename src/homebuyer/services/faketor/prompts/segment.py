"""SegmentContext prompt component.

Detected segment, buyer profile, confidence. This is the segment-aware
component that renders differently based on classification.

Phase D-1 (#38) of Epic #23.
Updated for multi-segment classification (#82).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homebuyer.services.faketor.prompts.templates import get_segment_template
from homebuyer.services.faketor.state.buyer import BuyerProfile

if TYPE_CHECKING:
    from homebuyer.services.faketor.classification import SegmentCandidate

logger = logging.getLogger(__name__)


def render(
    segment_id: str | None,
    segment_confidence: float,
    profile: BuyerProfile,
    candidates: list[SegmentCandidate] | None = None,
    idk_fields: dict[str, str] | None = None,
) -> str:
    """Render the segment context prompt fragment.

    Returns empty string if confidence is too low (<0.1) to be useful.
    For low confidence (0.1–0.3), returns the fallback elicitation prompt.
    For reasonable confidence (>0.3), returns the segment-specific template.

    When ``candidates`` is provided and confidence is below the threshold,
    renders a SEGMENT ALTERNATIVES block with disambiguation guidance
    instead of the generic confidence nudge.
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

    # Append disambiguation or confidence nudge when classification is uncertain
    if segment_confidence < _CONFIDENCE_NUDGE_THRESHOLD:
        alternatives_block = _build_alternatives_block(
            segment_id, segment_confidence, candidates
        )
        if alternatives_block:
            rendered = rendered + "\n\n" + alternatives_block
        else:
            # Fall back to generic confidence nudge if no alternatives
            nudge = _build_confidence_nudge(segment_confidence, profile)
            if nudge:
                rendered = rendered + "\n\n" + nudge

    # Append idk fields block if any ambiguous signals were detected
    idk_block = _build_idk_block(idk_fields)
    if idk_block:
        rendered = rendered + "\n\n" + idk_block

    return rendered


# The 4 core factors the classifier uses to determine segment
_CORE_FACTORS = [
    ("capital", "budget or savings amount"),
    ("income", "household income"),
    ("owns_current_home", "whether they currently own or rent"),
    ("equity", "equity in current property (if they own)"),
]

_CONFIDENCE_NUDGE_THRESHOLD = 0.6

# Maximum gap between primary and alternative to show as "also possible"
_ALTERNATIVE_GAP_THRESHOLD = 0.15


def _build_alternatives_block(
    primary_id: str,
    primary_confidence: float,
    candidates: list[SegmentCandidate] | None,
) -> str:
    """Build a SEGMENT ALTERNATIVES block for ambiguous classifications.

    Shows close alternatives and a targeted disambiguation question
    derived from the distinguishing factor between the top two candidates.
    Returns empty string if no meaningful alternatives exist.
    """
    if not candidates or len(candidates) < 2:
        return ""

    # Find alternatives close in confidence to the primary
    close_alternatives = [
        c for c in candidates
        if c.segment_id != primary_id
        and (primary_confidence - c.confidence) <= _ALTERNATIVE_GAP_THRESHOLD
        and c.confidence > 0.15
    ]

    if not close_alternatives:
        return ""

    # Build the segment names in human-readable form
    def _format_segment(seg_id: str) -> str:
        return seg_id.replace("_", " ").upper()

    confidence_pct = int(primary_confidence * 100)

    lines = [
        "=== SEGMENT ALTERNATIVES ===",
        f"Primary: {_format_segment(primary_id)} ({confidence_pct}%)",
    ]

    for alt in close_alternatives:
        alt_pct = int(alt.confidence * 100)
        lines.append(
            f"Also possible: {_format_segment(alt.segment_id)} ({alt_pct}%)"
            + (f" — distinguishing factor: {alt.distinguishing_factor}"
               if alt.distinguishing_factor else "")
        )

    # Use the top alternative's distinguishing factor for the question
    top_alt = close_alternatives[0]
    if top_alt.distinguishing_factor:
        lines.append("")
        lines.append(
            f"To narrow this down, after answering the user's question, "
            f"naturally ask about: {top_alt.distinguishing_factor}. "
            f"Keep it conversational — one question woven into your response."
        )

    lines.append("=== END SEGMENT ALTERNATIVES ===")
    return "\n".join(lines)


def _build_confidence_nudge(confidence: float, profile: BuyerProfile) -> str:
    """Build a nudge instruction when segment confidence is low.

    Tells the LLM which profile factors are missing and asks it to
    naturally elicit them after answering the user's question.
    Used as fallback when no alternatives are available.
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


_IDK_FIELD_LABELS: dict[str, str] = {
    "intent": "whether they want to live in the property or invest",
    "owns_current_home": "whether they currently own a home",
    "is_first_time_buyer": "whether this is their first purchase",
}


def _build_idk_block(idk_fields: dict[str, str] | None) -> str:
    """Build a block surfacing ambiguous extraction signals for Sonnet.

    When Haiku returns 'idk' for a field, it means there's a contextual
    signal but no explicit statement. Sonnet should either reason about
    it or ask a targeted clarifying question.
    """
    if not idk_fields:
        return ""

    lines = ["=== AMBIGUOUS SIGNALS ==="]
    lines.append(
        "The following were detected as likely but not explicitly stated. "
        "You may reason about them or ask a brief clarifying question:"
    )
    for field_name, evidence in idk_fields.items():
        label = _IDK_FIELD_LABELS.get(field_name, field_name)
        lines.append(f"- Possible: {label} (evidence: \"{evidence}\")")
    lines.append("=== END AMBIGUOUS SIGNALS ===")
    return "\n".join(lines)


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
