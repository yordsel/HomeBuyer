"""Tests for job resolution: request classification, proactive analysis, and turn planning.

Phase E-1 (#45), E-2 (#46), E-3 (#47) of Epic #23.
"""

import pytest

from homebuyer.services.faketor.classification import (
    APPRECIATION_BETTOR,
    CASH_BUYER,
    COMPETITIVE_BIDDER,
    FIRST_TIME_BUYER,
    NOT_VIABLE,
    STRETCHER,
    VALUE_ADD_INVESTOR,
    ALL_SEGMENTS,
    SegmentResult,
)
from homebuyer.services.faketor.jobs import (
    AnalysisSpec,
    FramingDirective,
    JobResolver,
    PROACTIVE_ANALYSES,
    RequestType,
    TurnPlan,
    classify_request,
    _available_context,
    _build_framing,
    _lead_with,
    _tool_priority,
)
from homebuyer.services.faketor.state.buyer import BuyerProfile
from homebuyer.services.faketor.state.context import ResearchContext
from homebuyer.services.faketor.state.market import (
    BerkeleyWideMetrics,
    MarketSnapshot,
)
from homebuyer.services.faketor.state.property import (
    FocusProperty,
    PropertyState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    has_market: bool = True,
    has_property: bool = False,
    has_intent: bool = True,
) -> ResearchContext:
    ctx = ResearchContext(user_id="test-user")
    if has_market:
        ctx.market = MarketSnapshot(
            mortgage_rate_30yr=6.5,
            berkeley_wide=BerkeleyWideMetrics(median_sale_price=1_300_000),
        )
    if has_property:
        ctx.property = PropertyState()
        ctx.property.focus_property = FocusProperty(
            property_id=123,
            address="1234 Cedar St",
            property_context={"price": 1_200_000},
        )
    if has_intent:
        ctx.buyer.profile = BuyerProfile(intent="occupy")
    return ctx


def _segment_result(segment_id: str, confidence: float = 0.75) -> SegmentResult:
    return SegmentResult(
        segment_id=segment_id,
        confidence=confidence,
        reasoning="test",
        factor_coverage=0.5,
    )


# ---------------------------------------------------------------------------
# RequestType classification tests (E-1, #45)
# ---------------------------------------------------------------------------


class TestClassifyRequest:
    """Pattern-based request classification."""

    def test_property_evaluation_with_address(self):
        assert classify_request("Tell me about 1234 Cedar St") == RequestType.PROPERTY_EVALUATION

    def test_property_evaluation_street_types(self):
        assert classify_request("1500 University Ave") == RequestType.PROPERTY_EVALUATION
        assert classify_request("2200 Milvia Rd") == RequestType.PROPERTY_EVALUATION
        assert classify_request("800 Jones Blvd") == RequestType.PROPERTY_EVALUATION

    def test_property_evaluation_this_property(self):
        assert classify_request("Analyze this property") == RequestType.PROPERTY_EVALUATION

    def test_search_find_homes(self):
        assert classify_request("Find homes in North Berkeley") == RequestType.SEARCH

    def test_search_looking_for(self):
        assert classify_request("I'm looking for properties under $1M") == RequestType.SEARCH

    def test_search_show_me(self):
        assert classify_request("Show me houses with 3 bedrooms") == RequestType.SEARCH

    def test_search_find_with_criteria(self):
        assert classify_request("Find something in the hills with a view") == RequestType.SEARCH

    def test_development_question_adu(self):
        assert classify_request("Can I build an ADU here?") == RequestType.DEVELOPMENT_QUESTION

    def test_development_question_zoning(self):
        assert classify_request("What's the zoning for this lot?") == RequestType.DEVELOPMENT_QUESTION

    def test_development_question_sb9(self):
        assert classify_request("Is this eligible for SB9 lot split?") == RequestType.DEVELOPMENT_QUESTION

    def test_sell_hold(self):
        assert classify_request("Should I sell or hold my current home?") == RequestType.SELL_HOLD

    def test_investment_analysis_roi(self):
        assert classify_request("What's the ROI on this property?") == RequestType.INVESTMENT_ANALYSIS

    def test_investment_analysis_cash_flow(self):
        assert classify_request("What would the cash flow be?") == RequestType.INVESTMENT_ANALYSIS

    def test_investment_analysis_cap_rate(self):
        assert classify_request("What's the cap rate?") == RequestType.INVESTMENT_ANALYSIS

    def test_investment_analysis_rent_out(self):
        assert classify_request("Could I rent it out?") == RequestType.INVESTMENT_ANALYSIS

    def test_affordability_budget(self):
        assert classify_request("Can I afford a $1.2M house?") == RequestType.AFFORDABILITY

    def test_affordability_monthly_payment(self):
        assert classify_request("What would the monthly payment be?") == RequestType.AFFORDABILITY

    def test_affordability_down_payment(self):
        assert classify_request("What's needed for a down payment?") == RequestType.AFFORDABILITY

    def test_affordability_pmi(self):
        assert classify_request("Would I need to pay PMI?") == RequestType.AFFORDABILITY

    def test_comparison(self):
        assert classify_request("Compare these two properties") == RequestType.COMPARISON

    def test_comparison_vs(self):
        assert classify_request("1234 Cedar vs 5678 Elm") == RequestType.COMPARISON

    def test_market_question_trends(self):
        assert classify_request("How is the market right now?") == RequestType.MARKET_QUESTION

    def test_market_question_rates(self):
        assert classify_request("How are interest rates trending?") == RequestType.MARKET_QUESTION

    def test_market_question_inventory(self):
        assert classify_request("How much inventory is there?") == RequestType.MARKET_QUESTION

    def test_process_question_how_to(self):
        assert classify_request("How does the closing process work?") == RequestType.PROCESS_QUESTION

    def test_process_question_what_is(self):
        assert classify_request("What is an appraisal contingency?") == RequestType.PROCESS_QUESTION

    def test_general_fallback(self):
        assert classify_request("Hello, nice to meet you") == RequestType.GENERAL

    def test_general_unrelated(self):
        assert classify_request("What's the weather like?") == RequestType.GENERAL

    def test_case_insensitive(self):
        assert classify_request("FIND HOMES IN BERKELEY") == RequestType.SEARCH


# ---------------------------------------------------------------------------
# AnalysisSpec tests (E-2, #46)
# ---------------------------------------------------------------------------


class TestAnalysisSpec:
    def test_can_run_no_requirements(self):
        spec = AnalysisSpec("get_market_summary")
        assert spec.can_run(set()) is True

    def test_can_run_with_met_requirements(self):
        spec = AnalysisSpec("get_price_prediction", ("property_context",))
        assert spec.can_run({"property_context", "market_snapshot"}) is True

    def test_cannot_run_missing_requirement(self):
        spec = AnalysisSpec("get_price_prediction", ("property_context",))
        assert spec.can_run({"market_snapshot"}) is False

    def test_can_run_multiple_requirements(self):
        spec = AnalysisSpec("test_tool", ("property_context", "buyer_profile"))
        assert spec.can_run({"property_context", "buyer_profile"}) is True
        assert spec.can_run({"property_context"}) is False

    def test_frozen(self):
        spec = AnalysisSpec("test", (), "desc")
        with pytest.raises(AttributeError):
            spec.tool_name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Proactive analysis registry tests
# ---------------------------------------------------------------------------


class TestProactiveAnalysesRegistry:
    def test_stretcher_property_eval_has_prediction(self):
        analyses = PROACTIVE_ANALYSES[(STRETCHER, RequestType.PROPERTY_EVALUATION)]
        tool_names = {a.tool_name for a in analyses}
        assert "get_price_prediction" in tool_names

    def test_value_add_investor_has_dev_potential(self):
        analyses = PROACTIVE_ANALYSES[(VALUE_ADD_INVESTOR, RequestType.PROPERTY_EVALUATION)]
        tool_names = {a.tool_name for a in analyses}
        assert "get_development_potential" in tool_names

    def test_cash_buyer_investment_has_rental(self):
        analyses = PROACTIVE_ANALYSES[(CASH_BUYER, RequestType.INVESTMENT_ANALYSIS)]
        tool_names = {a.tool_name for a in analyses}
        assert "estimate_rental_income" in tool_names

    def test_appreciation_bettor_market_has_summary(self):
        analyses = PROACTIVE_ANALYSES[(APPRECIATION_BETTOR, RequestType.MARKET_QUESTION)]
        tool_names = {a.tool_name for a in analyses}
        assert "get_market_summary" in tool_names

    def test_no_entry_returns_empty(self):
        """Missing (segment, request_type) key returns empty from .get()."""
        result = PROACTIVE_ANALYSES.get((NOT_VIABLE, RequestType.SEARCH), [])
        assert result == []


# ---------------------------------------------------------------------------
# Available context tests
# ---------------------------------------------------------------------------


class TestAvailableContext:
    def test_empty_context(self):
        ctx = ResearchContext(user_id="test")
        available = _available_context(ctx)
        assert available == set()

    def test_market_present(self):
        ctx = _make_context(has_market=True, has_property=False, has_intent=False)
        available = _available_context(ctx)
        assert "market_snapshot" in available

    def test_property_present(self):
        ctx = _make_context(has_market=False, has_property=True, has_intent=False)
        available = _available_context(ctx)
        assert "property_context" in available

    def test_intent_present(self):
        ctx = _make_context(has_market=False, has_property=False, has_intent=True)
        available = _available_context(ctx)
        assert "buyer_profile" in available

    def test_all_present(self):
        ctx = _make_context(has_market=True, has_property=True, has_intent=True)
        available = _available_context(ctx)
        assert available == {"market_snapshot", "property_context", "buyer_profile"}


# ---------------------------------------------------------------------------
# Framing and lead_with tests
# ---------------------------------------------------------------------------


class TestFraming:
    def test_no_segment_returns_empty(self):
        framing = _build_framing(None, RequestType.GENERAL)
        assert framing.tone == ""

    def test_stretcher_has_tone(self):
        framing = _build_framing(STRETCHER, RequestType.PROPERTY_EVALUATION)
        assert len(framing.tone) > 10

    def test_lead_with_stretcher_property_eval(self):
        result = _lead_with(STRETCHER, RequestType.PROPERTY_EVALUATION)
        assert "rent" in result.lower()

    def test_lead_with_competitive_bidder_property_eval(self):
        result = _lead_with(COMPETITIVE_BIDDER, RequestType.PROPERTY_EVALUATION)
        assert "bid" in result.lower()

    def test_lead_with_value_add_property_eval(self):
        result = _lead_with(VALUE_ADD_INVESTOR, RequestType.PROPERTY_EVALUATION)
        assert "development" in result.lower() or "zoning" in result.lower()

    def test_lead_with_affordability(self):
        result = _lead_with(STRETCHER, RequestType.AFFORDABILITY)
        assert "cost" in result.lower()

    def test_lead_with_investment(self):
        result = _lead_with(CASH_BUYER, RequestType.INVESTMENT_ANALYSIS)
        assert "return" in result.lower() or "cash flow" in result.lower()


# ---------------------------------------------------------------------------
# Tool priority tests
# ---------------------------------------------------------------------------


class TestToolPriority:
    def test_property_eval_basic(self):
        tools = _tool_priority(STRETCHER, RequestType.PROPERTY_EVALUATION)
        assert tools[0] == "lookup_property"
        assert "get_price_prediction" in tools

    def test_property_eval_value_add_includes_dev(self):
        tools = _tool_priority(VALUE_ADD_INVESTOR, RequestType.PROPERTY_EVALUATION)
        assert "get_development_potential" in tools

    def test_property_eval_investor_includes_rental(self):
        tools = _tool_priority(CASH_BUYER, RequestType.PROPERTY_EVALUATION)
        assert "estimate_rental_income" in tools

    def test_search(self):
        tools = _tool_priority(STRETCHER, RequestType.SEARCH)
        assert tools == ["search_properties"]

    def test_investment_analysis(self):
        tools = _tool_priority(CASH_BUYER, RequestType.INVESTMENT_ANALYSIS)
        assert "estimate_rental_income" in tools

    def test_development_question(self):
        tools = _tool_priority(VALUE_ADD_INVESTOR, RequestType.DEVELOPMENT_QUESTION)
        assert "get_development_potential" in tools

    def test_general_returns_empty(self):
        assert _tool_priority(STRETCHER, RequestType.GENERAL) == []


# ---------------------------------------------------------------------------
# JobResolver integration tests (E-3, #47)
# ---------------------------------------------------------------------------


class TestJobResolver:
    def setup_method(self):
        self.resolver = JobResolver()

    def test_resolve_basic(self):
        ctx = _make_context(has_property=True)
        segment = _segment_result(STRETCHER)
        plan = self.resolver.resolve("Tell me about 1234 Cedar St", segment, ctx)
        assert plan.request_type == RequestType.PROPERTY_EVALUATION
        assert plan.segment_id == STRETCHER
        assert len(plan.proactive_analyses) > 0
        assert plan.secondary_nudge is not None

    def test_resolve_filters_by_context(self):
        """Analyses requiring property_context are excluded when no property."""
        ctx = _make_context(has_property=False)
        segment = _segment_result(STRETCHER)
        plan = self.resolver.resolve("Tell me about 1234 Cedar St", segment, ctx)
        # Property-requiring analyses should be filtered out
        for analysis in plan.proactive_analyses:
            assert "property_context" not in analysis.requires

    def test_resolve_with_property_context(self):
        """Analyses requiring property_context are included when property present."""
        ctx = _make_context(has_property=True)
        segment = _segment_result(STRETCHER)
        plan = self.resolver.resolve("Tell me about 1234 Cedar St", segment, ctx)
        tool_names = {a.tool_name for a in plan.proactive_analyses}
        assert "get_price_prediction" in tool_names

    def test_resolve_no_segment(self):
        ctx = _make_context()
        plan = self.resolver.resolve("Hello there", None, ctx)
        assert plan.segment_id is None
        assert plan.proactive_analyses == []
        assert plan.secondary_nudge is None

    def test_resolve_general_request(self):
        ctx = _make_context()
        segment = _segment_result(STRETCHER)
        plan = self.resolver.resolve("Hello there", segment, ctx)
        assert plan.request_type == RequestType.GENERAL
        assert plan.segment_id == STRETCHER

    def test_all_segments_have_jobs(self):
        """Every segment has an entry in _SEGMENT_JOBS."""
        from homebuyer.services.faketor.jobs import _SEGMENT_JOBS
        for seg_id in ALL_SEGMENTS:
            assert seg_id in _SEGMENT_JOBS, f"Missing JTBD for {seg_id}"

    def test_all_segments_have_nudge(self):
        """Every segment has a secondary nudge."""
        from homebuyer.services.faketor.jobs import _SEGMENT_JOBS
        for seg_id in ALL_SEGMENTS:
            assert _SEGMENT_JOBS[seg_id].get("nudge"), f"Missing nudge for {seg_id}"

    def test_resolve_returns_turn_plan(self):
        ctx = _make_context()
        segment = _segment_result(FIRST_TIME_BUYER)
        plan = self.resolver.resolve("Can I afford this?", segment, ctx)
        assert isinstance(plan, TurnPlan)
        assert isinstance(plan.framing, FramingDirective)

    def test_classify_request_delegated(self):
        """JobResolver.classify_request delegates to module-level function."""
        assert self.resolver.classify_request("Find homes") == RequestType.SEARCH

    def test_resolve_investment_segment(self):
        ctx = _make_context(has_property=True)
        segment = _segment_result(VALUE_ADD_INVESTOR)
        plan = self.resolver.resolve("What's the development potential?", segment, ctx)
        assert plan.request_type == RequestType.DEVELOPMENT_QUESTION
        tool_names = {a.tool_name for a in plan.proactive_analyses}
        assert "get_development_potential" in tool_names
