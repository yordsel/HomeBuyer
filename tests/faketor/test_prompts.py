"""Tests for prompt assembly components and full prompt composition.

Each component is tested in isolation. The full assembly is tested
with representative ResearchContext objects.

Phase D-6 (#43) of Epic #23.
"""

from homebuyer.services.faketor.classification import (
    ALL_SEGMENTS,
    CASH_BUYER,
    STRETCHER,
    VALUE_ADD_INVESTOR,
)
from homebuyer.services.faketor.prompts import PromptAssembler
from homebuyer.services.faketor.prompts import (
    data_model,
    market,
    personality,
    preexecuted,
    property,
    segment,
    tools,
)
from homebuyer.services.faketor.prompts.fallback import render as render_fallback
from homebuyer.services.faketor.prompts.templates import get_segment_template
from homebuyer.services.faketor.state.buyer import BuyerProfile, BuyerState
from homebuyer.services.faketor.state.context import ResearchContext
from homebuyer.services.faketor.state.market import (
    BerkeleyWideMetrics,
    MarketSnapshot,
)
from homebuyer.services.faketor.state.property import (
    FilterIntent,
    FocusProperty,
    PropertyState,
)  # noqa: F401 — FilterIntent used in filter_intent tests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market() -> MarketSnapshot:
    return MarketSnapshot(
        mortgage_rate_30yr=6.5,
        conforming_limit=766_550,
        berkeley_wide=BerkeleyWideMetrics(
            median_sale_price=1_300_000,
            median_list_price=1_250_000,
            median_ppsf=850,
            median_dom=18,
            avg_sale_to_list=1.05,
            inventory=120,
            months_of_supply=1.8,
        ),
    )


def _make_context(
    segment_id: str | None = STRETCHER,
    confidence: float = 0.72,
    intent: str = "occupy",
) -> ResearchContext:
    buyer = BuyerState()
    buyer.profile = BuyerProfile(
        intent=intent,
        capital=100_000,
        income=150_000,
        current_rent=2_800,
    )
    buyer.segment_id = segment_id
    buyer.segment_confidence = confidence

    ctx = ResearchContext(user_id="test-user")
    ctx.buyer = buyer
    ctx.market = _make_market()
    return ctx


# ---------------------------------------------------------------------------
# Individual component tests
# ---------------------------------------------------------------------------


class TestPersonality:
    def test_renders_non_empty(self):
        result = personality.render()
        assert len(result) > 100

    def test_has_delimiters(self):
        result = personality.render()
        assert "=== PERSONALITY ===" in result
        assert "=== END PERSONALITY ===" in result

    def test_contains_faketor_identity(self):
        result = personality.render()
        assert "Faketor" in result
        assert "Berkeley" in result


class TestDataModel:
    def test_renders_non_empty(self):
        result = data_model.render()
        assert len(result) > 100

    def test_has_delimiters(self):
        result = data_model.render()
        assert "=== DATA MODEL ===" in result
        assert "=== END DATA MODEL ===" in result

    def test_contains_capabilities(self):
        result = data_model.render()
        assert "Property lookup" in result
        assert "query_database" in result


class TestTools:
    def test_renders_non_empty(self):
        result = tools.render()
        assert len(result) > 100

    def test_has_delimiters(self):
        result = tools.render()
        assert "=== TOOL INSTRUCTIONS ===" in result
        assert "=== END TOOL INSTRUCTIONS ===" in result

    def test_contains_anti_patterns(self):
        result = tools.render()
        assert "NEVER loop" in result


class TestMarketContext:
    def test_renders_with_data(self):
        mkt = _make_market()
        result = market.render(mkt)
        assert "6.5%" in result
        assert "$1,300,000" in result
        assert "$850" in result
        assert "1.8" in result

    def test_has_delimiters(self):
        result = market.render(_make_market())
        assert "=== MARKET CONDITIONS" in result
        assert "=== END MARKET CONDITIONS ===" in result

    def test_returns_empty_for_none(self):
        assert market.render(None) == ""

    def test_skips_zero_default_fields(self):
        """Fields that default to 0 (not loaded) should NOT be rendered."""
        mkt = MarketSnapshot(
            mortgage_rate_30yr=6.5,
            berkeley_wide=BerkeleyWideMetrics(median_sale_price=1_300_000),
        )
        result = market.render(mkt)
        assert "6.5%" in result
        assert "$1,300,000" in result
        # Zero-default fields should NOT appear (they mean "not loaded")
        assert "list price" not in result.lower()
        assert "price/sqft" not in result.lower()
        assert "days on market" not in result.lower()
        assert "$0" not in result
        assert "None" not in result

    def test_returns_empty_for_all_zero_market(self):
        """A default-constructed MarketSnapshot has all zeros — render empty."""
        mkt = MarketSnapshot()
        assert market.render(mkt) == ""


class TestSegmentContext:
    def test_renders_stretcher(self):
        profile = BuyerProfile(intent="occupy", capital=100_000, current_rent=2_800)
        result = segment.render(STRETCHER, 0.72, profile)
        assert "STRETCHER" in result
        assert "0.72" in result
        assert "=== BUYER SEGMENT ===" in result

    def test_returns_empty_for_no_segment(self):
        result = segment.render(None, 0.0, BuyerProfile())
        assert result == ""

    def test_returns_empty_for_very_low_confidence(self):
        result = segment.render(STRETCHER, 0.05, BuyerProfile())
        assert result == ""

    def test_low_confidence_uses_fallback(self):
        result = segment.render(STRETCHER, 0.2, BuyerProfile())
        assert "Not yet determined" in result
        assert "BUYER CONTEXT" in result

    def test_profile_summary_included(self):
        profile = BuyerProfile(
            intent="invest",
            capital=500_000,
            equity=300_000,
        )
        result = segment.render(CASH_BUYER, 0.85, profile)
        assert "$500,000 capital" in result
        assert "$300,000 equity" in result


class TestPropertyContext:
    def test_renders_with_focus_property(self):
        ps = PropertyState()
        ps.focus_property = FocusProperty(
            property_id=123,
            address="1234 Cedar St",
            property_context={
                "price": 1_200_000,
                "neighborhood": "North Berkeley",
            },
        )
        result = property.render(ps)
        assert "1234 Cedar St" in result
        assert "$1,200,000" in result
        assert "North Berkeley" in result

    def test_renders_with_filter_intent(self):
        ps = PropertyState()
        ps.filter_intent = FilterIntent(
            description="R-1 zoned in North Berkeley",
            criteria={"zoning": "R-1", "neighborhood": "North Berkeley"},
        )
        result = property.render(ps)
        assert "R-1 zoned in North Berkeley" in result

    def test_returns_empty_for_none(self):
        assert property.render(None) == ""

    def test_returns_empty_for_empty_state(self):
        assert property.render(PropertyState()) == ""


class TestPreExecuted:
    def test_passes_through_facts(self):
        facts = "=== VERIFIED DATA SUMMARY ===\nSome facts here\n=== END ==="
        result = preexecuted.render(facts)
        assert result == facts

    def test_returns_empty_for_none(self):
        assert preexecuted.render(None) == ""

    def test_returns_empty_for_empty_string(self):
        assert preexecuted.render("") == ""

    def test_returns_empty_for_whitespace(self):
        assert preexecuted.render("   ") == ""


# ---------------------------------------------------------------------------
# Fallback prompt
# ---------------------------------------------------------------------------


class TestFallback:
    def test_renders_elicitation_questions(self):
        result = render_fallback()
        assert "Not yet determined" in result
        assert "?" in result  # Contains questions

    def test_skips_known_fields(self):
        profile = BuyerProfile(intent="occupy", income=150_000)
        result = render_fallback(profile)
        # Should NOT ask about intent (already known)
        assert "potential home, or evaluating it as an investment" not in result

    def test_always_has_at_least_one_question(self):
        # Fully populated profile
        profile = BuyerProfile(
            intent="occupy",
            capital=300_000,
            income=200_000,
            owns_current_home=True,
            is_first_time_buyer=False,
        )
        result = render_fallback(profile)
        assert "?" in result


# ---------------------------------------------------------------------------
# Segment templates
# ---------------------------------------------------------------------------


class TestSegmentTemplates:
    def test_all_11_segments_have_templates(self):
        """Every segment in ALL_SEGMENTS has a registered template."""
        for seg_id in ALL_SEGMENTS:
            template = get_segment_template(seg_id)
            assert template is not None, f"Missing template for {seg_id}"

    def test_templates_produce_output(self):
        """Each template renders non-empty output."""
        profile = BuyerProfile(intent="occupy", capital=200_000)
        for seg_id in ALL_SEGMENTS:
            template = get_segment_template(seg_id)
            result = template(
                confidence=0.75,
                profile_summary="Test profile",
                profile=profile,
            )
            assert len(result) > 100, f"Template {seg_id} produced short output"
            assert "=== BUYER SEGMENT ===" in result
            assert "=== END BUYER SEGMENT ===" in result

    def test_stretcher_tone(self):
        template = get_segment_template(STRETCHER)
        result = template(0.72, "Test", BuyerProfile())
        assert "reassuring" in result.lower() or "warm" in result.lower()

    def test_value_add_investor_tone(self):
        template = get_segment_template(VALUE_ADD_INVESTOR)
        result = template(0.85, "Test", BuyerProfile())
        assert "technical" in result.lower() or "project" in result.lower()


# ---------------------------------------------------------------------------
# Full assembly tests
# ---------------------------------------------------------------------------


class TestPromptAssembler:
    def test_basic_assembly(self):
        ctx = _make_context()
        assembler = PromptAssembler()
        result = assembler.assemble(ctx)

        # Should contain all major sections
        assert "=== PERSONALITY ===" in result
        assert "=== DATA MODEL ===" in result
        assert "=== TOOL INSTRUCTIONS ===" in result
        assert "=== MARKET CONDITIONS" in result
        assert "=== BUYER SEGMENT ===" in result

    def test_assembly_order(self):
        """Components appear in the correct order."""
        ctx = _make_context()
        assembler = PromptAssembler()
        result = assembler.assemble(ctx)

        personality_pos = result.index("=== PERSONALITY ===")
        data_model_pos = result.index("=== DATA MODEL ===")
        tool_pos = result.index("=== TOOL INSTRUCTIONS ===")
        market_pos = result.index("=== MARKET CONDITIONS")
        segment_pos = result.index("=== BUYER SEGMENT ===")

        assert personality_pos < data_model_pos < tool_pos < market_pos < segment_pos

    def test_assembly_with_no_segment(self):
        """Assembly works when no segment is classified."""
        ctx = _make_context(segment_id=None, confidence=0.0)
        assembler = PromptAssembler()
        result = assembler.assemble(ctx)

        # Should still have base components
        assert "=== PERSONALITY ===" in result
        assert "=== DATA MODEL ===" in result
        # But no segment block
        assert "=== BUYER SEGMENT ===" not in result

    def test_assembly_with_accumulated_facts(self):
        ctx = _make_context()
        assembler = PromptAssembler()
        facts = "=== VERIFIED DATA ===\nSome data here\n=== END ==="
        result = assembler.assemble(ctx, accumulated_facts=facts)
        assert "VERIFIED DATA" in result

    def test_assembly_with_iteration_warning(self):
        ctx = _make_context()
        assembler = PromptAssembler()
        result = assembler.assemble(ctx, iteration_remaining=2)
        assert "ITERATION BUDGET" in result
        assert "2" in result

    def test_no_iteration_warning_when_plenty(self):
        ctx = _make_context()
        assembler = PromptAssembler()
        result = assembler.assemble(ctx, iteration_remaining=8)
        assert "ITERATION BUDGET" not in result

    def test_assembly_with_property_context(self):
        ctx = _make_context()
        ctx.property = PropertyState()
        ctx.property.focus_property = FocusProperty(
            property_id=123,
            address="1234 Cedar St",
            property_context={"price": 1_200_000},
        )
        assembler = PromptAssembler()
        result = assembler.assemble(ctx)
        assert "1234 Cedar St" in result

    def test_all_segments_produce_valid_assembly(self):
        """Assembly works for every segment type."""
        assembler = PromptAssembler()
        for seg_id in ALL_SEGMENTS:
            ctx = _make_context(segment_id=seg_id, confidence=0.75)
            result = assembler.assemble(ctx)
            assert "=== PERSONALITY ===" in result
            assert "=== BUYER SEGMENT ===" in result
