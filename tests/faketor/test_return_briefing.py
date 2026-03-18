"""Tests for the return briefing prompt component.

Phase G-4 (#68) of Epic #23.
"""

import time

from homebuyer.services.faketor.prompts.return_briefing import (
    render,
    _render_market_changes,
    _render_profile_recap,
)
from homebuyer.services.faketor.state.context import ResearchContext
from homebuyer.services.faketor.state.market import MarketDelta
from homebuyer.services.faketor.state.property import FocusProperty


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _context_with_delta(**delta_overrides) -> ResearchContext:
    """Create a ResearchContext with a material MarketDelta."""
    ctx = ResearchContext(
        user_id="1",
        created_at=time.time() - 7200,
        last_active=time.time(),
    )
    delta_defaults = {
        "rate_change": -0.25,
        "rate_change_pct": -3.5,
        "rate_material": True,
        "median_price_change": 15_000,
        "median_price_change_pct": 1.2,
        "price_material": False,
        "inventory_change": 5,
        "inventory_change_pct": 8.3,
        "inventory_material": False,
    }
    delta_defaults.update(delta_overrides)
    ctx.market_delta = MarketDelta(**delta_defaults)
    return ctx


# ---------------------------------------------------------------------------
# render() tests
# ---------------------------------------------------------------------------


class TestReturnBriefingRender:
    def test_empty_when_no_delta(self):
        """No market delta → no briefing."""
        ctx = ResearchContext()
        assert render(ctx) == ""

    def test_empty_when_no_material_changes(self):
        """Delta present but nothing material → no briefing."""
        ctx = _context_with_delta(rate_material=False)
        assert render(ctx) == ""

    def test_renders_with_material_rate_change(self):
        """Material rate change should produce a briefing."""
        ctx = _context_with_delta(rate_material=True)
        result = render(ctx)
        assert "=== RETURN CONTEXT" in result
        assert "=== END RETURN CONTEXT ===" in result
        assert "Mortgage rates moved down" in result
        assert "0.25%" in result

    def test_renders_with_material_price_change(self):
        """Material price change should appear in briefing."""
        ctx = _context_with_delta(
            rate_material=False,
            price_material=True,
            median_price_change=25_000,
            median_price_change_pct=2.0,
        )
        result = render(ctx)
        assert "median price" in result.lower()
        assert "$25,000" in result

    def test_renders_with_material_inventory_change(self):
        """Material inventory change should appear in briefing."""
        ctx = _context_with_delta(
            rate_material=False,
            inventory_material=True,
            inventory_change=-10,
            inventory_change_pct=-12.5,
        )
        result = render(ctx)
        assert "Inventory decreased" in result

    def test_includes_focus_property(self):
        """Focus property should be mentioned in briefing."""
        ctx = _context_with_delta(rate_material=True)
        ctx.property.focus_property = FocusProperty(
            property_id=42,
            address="123 Spruce St, Berkeley",
            last_known_status="active",
            status_checked_at=time.time() - 7200,
        )
        result = render(ctx)
        assert "123 Spruce St" in result
        assert "active" in result

    def test_no_focus_property_section_when_none(self):
        """No focus property → no FOCUS PROPERTY section."""
        ctx = _context_with_delta(rate_material=True)
        result = render(ctx)
        assert "FOCUS PROPERTY" not in result

    def test_includes_buyer_profile_recap(self):
        """Buyer profile fields should be recapped."""
        ctx = _context_with_delta(rate_material=True)
        ctx.buyer.profile.intent = "occupy"
        ctx.buyer.profile.capital = 500_000
        ctx.buyer.profile.income = 250_000
        result = render(ctx)
        assert "BUYER PROFILE RECAP" in result
        assert "$500,000" in result
        assert "occupy" in result

    def test_instructions_always_present(self):
        """LLM instructions should always be in the briefing."""
        ctx = _context_with_delta(rate_material=True)
        result = render(ctx)
        assert "Welcome the user back" in result
        assert "Do NOT dump all changes" in result

    def test_multiple_material_changes(self):
        """All three material changes should render together."""
        ctx = _context_with_delta(
            rate_material=True,
            price_material=True,
            inventory_material=True,
        )
        result = render(ctx)
        assert "Mortgage rates" in result
        assert "median price" in result.lower()
        assert "Inventory" in result


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestRenderMarketChanges:
    def test_rate_up(self):
        delta = MarketDelta(rate_change=0.50, rate_change_pct=7.1, rate_material=True)
        lines = _render_market_changes(delta)
        assert len(lines) == 1
        assert "up" in lines[0]

    def test_rate_down(self):
        delta = MarketDelta(rate_change=-0.25, rate_change_pct=-3.5, rate_material=True)
        lines = _render_market_changes(delta)
        assert "down" in lines[0]

    def test_price_up(self):
        delta = MarketDelta(
            median_price_change=30_000,
            median_price_change_pct=2.5,
            price_material=True,
        )
        lines = _render_market_changes(delta)
        assert "$30,000" in lines[0]

    def test_inventory_decreased(self):
        delta = MarketDelta(
            inventory_change=-8,
            inventory_change_pct=-10.0,
            inventory_material=True,
        )
        lines = _render_market_changes(delta)
        assert "decreased" in lines[0]

    def test_no_material_changes(self):
        delta = MarketDelta()
        assert _render_market_changes(delta) == []


class TestRenderProfileRecap:
    def test_full_profile(self):
        from homebuyer.services.faketor.state.buyer import BuyerProfile
        profile = BuyerProfile()
        profile.intent = "invest"
        profile.capital = 1_000_000
        profile.income = 300_000
        profile.current_rent = 4_500
        lines = _render_profile_recap(profile)
        assert len(lines) == 4

    def test_empty_profile(self):
        from homebuyer.services.faketor.state.buyer import BuyerProfile
        profile = BuyerProfile()
        lines = _render_profile_recap(profile)
        assert len(lines) == 0


# ---------------------------------------------------------------------------
# Integration with PromptAssembler
# ---------------------------------------------------------------------------


class TestReturnBriefingInAssembler:
    def test_briefing_included_in_assembled_prompt(self):
        """Return briefing should appear in the assembled system prompt."""
        from homebuyer.services.faketor.prompts import PromptAssembler

        ctx = _context_with_delta(rate_material=True)
        assembler = PromptAssembler()
        prompt = assembler.assemble(ctx)
        assert "=== RETURN CONTEXT" in prompt

    def test_no_briefing_for_new_user(self):
        """New user (no delta) should not get a return briefing."""
        from homebuyer.services.faketor.prompts import PromptAssembler

        ctx = ResearchContext()
        assembler = PromptAssembler()
        prompt = assembler.assemble(ctx)
        assert "RETURN CONTEXT" not in prompt
