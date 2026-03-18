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
        AnalysisSpec("compute_true_cost", ("property_context",), "True monthly cost breakdown"),
        AnalysisSpec("rent_vs_buy", ("property_context",), "Rent vs buy comparison"),
    ],
    (STRETCHER, RequestType.AFFORDABILITY): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
        AnalysisSpec("compute_true_cost", ("property_context",), "True monthly cost breakdown"),
        AnalysisSpec("rent_vs_buy", ("property_context",), "Rent vs buy comparison"),
    ],

    # --- First-Time Buyer ---
    (FIRST_TIME_BUYER, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_comparable_sales", ("property_context",), "Recent comp sales"),
        AnalysisSpec("compute_true_cost", ("property_context",), "True monthly cost breakdown"),
        AnalysisSpec("pmi_model", ("property_context",), "PMI cost and timeline"),
    ],
    (FIRST_TIME_BUYER, RequestType.AFFORDABILITY): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
        AnalysisSpec("pmi_model", ("property_context",), "PMI cost and timeline"),
    ],

    # --- Down Payment Constrained ---
    (DOWN_PAYMENT_CONSTRAINED, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("pmi_model", ("property_context",), "PMI cost and timeline"),
        AnalysisSpec("compute_true_cost", ("property_context",), "True monthly cost breakdown"),
    ],
    (DOWN_PAYMENT_CONSTRAINED, RequestType.AFFORDABILITY): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
        AnalysisSpec("pmi_model", ("property_context",), "PMI cost and timeline"),
    ],

    # --- Equity-Trapped Upgrader ---
    (EQUITY_TRAPPED_UPGRADER, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_comparable_sales", ("property_context",), "Recent comp sales"),
        AnalysisSpec("rate_penalty", ("property_context", "buyer_profile"), "Rate lock penalty"),
    ],
    (EQUITY_TRAPPED_UPGRADER, RequestType.INVESTMENT_ANALYSIS): [
        AnalysisSpec("dual_property_model", ("property_context", "buyer_profile"), "Dual property strategy"),
    ],

    # --- Competitive Bidder ---
    (COMPETITIVE_BIDDER, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_comparable_sales", ("property_context",), "Recent comp sales"),
        AnalysisSpec("competition_assessment", ("property_context",), "Market competition assessment"),
    ],

    # --- Not Viable ---
    (NOT_VIABLE, RequestType.AFFORDABILITY): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
        AnalysisSpec("adjacent_market_comparison", ("buyer_profile",), "Adjacent market comparison"),
    ],

    # --- Cash Buyer ---
    (CASH_BUYER, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_comparable_sales", ("property_context",), "Recent comp sales"),
        AnalysisSpec("appreciation_stress_test", ("property_context",), "Appreciation scenarios"),
    ],
    (CASH_BUYER, RequestType.INVESTMENT_ANALYSIS): [
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
    ],

    # --- Equity-Leveraging Investor ---
    (EQUITY_LEVERAGING_INVESTOR, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
        AnalysisSpec("dual_property_model", ("property_context", "buyer_profile"), "Dual property strategy"),
    ],
    (EQUITY_LEVERAGING_INVESTOR, RequestType.INVESTMENT_ANALYSIS): [
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
    ],

    # --- Leveraged Investor ---
    (LEVERAGED_INVESTOR, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
        AnalysisSpec("appreciation_stress_test", ("property_context",), "Appreciation scenarios"),
    ],
    (LEVERAGED_INVESTOR, RequestType.INVESTMENT_ANALYSIS): [
        AnalysisSpec("estimate_rental_income", ("property_context",), "Rental yield estimate"),
        AnalysisSpec("rate_penalty", ("property_context", "buyer_profile"), "Rate penalty analysis"),
    ],

    # --- Value-Add Investor ---
    (VALUE_ADD_INVESTOR, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_development_potential", ("property_context",), "Zoning & dev potential"),
        AnalysisSpec("get_price_prediction", ("property_context",), "As-is fair value"),
        AnalysisSpec("appreciation_stress_test", ("property_context",), "Appreciation scenarios"),
    ],
    (VALUE_ADD_INVESTOR, RequestType.DEVELOPMENT_QUESTION): [
        AnalysisSpec("get_development_potential", ("property_context",), "Zoning & dev potential"),
    ],

    # --- Appreciation Bettor ---
    (APPRECIATION_BETTOR, RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", ("property_context",), "Fair value estimate"),
        AnalysisSpec("get_neighborhood_stats", ("property_context",), "Neighborhood trends"),
        AnalysisSpec("appreciation_stress_test", ("property_context",), "Appreciation scenarios"),
    ],
    (APPRECIATION_BETTOR, RequestType.MARKET_QUESTION): [
        AnalysisSpec("get_market_summary", (), "Current market conditions"),
        AnalysisSpec("neighborhood_lifestyle", (), "Neighborhood lifestyle comparison"),
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


# ---------------------------------------------------------------------------
# Dynamic suggestion chips — context-aware prompts for the frontend
# ---------------------------------------------------------------------------

# Intent discovery chips (turn 1, no segment yet)
_INTENT_DISCOVERY_CHIPS = [
    "I'm looking to buy my first home",
    "I want to invest in rental property",
    "I'm thinking of upgrading from my current home",
    "Just exploring the market",
]

# Capacity chips by intent (turn 2, intent known but no financials)
_CAPACITY_CHIPS_OCCUPY = [
    "Let me share my financial details",
    "Show me what's available under $1M",
    "What neighborhoods fit my budget?",
    "What are the true monthly costs of owning?",
]

_CAPACITY_CHIPS_INVEST = [
    "I have equity in my current home",
    "I'm looking to buy with cash",
    "I want to use leverage for maximum returns",
    "Show me cash-flow positive properties",
]

# Segment-aware chips (turn 3+, segment known)
_SEGMENT_CHIPS: dict[str, list[str]] = {
    NOT_VIABLE: [
        "What can I afford in nearby cities?",
        "How can I improve my buying position?",
        "What's the cheapest neighborhood in Berkeley?",
        "Show me condos under $600K",
    ],
    STRETCHER: [
        "What's the true monthly cost for this property?",
        "Should I rent or buy at these prices?",
        "Show me properties I can actually afford",
        "What neighborhoods have the best value?",
    ],
    FIRST_TIME_BUYER: [
        "Break down the true monthly cost",
        "What will my PMI cost look like?",
        "Rent vs buy — which makes more sense?",
        "What first-time buyer programs are available?",
    ],
    DOWN_PAYMENT_CONSTRAINED: [
        "How much PMI will I pay and when does it drop off?",
        "Should I wait to save more for a down payment?",
        "What's the true monthly cost with 10% down?",
        "Show me homes where PMI is worth it",
    ],
    EQUITY_TRAPPED_UPGRADER: [
        "What's my rate lock penalty if I move?",
        "Can I keep my current home and buy another?",
        "Compare my current payment to a new mortgage",
        "Show me homes worth the rate penalty",
    ],
    COMPETITIVE_BIDDER: [
        "How competitive is this neighborhood?",
        "What's the typical overbid percentage here?",
        "Show me less competitive neighborhoods",
        "What properties are sitting on the market?",
    ],
    CASH_BUYER: [
        "Rank properties by investment yield",
        "Run an appreciation stress test",
        "Compare cap rates across neighborhoods",
        "Generate an investment prospectus",
    ],
    EQUITY_LEVERAGING_INVESTOR: [
        "Analyze a dual property strategy with my equity",
        "Rank properties by cash-on-cash return",
        "What can my equity unlock as a down payment?",
        "Compare HELOC vs cash-out refi for extraction",
    ],
    LEVERAGED_INVESTOR: [
        "Show me properties with positive leverage spread",
        "What's the rate penalty on a new investment loan?",
        "Run an appreciation stress test",
        "Rank properties by DSCR",
    ],
    VALUE_ADD_INVESTOR: [
        "What's the development potential here?",
        "Run an appreciation stress test with renovations",
        "What improvements add the most value?",
        "Compare ADU vs lot split returns",
    ],
    APPRECIATION_BETTOR: [
        "Run appreciation scenarios for this property",
        "Which neighborhoods are appreciating fastest?",
        "Compare exit strategies at different horizons",
        "What are the lifestyle factors for neighborhoods?",
    ],
}


def suggest_chips(
    context: ResearchContext,
    has_property: bool = False,
    tools_used: list[str] | None = None,
) -> list[str]:
    """Generate context-aware suggestion chips for the frontend.

    Returns 4 chips based on conversation state:
    - No segment, no intent → intent discovery chips
    - Intent known, no financials → capacity chips
    - Segment known → segment-specific job chips
    - Property active → property-specific follow-ups

    The orchestrator calls this after each turn and emits the result
    as a ``suggestion_chips`` SSE event.
    """
    segment_id = context.buyer.segment_id if context.buyer else None
    intent = context.buyer.profile.intent if context.buyer else None
    has_financials = bool(
        context.buyer
        and context.buyer.profile.capital is not None
    )

    # If property is active and segment is known, give segment+property chips
    if has_property and segment_id and segment_id in _SEGMENT_CHIPS:
        return _SEGMENT_CHIPS[segment_id][:4]

    # Segment known → segment-specific chips
    if segment_id and segment_id in _SEGMENT_CHIPS:
        return _SEGMENT_CHIPS[segment_id][:4]

    # Intent known but no financials → capacity discovery
    if intent == "invest":
        return _CAPACITY_CHIPS_INVEST[:4]
    if intent == "occupy" and not has_financials:
        return _CAPACITY_CHIPS_OCCUPY[:4]

    # Nothing known → intent discovery
    return _INTENT_DISCOVERY_CHIPS[:4]
