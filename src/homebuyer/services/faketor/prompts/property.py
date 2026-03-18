"""PropertyContext prompt component.

Focus property, working set summary, and prior analyses. Changes per
turn based on the current property state.

Phase D-1 (#38) of Epic #23.
"""

from __future__ import annotations

from homebuyer.services.faketor.state.property import PropertyState


def render(property_state: PropertyState | None) -> str:
    """Render the property context prompt fragment.

    Returns empty string if no property state or nothing to report.
    """
    if property_state is None:
        return ""

    parts: list[str] = []

    # Focus property
    if property_state.focus_property:
        fp = property_state.focus_property
        focus_line = f"Focus property: {fp.address}"
        # Include price/neighborhood from property_context if available
        ctx = fp.property_context
        if ctx.get("price") is not None:
            focus_line += f" (${ctx['price']:,})"
        if ctx.get("neighborhood"):
            focus_line += f" in {ctx['neighborhood']}"
        parts.append(focus_line)

    # Filter intent summary
    if property_state.filter_intent:
        fi = property_state.filter_intent
        if fi.description:
            parts.append(f"Current search: {fi.description}")

    # Prior analyses
    if property_state.analyses:
        analysis_summaries: list[str] = []
        for prop_id, analysis in list(property_state.analyses.items())[:5]:
            tools_used = ", ".join(list(analysis.analyses.keys())[:3])
            addr = analysis.address or f"Property #{prop_id}"
            analysis_summaries.append(f"  - {addr}: analyzed with {tools_used}")

        if analysis_summaries:
            parts.append("Prior analyses completed:")
            parts.extend(analysis_summaries)

    if not parts:
        return ""

    return "=== PROPERTY CONTEXT ===\n" + "\n".join(parts) + "\n=== END PROPERTY CONTEXT ==="
