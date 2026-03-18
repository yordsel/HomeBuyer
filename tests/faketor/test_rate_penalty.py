"""Tests for the rate penalty tool.

Phase F-4 (#57) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_rate_penalty_facts
from homebuyer.services.faketor.tools.gap.rate_penalty import (
    RatePenaltyParams,
    compute_rate_penalty,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_params(**overrides) -> RatePenaltyParams:
    # Equity-trapped upgrader: $500k balance at 3.25%, looking at $1.2M home
    defaults = {
        "existing_balance": 500_000,
        "existing_rate": 3.25,
        "existing_remaining_months": 300,  # ~25 years left
        "new_purchase_price": 1_200_000,
        "new_down_payment_pct": 20.0,
        "new_rate": 7.0,
        "annual_gross_income": 250_000,
    }
    defaults.update(overrides)
    return RatePenaltyParams(**defaults)


# ---------------------------------------------------------------------------
# Core computation tests
# ---------------------------------------------------------------------------


class TestRatePenaltyBaseline:
    def test_positive_penalty_at_higher_rate(self):
        """Moving from 3.25% to 7.0% on a bigger loan → positive penalty."""
        result = compute_rate_penalty(_default_params())
        assert result["monthly_penalty"] > 0
        assert result["annual_penalty"] == result["monthly_penalty"] * 12
        assert "more" in result["penalty_description"]

    def test_existing_payment_reasonable(self):
        """$500k at 3.25% over 300 months should be ~$2,400/mo."""
        result = compute_rate_penalty(_default_params())
        # Rough check: P&I on $500k at 3.25% over 25yr ≈ $2,437
        assert 2_200 <= result["existing_monthly_payment"] <= 2_700

    def test_new_payment_reasonable(self):
        """$960k loan at 7.0% over 30yr should be ~$6,400/mo."""
        result = compute_rate_penalty(_default_params())
        # 80% of $1.2M = $960k loan at 7%
        assert 6_000 <= result["new_monthly_payment"] <= 6_800

    def test_income_pct_computed(self):
        """Penalty as % of income should be computed when income provided."""
        result = compute_rate_penalty(_default_params())
        assert result["penalty_pct_of_income"] is not None
        assert result["penalty_pct_of_income"] > 0
        assert result["is_tolerable"] is not None

    def test_no_income_skips_pct(self):
        """Without income, penalty % and tolerability are None."""
        result = compute_rate_penalty(_default_params(annual_gross_income=None))
        assert result["penalty_pct_of_income"] is None
        assert result["is_tolerable"] is None

    def test_breakeven_rate_found(self):
        """When loans are similar size, breakeven rate should exist."""
        # Same-size loan: $960k existing at 3.25%, new $960k
        result = compute_rate_penalty(_default_params(
            existing_balance=960_000,
            existing_rate=3.25,
            existing_remaining_months=360,
        ))
        assert result["breakeven_rate"] is not None
        # Breakeven should be close to existing rate (same loan size)
        assert abs(result["breakeven_rate"] - 3.25) < 0.5

    def test_breakeven_none_when_impossible(self):
        """When new loan is much larger, no rate makes payments equal."""
        result = compute_rate_penalty(_default_params())
        # $500k existing vs $960k new — no rate can make $960k payment = $500k payment
        assert result["breakeven_rate"] is None


class TestRatePenaltyScenarios:
    def test_same_rate_no_penalty_same_loan(self):
        """Same rate and same loan amount → zero penalty."""
        result = compute_rate_penalty(_default_params(
            existing_balance=960_000,
            existing_rate=7.0,
            existing_remaining_months=360,
            new_purchase_price=1_200_000,
            new_down_payment_pct=20.0,
            new_rate=7.0,
        ))
        assert result["monthly_penalty"] == 0

    def test_lower_new_rate_negative_penalty(self):
        """New rate lower than existing → negative penalty (savings)."""
        result = compute_rate_penalty(_default_params(
            existing_balance=960_000,
            existing_rate=7.0,
            existing_remaining_months=360,
            new_purchase_price=1_200_000,
            new_down_payment_pct=20.0,
            new_rate=5.0,
        ))
        assert result["monthly_penalty"] < 0
        assert "less" in result["penalty_description"]

    def test_rate_scenarios_generated(self):
        """Should generate rate scenarios across a range."""
        result = compute_rate_penalty(_default_params())
        scenarios = result["rate_scenarios"]
        assert len(scenarios) > 0
        # Scenarios should be sorted by rate
        rates = [s["rate"] for s in scenarios]
        assert rates == sorted(rates)

    def test_rate_scenarios_include_current(self):
        """Rate scenarios should include the current market rate."""
        result = compute_rate_penalty(_default_params(new_rate=7.0))
        rates = [s["rate"] for s in result["rate_scenarios"]]
        assert 7.0 in rates

    def test_tolerable_rate_found(self):
        """Should find the highest rate where penalty is tolerable."""
        result = compute_rate_penalty(_default_params())
        # With $250k income, some scenarios should be tolerable
        if result["tolerable_rate"] is not None:
            assert result["tolerable_rate"] > 0

    def test_high_income_makes_penalty_tolerable(self):
        """Very high income should make the penalty tolerable."""
        result = compute_rate_penalty(_default_params(annual_gross_income=1_000_000))
        assert result["is_tolerable"] is True
        assert result["penalty_pct_of_income"] < 5.0

    def test_low_income_makes_penalty_intolerable(self):
        """Low income should make the penalty intolerable."""
        result = compute_rate_penalty(_default_params(annual_gross_income=80_000))
        assert result["is_tolerable"] is False


class TestRatePenaltySummary:
    def test_all_output_fields_present(self):
        """Result should have all expected fields."""
        result = compute_rate_penalty(_default_params())
        expected_fields = [
            "existing_balance", "existing_rate", "existing_remaining_months",
            "new_purchase_price", "new_down_payment_pct", "new_down_payment_amount",
            "new_loan_amount", "new_rate",
            "existing_monthly_payment", "new_monthly_payment",
            "monthly_penalty", "annual_penalty", "penalty_description",
            "annual_gross_income", "monthly_gross_income",
            "penalty_pct_of_income", "is_tolerable", "tolerable_threshold_pct",
            "breakeven_rate", "breakeven_description",
            "rate_scenarios", "tolerable_rate",
        ]
        for field in expected_fields:
            assert field in result, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Fact computer tests
# ---------------------------------------------------------------------------


class TestRatePenaltyFacts:
    def test_fact_computer_extracts_fields(self):
        result = compute_rate_penalty(_default_params())
        facts = compute_rate_penalty_facts(result)

        assert facts["existing_rate"] == result["existing_rate"]
        assert facts["new_rate"] == result["new_rate"]
        assert facts["monthly_penalty"] == result["monthly_penalty"]
        assert facts["breakeven_rate"] == result["breakeven_rate"]
        assert facts["penalty_pct_of_income"] == result["penalty_pct_of_income"]

    def test_fact_computer_handles_empty_dict(self):
        facts = compute_rate_penalty_facts({})
        assert facts["existing_rate"] is None
        assert facts["monthly_penalty"] is None


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRatePenaltyRegistration:
    def test_tool_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert "rate_penalty" in registry.names

    def test_fact_computer_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_fact_computer("rate_penalty") is not None

    def test_block_type_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_block_type("rate_penalty") == "rate_penalty_card"
