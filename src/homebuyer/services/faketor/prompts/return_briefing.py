"""Return briefing prompt component for returning users.

When a returning user resumes after a break, and the market has changed
materially, this component injects a RETURN CONTEXT block into the system
prompt. The LLM naturally weaves the briefing into its first response —
no separate resume endpoint needed.

Phase G-4 (#68) of Epic #23.
"""

from __future__ import annotations

from homebuyer.services.faketor.state.context import ResearchContext
from homebuyer.services.faketor.state.market import MarketDelta


def render(context: ResearchContext) -> str:
    """Render the return briefing prompt fragment.

    Returns a RETURN CONTEXT block if market_delta is non-null and has
    material changes. Returns empty string otherwise (new user, no delta,
    or no material changes).
    """
    delta = context.market_delta
    if delta is None:
        return ""

    if not delta.any_material:
        return ""

    parts = ["=== RETURN CONTEXT (welcome this user back) ==="]
    parts.append(
        "The user is returning after a break. Key changes since their last visit:"
    )
    parts.append("")

    # Market changes
    market_changes = _render_market_changes(delta)
    if market_changes:
        parts.append("MARKET CHANGES:")
        parts.extend(market_changes)
        parts.append("")

    # Focus property status
    focus = context.property.focus_property
    if focus and focus.address:
        parts.append("FOCUS PROPERTY:")
        parts.append(f"  - {focus.address} (last known status: {focus.last_known_status})")
        parts.append("  - Check if status has changed and brief the user.")
        parts.append("")

    # Stale analyses
    stale = context.property.get_stale_analyses(
        context.market.snapshot_at, delta,
    )
    if stale:
        parts.append("STALE ANALYSES (may need re-running):")
        for prop_id, address, record in stale:
            parts.append(f"  - {record.tool_name} for {address} (property #{prop_id})")
        parts.append("")

    # Buyer profile recap
    profile = context.buyer.profile
    profile_parts = _render_profile_recap(profile)
    if profile_parts:
        parts.append("BUYER PROFILE RECAP:")
        parts.extend(profile_parts)
        parts.append("")

    # Instructions for the LLM
    parts.append("INSTRUCTIONS:")
    parts.append(
        "- Welcome the user back naturally (don't be robotic about it)."
    )
    parts.append(
        "- Briefly mention the most impactful market changes and what they "
        "mean for this buyer's situation."
    )
    parts.append(
        "- If they had a focus property, check its status and mention any changes."
    )
    parts.append(
        "- Offer to re-run stale analyses with updated market data."
    )
    parts.append(
        "- Do NOT dump all changes at once — lead with what matters most."
    )
    parts.append("=== END RETURN CONTEXT ===")

    return "\n".join(parts)


def _render_market_changes(delta: MarketDelta) -> list[str]:
    """Render material market changes as bullet points."""
    lines: list[str] = []

    if delta.rate_material:
        direction = "up" if delta.rate_change > 0 else "down"
        lines.append(
            f"  - Mortgage rates moved {direction} by "
            f"{abs(delta.rate_change):.2f}% "
            f"({delta.rate_change_pct:+.1f}% relative)"
        )

    if delta.price_material:
        direction = "up" if delta.median_price_change > 0 else "down"
        lines.append(
            f"  - Berkeley median price {direction} "
            f"${abs(delta.median_price_change):,} "
            f"({delta.median_price_change_pct:+.1f}%)"
        )

    if delta.inventory_material:
        direction = "increased" if delta.inventory_change > 0 else "decreased"
        lines.append(
            f"  - Inventory {direction} by {abs(delta.inventory_change)} listings "
            f"({delta.inventory_change_pct:+.1f}%)"
        )

    return lines


def _render_profile_recap(profile) -> list[str]:
    """Render a brief recap of the buyer profile."""
    lines: list[str] = []

    if profile.intent:
        lines.append(f"  - Intent: {profile.intent}")
    if profile.capital is not None:
        lines.append(f"  - Available capital: ${profile.capital:,}")
    if profile.income is not None:
        lines.append(f"  - Annual income: ${profile.income:,}")
    if profile.current_rent is not None:
        lines.append(f"  - Current rent: ${profile.current_rent:,}/mo")

    return lines
