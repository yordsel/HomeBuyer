"""Job resolution for the segment-driven Faketor redesign.

Translates a classified segment into a concrete turn plan: what analyses
to pre-execute, how to frame the response, and what secondary jobs to
weave in.

Phase E-1 (#45), E-2 (#46), E-3 (#47) of Epic #23.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from homebuyer.services.faketor.classification import (
    APPRECIATION_BETTOR,
    CASH_BUYER,
    COMPETITIVE_BIDDER,
    DOWN_PAYMENT_CONSTRAINED,
    EQUITY_LEVERAGING_INVESTOR,
    EQUITY_TRAPPED_UPGRADER,
    FIRST_TIME_BUYER,
    LEVERAGED_INVESTOR,
    NOT_VIABLE,
    STRETCHER,
    VALUE_ADD_INVESTOR,
    SegmentResult,
)
from homebuyer.services.faketor.state.context import ResearchContext


# ---------------------------------------------------------------------------
# RequestType — what the user is asking for
# ---------------------------------------------------------------------------


class RequestType(str, Enum):
    """Classification of the user's request intent."""

    PROPERTY_EVALUATION = "property_evaluation"
    SEARCH = "search"
    MARKET_QUESTION = "market_question"
    AFFORDABILITY = "affordability"
    INVESTMENT_ANALYSIS = "investment_analysis"
    COMPARISON = "comparison"
    DEVELOPMENT_QUESTION = "development_question"
    PROCESS_QUESTION = "process_question"
    SELL_HOLD = "sell_hold"
    GENERAL = "general"


# Pattern-based request classification (E-1, #45)
# Each entry: (compiled regex, RequestType)
# Order matters — first match wins
_REQUEST_PATTERNS: list[tuple[re.Pattern[str], RequestType]] = [
    # Property evaluation — specific address or "this property"
    (re.compile(
        r"(?:tell me about|analyze|evaluate|look up|what about|how is|show me)"
        r".*(?:\d{2,5}\s+\w+|\bthis\s+(?:property|house|home|place)\b)",
        re.IGNORECASE,
    ), RequestType.PROPERTY_EVALUATION),
    (re.compile(
        r"\b\d{2,5}\s+(?:[\w]+\s+)?"
        r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ct|court|way|pl|place)\b",
        re.IGNORECASE,
    ), RequestType.PROPERTY_EVALUATION),

    # Search — find, search, show me properties matching criteria
    (re.compile(
        r"(?:find|search|show me|list|looking for|any)\s+"
        r"(?:properties|homes|houses|lots|parcels|places)",
        re.IGNORECASE,
    ), RequestType.SEARCH),
    (re.compile(
        r"(?:find|search)\b.*(?:in|near|around|under|over|with|zoned)",
        re.IGNORECASE,
    ), RequestType.SEARCH),

    # Development question — ADU, zoning, SB9, permits, build
    (re.compile(
        r"\b(?:adu|jadu|sb\s*9|middle\s*housing|zoning|development|permit|build|"
        r"lot\s*split|setback|far\b|height\s*limit|accessory\s*dwelling)",
        re.IGNORECASE,
    ), RequestType.DEVELOPMENT_QUESTION),

    # Sell vs hold
    (re.compile(
        r"\b(?:sell\s+(?:or|vs|versus)\s+hold|should\s+i\s+sell|keep\s+or\s+sell|"
        r"hold\s+(?:or|vs)\s+sell)",
        re.IGNORECASE,
    ), RequestType.SELL_HOLD),

    # Investment analysis — ROI, cash flow, cap rate, rental income, invest
    (re.compile(
        r"\b(?:invest(?:ment)?|roi|cap\s*rate|cash\s*flow|rental\s*(?:income|yield)|"
        r"noi|dscr|cash.on.cash|irr|appreciation|prospectus|"
        r"rent\s+(?:it\s+)?out|income\s*property)",
        re.IGNORECASE,
    ), RequestType.INVESTMENT_ANALYSIS),

    # Affordability — budget, afford, monthly payment, down payment, mortgage
    (re.compile(
        r"\b(?:afford|budget|monthly\s*(?:payment|cost)|down\s*payment|"
        r"how\s*much\s*(?:can\s*i|house|home)|pmi|dti|"
        r"mortgage\s*(?:payment|rate|calculator)|pre.?approv)",
        re.IGNORECASE,
    ), RequestType.AFFORDABILITY),

    # Comparison — compare, vs, versus, which is better
    (re.compile(
        r"\b(?:compare|comparison|vs\.?|versus|which\s+(?:is|one)\s+better|"
        r"difference\s+between|side\s+by\s+side)",
        re.IGNORECASE,
    ), RequestType.COMPARISON),

    # Market question — market, trends, prices, inventory, rates
    (re.compile(
        r"\b(?:market|trend|median|inventory|housing\s*market|"
        r"interest\s*rate|mortgage\s*rate|price\s*trend|"
        r"how\s*(?:is|are)\s*(?:the\s*)?(?:market|prices|rates)|"
        r"months?\s*of\s*supply|days?\s*on\s*market)",
        re.IGNORECASE,
    ), RequestType.MARKET_QUESTION),

    # Process question — how to, what is, explain, process
    (re.compile(
        r"\b(?:how\s+(?:do|does|to|is)|what\s+(?:is|are|does)|explain|"
        r"(?:closing|escrow|offer|inspection|appraisal|contingency)\s+"
        r"(?:process|work|mean))",
        re.IGNORECASE,
    ), RequestType.PROCESS_QUESTION),
]


def classify_request(message: str) -> RequestType:
    """Classify a user message into a RequestType.

    Uses pattern matching (not LLM) — fast and deterministic.
    Falls back to GENERAL if no pattern matches.
    """
    for pattern, request_type in _REQUEST_PATTERNS:
        if pattern.search(message):
            return request_type
    return RequestType.GENERAL


# ---------------------------------------------------------------------------
# AnalysisSpec — what to pre-execute
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalysisSpec:
    """Specification for a proactive analysis to pre-execute."""

    tool_name: str
    requires: tuple[str, ...] = ()  # Required context keys
    description: str = ""

    def can_run(self, available: set[str]) -> bool:
        """Check if required context is available."""
        return all(r in available for r in self.requires)


# ---------------------------------------------------------------------------
# Proactive analysis registry (E-2, #46)
# ---------------------------------------------------------------------------

# Data-driven mapping: (segment_id, RequestType) → list of analyses to pre-execute.
# Adding a new segment or changing analysis for an existing one is a table update.
PROACTIVE_ANALYSES: dict[tuple[str, RequestType], list[AnalysisSpec]] = {
    # --- Stretcher ---
    (STRETCHER, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_comparable_sales", ("property_context",), "Recent comp sales"),
    ],
    (STRETCHER, RequestType.AFFORDABILITY): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
    ],

    # --- First-Time Buyer ---
    (FIRST_TIME_BUYER, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_comparable_sales", ("property_context",), "Recent comp sales"),
    ],
    (FIRST_TIME_BUYER, RequestType.AFFORDABILITY): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
    ],

    # --- Down Payment Constrained ---
    (DOWN_PAYMENT_CONSTRAINED, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
    ],
    (DOWN_PAYMENT_CONSTRAINED, RequestType.AFFORDABILITY): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
    ],

    # --- Equity-Trapped Upgrader ---
    (EQUITY_TRAPPED_UPGRADER, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_comparable_sales", ("property_context",), "Recent comp sales"),
    ],

    # --- Competitive Bidder ---
    (COMPETITIVE_BIDDER, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_comparable_sales", ("property_context",), "Recent comp sales"),
    ],

    # --- Not Viable ---
    (NOT_VIABLE, RequestType.AFFORDABILITY): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
    ],

    # --- Cash Buyer ---
    (CASH_BUYER, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_comparable_sales", ("property_context",), "Recent comp sales"),
    ],
    (CASH_BUYER, RequestType.INVESTMENT_ANALYSIS): [
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
    ],

    # --- Equity-Leveraging Investor ---
    (EQUITY_LEVERAGING_INVESTOR, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
    ],
    (EQUITY_LEVERAGING_INVESTOR, RequestType.INVESTMENT_ANALYSIS): [
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
    ],

    # --- Leveraged Investor ---
    (LEVERAGED_INVESTOR, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
    ],
    (LEVERAGED_INVESTOR, RequestType.INVESTMENT_ANALYSIS): [
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
    ],

    # --- Value-Add Investor ---
    (VALUE_ADD_INVESTOR, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_development_potential", ("property_context",), "Zoning & dev potential"),
        AnalysisSpec("get_price_prediction", ("property_context",), "As-is fair value"),
    ],
    (VALUE_ADD_INVESTOR, RequestType.DEVELOPMENT_QUESTION): [
        AnalysisSpec("get_development_potential", ("property_context",), "Zoning & dev potential"),
    ],

    # --- Appreciation Bettor ---
    (APPRECIATION_BETTOR, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_neighborhood_stats", ("property_context",), "Neighborhood trends"),
    ],
    (APPRECIATION_BETTOR, RequestType.MARKET_QUESTION): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
    ],
}


# ---------------------------------------------------------------------------
# TurnPlan + FramingDirective — output of job resolution
# ---------------------------------------------------------------------------


@dataclass
class FramingDirective:
    """How the LLM should frame its response for this turn."""

    tone: str = ""
    lead_with: str = ""  # What to emphasize first
    avoid: str = ""  # What NOT to do


@dataclass
class TurnPlan:
    """Concrete plan for a single chat turn."""

    request_type: RequestType = RequestType.GENERAL
    segment_id: str | None = None
    proactive_analyses: list[AnalysisSpec] = field(default_factory=list)
    framing: FramingDirective = field(default_factory=FramingDirective)
    secondary_nudge: str | None = None
    tool_priority: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Segment job definitions — primary/secondary JTBD per segment
# ---------------------------------------------------------------------------

_SEGMENT_JOBS: dict[str, dict[str, Any]] = {
    NOT_VIABLE: {
        "primary": "Help buyer understand what would need to change to become viable",
        "secondary": "Explore adjacent markets or assistance programs",
        "nudge": "Would you like to see what market conditions would make this viable?",
    },
    STRETCHER: {
        "primary": "Help buyer evaluate if buying makes financial sense vs renting",
        "secondary": "Surface true costs and risks beyond the mortgage payment",
        "nudge": "Want me to compare the true cost of ownership with your current rent?",
    },
    FIRST_TIME_BUYER: {
        "primary": "Help buyer understand what they're buying — true cost, not just price",
        "secondary": "Build market literacy for independent property evaluation",
        "nudge": "Would you like me to break down the full monthly cost for this property?",
    },
    DOWN_PAYMENT_CONSTRAINED: {
        "primary": "Evaluate true cost impact of lower down payment (PMI, higher monthly)",
        "secondary": "Compare loan programs and PMI payoff timelines",
        "nudge": "Want me to compare 10% down vs 20% down with specific dollar impacts?",
    },
    EQUITY_TRAPPED_UPGRADER: {
        "primary": "Quantify the rate penalty of moving",
        "secondary": "Explore alternatives (HELOC, bridge loans)",
        "nudge": "Want me to calculate the rate penalty of moving to this property?",
    },
    COMPETITIVE_BIDDER: {
        "primary": "Help calibrate bids — rational price given comps and competition",
        "secondary": "Identify less competitive supply in adjacent areas",
        "nudge": "Want me to synthesize the comps into a rational bid range?",
    },
    CASH_BUYER: {
        "primary": "Evaluate if property is a good deployment of capital vs alternatives",
        "secondary": "Quantify cash offer discount advantage",
        "nudge": "Want me to compare this property's yield against alternative investments?",
    },
    EQUITY_LEVERAGING_INVESTOR: {
        "primary": "Evaluate if return justifies cost of accessing equity",
        "secondary": "Model portfolio effect of adding this property",
        "nudge": "Want me to calculate the cost of accessing your equity vs projected yield?",
    },
    LEVERAGED_INVESTOR: {
        "primary": "Validate leverage thesis — does income cover debt service?",
        "secondary": "Stress-test assumptions at different rate scenarios",
        "nudge": "Want me to stress-test this at +50bps and +100bps rate scenarios?",
    },
    VALUE_ADD_INVESTOR: {
        "primary": "Find properties with development upside where the numbers work",
        "secondary": "Provide realistic timeline and regulatory pathway",
        "nudge": "Want me to check development potential and permit history?",
    },
    APPRECIATION_BETTOR: {
        "primary": "Evaluate if appreciation thesis is supported by data",
        "secondary": "Quantify negative carry and break-even appreciation rate",
        "nudge": "Want me to calculate the break-even appreciation rate for this property?",
    },
}


# ---------------------------------------------------------------------------
# JobResolver (E-3, #47)
# ---------------------------------------------------------------------------


class JobResolver:
    """Resolves segment + request into a concrete turn plan.

    The resolver knows:
    - What each segment's primary/secondary JTBD is (from design doc Section 3)
    - What proactive analyses each segment×request triggers (from Section 6.6.3)
    - How to frame results for each segment (from Section 6.7.3)
    """

    def classify_request(self, message: str) -> RequestType:
        """Classify user message into a RequestType. Pattern-based, not LLM."""
        return classify_request(message)

    def resolve(
        self,
        request_text: str,
        segment: SegmentResult | None,
        context: ResearchContext,
    ) -> TurnPlan:
        """Build a turn plan from the request and current state."""
        request_type = self.classify_request(request_text)
        segment_id = segment.segment_id if segment else None

        # Look up proactive analyses
        analyses: list[AnalysisSpec] = []
        if segment_id:
            key = (segment_id, request_type)
            analyses = list(PROACTIVE_ANALYSES.get(key, []))

        # Filter by available context
        available = _available_context(context)
        analyses = [a for a in analyses if a.can_run(available)]

        # Build framing directive
        framing = _build_framing(segment_id, request_type)

        # Get secondary nudge
        nudge = None
        if segment_id and segment_id in _SEGMENT_JOBS:
            nudge = _SEGMENT_JOBS[segment_id].get("nudge")

        # Build tool priority
        tool_priority = _tool_priority(segment_id, request_type)

        return TurnPlan(
            request_type=request_type,
            segment_id=segment_id,
            proactive_analyses=analyses,
            framing=framing,
            secondary_nudge=nudge,
            tool_priority=tool_priority,
        )


def _available_context(context: ResearchContext) -> set[str]:
    """Determine what context is available for proactive analysis."""
    available: set[str] = set()

    if context.market and context.market.mortgage_rate_30yr:
        available.add("market_snapshot")

    if context.property and context.property.focus_property:
        available.add("property_context")

    if context.buyer and context.buyer.profile.intent:
        available.add("buyer_profile")

    return available


def _build_framing(segment_id: str | None, request_type: RequestType) -> FramingDirective:
    """Build framing directive based on segment and request type."""
    if not segment_id or segment_id not in _SEGMENT_JOBS:
        return FramingDirective()

    job = _SEGMENT_JOBS[segment_id]

    # Default framing from the segment's primary job
    return FramingDirective(
        tone=job.get("primary", ""),
        lead_with=_lead_with(segment_id, request_type),
        avoid="",
    )


def _lead_with(segment_id: str, request_type: RequestType) -> str:
    """What to emphasize first based on segment × request type."""
    if request_type == RequestType.PROPERTY_EVALUATION:
        if segment_id == STRETCHER:
            return "true monthly cost compared to rent"
        if segment_id == COMPETITIVE_BIDDER:
            return "fair value and bid calibration"
        if segment_id == VALUE_ADD_INVESTOR:
            return "development potential and zoning"
        if segment_id in (CASH_BUYER, LEVERAGED_INVESTOR, EQUITY_LEVERAGING_INVESTOR):
            return "investment yield and return metrics"
        return "fair value estimate"

    if request_type == RequestType.AFFORDABILITY:
        return "true monthly cost breakdown"

    if request_type == RequestType.INVESTMENT_ANALYSIS:
        return "cash flow and return metrics"

    return ""


def _tool_priority(segment_id: str | None, request_type: RequestType) -> list[str]:
    """Preferred tool order for reactive (LLM-driven) use."""
    if request_type == RequestType.PROPERTY_EVALUATION:
        base = ["lookup_property", "get_price_prediction", "get_comparable_sales"]
        if segment_id == VALUE_ADD_INVESTOR:
            base.append("get_development_potential")
        if segment_id in (CASH_BUYER, LEVERAGED_INVESTOR, EQUITY_LEVERAGING_INVESTOR):
            base.append("estimate_rental_income")
        return base

    if request_type == RequestType.SEARCH:
        return ["search_properties"]

    if request_type == RequestType.INVESTMENT_ANALYSIS:
        return ["estimate_rental_income", "analyze_investment_scenarios", "get_price_prediction"]

    if request_type == RequestType.DEVELOPMENT_QUESTION:
        return ["get_development_potential", "lookup_permits", "lookup_regulation"]

    return []
