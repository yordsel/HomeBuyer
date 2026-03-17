"""Tests for the adjacent market comparison tool.

Phase F-10 (#63) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_adjacent_market_facts
from homebuyer.services.faketor.tools.gap.adjacent_market import (
    AdjacentMarketParams,
    compute_adjacent_market,
)


class TestAdjacentMarket:
    def test_all_markets(self):
        """Empty markets list should compare all available markets."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=1_200_000))
        assert result["markets_compared"] >= 6

    def test_budget_ratio(self):
        """Budget ratio should reflect affordability."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=1_200_000))
        for comp in result["comparisons"]:
            assert comp["budget_ratio"] > 0

    def test_sorted_by_affordability(self):
        """Results should be sorted by budget ratio descending."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=1_200_000))
        ratios = [c["budget_ratio"] for c in result["comparisons"]]
        assert ratios == sorted(ratios, reverse=True)

    def test_affordable_markets_identified(self):
        """Should identify affordable markets."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=1_200_000))
        assert result["affordable_count"] > 0
        assert len(result["affordable_markets"]) == result["affordable_count"]

    def test_berkeley_baseline(self):
        """Should include Berkeley as baseline."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=1_200_000))
        assert result["berkeley_baseline"] is not None
        assert result["berkeley_baseline"]["market"] == "Berkeley"

    def test_bart_filter(self):
        """BART filter should exclude non-BART markets."""
        compute_adjacent_market(AdjacentMarketParams(budget=1_200_000))
        bart_only = compute_adjacent_market(AdjacentMarketParams(
            budget=1_200_000, must_have_bart=True,
        ))
        bart_meeting = [c for c in bart_only["comparisons"] if c["meets_requirements"]]
        # All that meet requirements should have BART
        for c in bart_meeting:
            assert c["bart_access"] is True

    def test_sqft_bonus(self):
        """Should compute sqft bonus vs typical."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=1_500_000))
        for comp in result["comparisons"]:
            assert "sqft_bonus" in comp
            assert comp["sqft_bonus"] == comp["affordable_sqft"] - comp["typical_sqft"]

    def test_low_budget(self):
        """Very low budget should show mostly out-of-range."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=400_000))
        out_of_range = [
            c for c in result["comparisons"] if c["affordability"] == "Out of Range"
        ]
        assert len(out_of_range) > 0


class TestAdjacentMarketFacts:
    def test_extracts_fields(self):
        result = compute_adjacent_market(AdjacentMarketParams(budget=1_200_000))
        facts = compute_adjacent_market_facts(result)
        assert facts["budget"] == 1_200_000
        assert facts["markets_compared"] == result["markets_compared"]
        assert facts["best_value"] == result["best_value"]

    def test_handles_empty(self):
        facts = compute_adjacent_market_facts({})
        assert facts["budget"] is None


class TestAdjacentMarketRegistration:
    def test_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert "adjacent_market_comparison" in registry.names

    def test_block_type(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_block_type("adjacent_market_comparison") == "adjacent_market_card"
