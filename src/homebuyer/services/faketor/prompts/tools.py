"""ToolInstructions prompt component.

When to use which tool, anti-patterns (no loops). Changes only
when tools are added/removed — not segment-aware.

Phase D-1 (#38) of Epic #23.
"""

from __future__ import annotations


def render() -> str:
    """Render the tool instructions prompt fragment."""
    return """\
=== TOOL INSTRUCTIONS ===
REGULATIONS KNOWLEDGE BASE:
Use lookup_regulation BEFORE telling users to check the municipal code. \
Covers all 32+ zoning code definitions (R-1, R-1H, R-2, R-2A, R-2AH, C-SA, \
C-W, MUR, ES-R, etc.), ADU/JADU rules, SB 9, Middle Housing Ordinance, BESO, \
transfer tax, rent control, permitting, and hillside overlay. For property-specific \
zoning analysis, use get_development_potential instead.

GLOSSARY KNOWLEDGE BASE:
Use lookup_glossary_term when a user asks "what is X" for financial/real estate \
concepts, when you use jargon, or when tool results contain unfamiliar metrics.

TOOL SEQUENCING:
- lookup_property → get_development_potential (for specific addresses)
- search_properties → drill into top results with per-property tools
- Use query_database for ranking questions (precomputed_scenarios table)
- generate_investment_prospectus for comprehensive reports (supports \
from_working_set=true)

ANTI-PATTERNS:
- NEVER loop per-property analysis tools across multiple properties
- Do NOT use lookup_property when the user wants to search/find
- Do NOT call get_market_summary if market conditions are already provided
=== END TOOL INSTRUCTIONS ==="""
