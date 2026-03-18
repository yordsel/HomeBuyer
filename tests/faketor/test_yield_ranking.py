"""Tests for the yield ranking tool.

Phase F-7 (#60) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_yield_ranking_facts
from homebuyer.services.faketor.tools.gap.yield_ranking import (
    PropertyForRanking,
    YieldRankingParams,
    compute_yield_ranking,
)


def _sample_properties():
    return [
        PropertyForRanking(address="123 Main St", price=800_000, monthly_rent=4_000),
        PropertyForRanking(address="456 Oak Ave", price=600_000, monthly_rent=3_500),
        PropertyForRanking(address="789 Elm Blvd", price=1_000_000, monthly_rent=4_500),
    ]


class TestYieldRanking:
    def test_ranks_by_spread(self):
        result = compute_yield_ranking(YieldRankingParams(properties=_sample_properties()))
        ranked = result["ranked_by_spread"]
        assert len(ranked) == 3
        # Best spread should be first
        spreads = [r["leverage_spread_pct"] for r in ranked]
        assert spreads == sorted(spreads, reverse=True)

    def test_ranks_by_coc(self):
        result = compute_yield_ranking(YieldRankingParams(properties=_sample_properties()))
        cocs = [r["cash_on_cash_pct"] for r in result["ranked_by_cash_on_cash"]]
        assert cocs == sorted(cocs, reverse=True)

    def test_ranks_by_dscr(self):
        result = compute_yield_ranking(YieldRankingParams(properties=_sample_properties()))
        dscrs = [r["dscr"] for r in result["ranked_by_dscr"]]
        assert dscrs == sorted(dscrs, reverse=True)

    def test_property_count(self):
        result = compute_yield_ranking(YieldRankingParams(properties=_sample_properties()))
        assert result["property_count"] == 3

    def test_best_properties_identified(self):
        result = compute_yield_ranking(YieldRankingParams(properties=_sample_properties()))
        assert result["best_leverage_spread"] is not None
        assert result["best_cash_on_cash"] is not None
        assert result["best_dscr"] is not None

    def test_empty_list(self):
        result = compute_yield_ranking(YieldRankingParams(properties=[]))
        assert result["property_count"] == 0
        assert result["best_leverage_spread"] is None

    def test_custom_down_and_rate(self):
        result = compute_yield_ranking(YieldRankingParams(
            properties=_sample_properties(),
            down_payment_pct=30.0,
            mortgage_rate=6.5,
        ))
        assert result["down_payment_pct"] == 30.0
        assert result["mortgage_rate"] == 6.5


class TestYieldRankingFacts:
    def test_extracts_fields(self):
        result = compute_yield_ranking(YieldRankingParams(properties=_sample_properties()))
        facts = compute_yield_ranking_facts(result)
        assert facts["property_count"] == 3
        assert facts["best_spread_address"] is not None

    def test_handles_empty(self):
        facts = compute_yield_ranking_facts({})
        assert facts["property_count"] is None


class TestYieldRankingRegistration:
    def test_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert "yield_ranking" in registry.names

    def test_fact_computer(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_fact_computer("yield_ranking") is not None

    def test_block_type(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_block_type("yield_ranking") == "yield_ranking_card"
