"""Tests for the competition assessment tool.

Phase F-5 (#58) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_competition_facts
from homebuyer.services.faketor.tools.gap.competition import (
    CompetitionParams,
    compute_competition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hot_market_params(**overrides) -> CompetitionParams:
    """Hot Berkeley market: high STL ratios, low DOM, mostly above asking."""
    defaults = {
        "neighborhood": "Rockridge",
        "sale_to_list_ratios": [1.08, 1.12, 1.05, 1.10, 1.03, 1.15, 1.07, 1.09],
        "dom_values": [5, 3, 8, 4, 7, 6, 10, 5],
        "above_asking_flags": [True, True, True, True, True, True, True, False],
        "active_listings": 8,
        "monthly_closed_sales": 4.0,
        "price_min": 1_000_000,
        "price_max": 1_500_000,
    }
    defaults.update(overrides)
    return CompetitionParams(**defaults)


def _cold_market_params(**overrides) -> CompetitionParams:
    """Cold/buyer-friendly market: low STL, high DOM, mostly below asking."""
    defaults = {
        "neighborhood": "South Berkeley",
        "sale_to_list_ratios": [0.95, 0.92, 0.97, 0.93, 0.96],
        "dom_values": [45, 62, 38, 55, 70],
        "above_asking_flags": [False, False, False, False, True],
        "active_listings": 20,
        "monthly_closed_sales": 2.0,
        "price_min": 800_000,
        "price_max": 1_200_000,
    }
    defaults.update(overrides)
    return CompetitionParams(**defaults)


# ---------------------------------------------------------------------------
# Core computation tests
# ---------------------------------------------------------------------------


class TestCompetitionBaseline:
    def test_hot_market_high_score(self):
        """Hot market should produce a high competition score."""
        result = compute_competition(_hot_market_params())
        assert result["competition_score"] >= 60
        assert result["competition_label"] in ("Very Competitive", "Competitive")

    def test_cold_market_low_score(self):
        """Cold market should produce a low competition score."""
        result = compute_competition(_cold_market_params())
        assert result["competition_score"] <= 40
        assert result["competition_label"] in ("Buyer-Friendly", "Very Buyer-Friendly", "Moderate")

    def test_sale_to_list_computed(self):
        """Sale-to-list median should be computed."""
        result = compute_competition(_hot_market_params())
        assert result["sale_to_list_median"] is not None
        assert result["sale_to_list_median"] > 1.0  # above asking

    def test_dom_distribution(self):
        """DOM distribution should have median and percentiles."""
        result = compute_competition(_hot_market_params())
        dom = result["dom_distribution"]
        assert dom["median"] is not None
        assert dom["median"] < 10  # hot market
        assert dom["p25"] is not None
        assert dom["p75"] is not None

    def test_above_asking_pct(self):
        """Above-asking percentage should be computed."""
        result = compute_competition(_hot_market_params())
        assert result["above_asking_pct"] is not None
        assert result["above_asking_pct"] > 50  # most above asking

    def test_absorption_rate(self):
        """Absorption rate and months of inventory computed."""
        result = compute_competition(_hot_market_params())
        assert result["absorption_rate"] is not None
        assert result["months_of_inventory"] is not None
        assert result["months_of_inventory"] > 0

    def test_sample_size_reported(self):
        """Sample size should match input data length."""
        result = compute_competition(_hot_market_params())
        assert result["sample_size"] == 8


class TestCompetitionScoring:
    def test_score_components_present(self):
        """Score components should be individually reported."""
        result = compute_competition(_hot_market_params())
        components = result["score_components"]
        assert "sale_to_list_score" in components
        assert "dom_score" in components
        assert "above_asking_score" in components
        assert "absorption_score" in components

    def test_hot_components_all_high(self):
        """In a hot market, all component scores should be high."""
        result = compute_competition(_hot_market_params())
        components = result["score_components"]
        assert components["sale_to_list_score"] >= 50
        assert components["dom_score"] >= 50
        assert components["above_asking_score"] >= 50

    def test_cold_dom_score_low(self):
        """In a cold market, DOM score should be low."""
        result = compute_competition(_cold_market_params())
        components = result["score_components"]
        assert components["dom_score"] <= 50


class TestCompetitionEdgeCases:
    def test_empty_data(self):
        """Empty data should produce neutral score."""
        result = compute_competition(CompetitionParams(neighborhood="Test"))
        assert result["competition_score"] == 50.0
        assert result["sale_to_list_median"] is None
        assert result["dom_distribution"]["median"] is None
        assert result["sample_size"] == 0

    def test_single_sale(self):
        """Single sale should still produce results."""
        result = compute_competition(CompetitionParams(
            neighborhood="Test",
            sale_to_list_ratios=[1.05],
            dom_values=[7],
            above_asking_flags=[True],
            active_listings=3,
            monthly_closed_sales=1.0,
        ))
        assert result["competition_score"] > 0
        assert result["sale_to_list_median"] == 1.05

    def test_zero_inventory(self):
        """Zero active listings: max absorption."""
        result = compute_competition(CompetitionParams(
            neighborhood="Test",
            sale_to_list_ratios=[1.0],
            dom_values=[10],
            above_asking_flags=[False],
            active_listings=0,
            monthly_closed_sales=5.0,
        ))
        assert result["months_of_inventory"] == 0.0

    def test_interpretation_present(self):
        """Interpretation string should be a readable summary."""
        result = compute_competition(_hot_market_params())
        assert result["interpretation"] is not None
        assert len(result["interpretation"]) > 10


# ---------------------------------------------------------------------------
# Fact computer tests
# ---------------------------------------------------------------------------


class TestCompetitionFacts:
    def test_fact_computer_extracts_fields(self):
        result = compute_competition(_hot_market_params())
        facts = compute_competition_facts(result)

        assert facts["competition_score"] == result["competition_score"]
        assert facts["competition_label"] == result["competition_label"]
        assert facts["sale_to_list_median"] == result["sale_to_list_median"]
        assert facts["dom_median"] == result["dom_distribution"]["median"]

    def test_fact_computer_handles_empty_dict(self):
        facts = compute_competition_facts({})
        assert facts["competition_score"] is None


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestCompetitionRegistration:
    def test_tool_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert "competition_assessment" in registry.names

    def test_fact_computer_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_fact_computer("competition_assessment") is not None

    def test_block_type_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_block_type("competition_assessment") == "competition_card"
