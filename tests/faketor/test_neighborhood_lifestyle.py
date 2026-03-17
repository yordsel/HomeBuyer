"""Tests for the neighborhood lifestyle tool.

Phase F-9 (#62) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_neighborhood_lifestyle_facts
from homebuyer.services.faketor.tools.gap.neighborhood_lifestyle import (
    NeighborhoodLifestyleParams,
    compute_neighborhood_lifestyle,
)


class TestNeighborhoodLifestyle:
    def test_all_neighborhoods(self):
        """Empty list should compare all neighborhoods."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams())
        assert result["neighborhoods_compared"] >= 8

    def test_specific_neighborhoods(self):
        """Should compare only specified neighborhoods."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams(
            neighborhoods=["North Berkeley", "Rockridge", "Elmwood"],
        ))
        assert result["neighborhoods_compared"] == 3

    def test_composite_scores(self):
        """Each neighborhood should have a composite score."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams())
        for comp in result["comparisons"]:
            assert 1.0 <= comp["composite_score"] <= 10.0

    def test_sorted_by_score(self):
        """Results should be sorted by composite score descending."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams())
        scores = [c["composite_score"] for c in result["comparisons"]]
        assert scores == sorted(scores, reverse=True)

    def test_weighted_priorities(self):
        """Heavy school weight should favor school-strong neighborhoods."""
        equal_weight = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams())
        school_heavy = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams(
            priority_schools=5.0,
            priority_walkability=0.0,
            priority_transit=0.0,
            priority_dining=0.0,
            priority_parks=0.0,
            priority_safety=0.0,
        ))
        # School-only weighting should produce different ranking than equal weight
        equal_scores = {
            c["neighborhood"]: c["composite_score"]
            for c in equal_weight["comparisons"]
        }
        school_scores = {
            c["neighborhood"]: c["composite_score"]
            for c in school_heavy["comparisons"]
        }
        # The top-ranked neighborhood should have the highest school score (9)
        # Claremont and North Berkeley both have schools=9
        top_school = school_heavy["comparisons"][0]
        assert top_school["scores"]["schools"] == 9
        # Scores should differ between the two weightings
        assert equal_scores != school_scores

    def test_best_per_factor(self):
        """Should identify best neighborhood per factor."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams())
        factors = result["best_per_factor"]
        assert "walkability" in factors
        assert "schools" in factors
        assert "transit" in factors

    def test_unknown_neighborhood_skipped(self):
        """Unknown neighborhoods should be silently skipped."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams(
            neighborhoods=["North Berkeley", "NonExistent"],
        ))
        assert result["neighborhoods_compared"] == 1

    def test_character_included(self):
        """Each comparison should include character description."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams(
            neighborhoods=["Rockridge"],
        ))
        assert result["comparisons"][0]["character"] != ""


class TestNeighborhoodLifestyleFacts:
    def test_extracts_fields(self):
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams())
        facts = compute_neighborhood_lifestyle_facts(result)
        assert facts["neighborhoods_compared"] == result["neighborhoods_compared"]
        assert facts["best_overall"] == result["best_overall"]

    def test_handles_empty(self):
        facts = compute_neighborhood_lifestyle_facts({})
        assert facts["neighborhoods_compared"] is None


class TestNeighborhoodLifestyleRegistration:
    def test_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert "neighborhood_lifestyle" in registry.names

    def test_block_type(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_block_type("neighborhood_lifestyle") == "neighborhood_lifestyle_card"
