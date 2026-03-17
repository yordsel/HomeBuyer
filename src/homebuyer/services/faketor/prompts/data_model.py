"""DataModelRules prompt component.

Record types, property categories, query rules. Changes only when
the data model changes — not segment-aware.

Phase D-1 (#38) of Epic #23.
"""

from __future__ import annotations


def render() -> str:
    """Render the data model rules prompt fragment."""
    return """\
=== DATA MODEL ===
CAPABILITIES (use your tools!):
- Property lookup: search any Berkeley property by address (17,000+ parcels)
- Property search: find by neighborhood, zoning, lot size, price, beds/baths, \
year built, ADU/SB9 eligibility
- Development potential: zoning, ADU, Middle Housing, SB 9 lot splitting
- Improvement ROI: ML-simulated value impact of renovations
- Comparable sales and neighborhood statistics
- Market-wide trends, mortgage rates, inventory
- Price prediction from the ML model
- Sell-vs-hold analysis with appreciation projections and rental yield
- Rental income estimation with data-driven rent estimates
- Investment scenario comparison (as-is, ADU, SB9, multi-unit)
- Permit history: building permits filed for any property
- Database queries: ad-hoc SQL for counts, averages, distributions
- Regulations knowledge base: Berkeley zoning, ADU/JADU, SB 9, Middle Housing, \
BESO, transfer tax, rent control, permitting, hillside overlay
- Glossary knowledge base: 70+ financial and real estate term definitions

RULES:
- If the user asks something you can answer with a tool, use it
- When the user mentions a specific address, use lookup_property first
- Use search_properties for finding/searching (not lookup_property)
- When following up search results with get_development_potential, \
ALWAYS pass the property_id from the search results
- For aggregate/analytical questions (counts, averages, "how many"), \
use query_database
- NEVER call per-property analysis tools in a loop for multiple properties — \
use query_database or generate_investment_prospectus instead
- Tool responses include *_note fields — use these verbatim
=== END DATA MODEL ==="""
