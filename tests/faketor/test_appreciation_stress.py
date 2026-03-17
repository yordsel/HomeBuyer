"""Tests for the appreciation stress test tool.

Phase F-8 (#61) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_appreciation_stress_facts
from homebuyer.services.faketor.tools.gap.appreciation_stress import (
    AppreciationStressParams,
    compute_appreciation_stress,
)


def _default_params(**overrides) -> AppreciationStressParams:
    defaults = {
        "purchase_price": 1_200_000,
        "down_payment_pct": 20.0,
        "mortgage_rate": 7.0,
        "monthly_rental_income": 0,
        "exit_years": [3, 5, 7, 10],
    }
    defaults.update(overrides)
    return AppreciationStressParams(**defaults)


class TestAppreciationStress:
    def test_default_scenarios(self):
        """Should have 5 default scenarios (bull, base, flat, bear, crash)."""
        result = compute_appreciation_stress(_default_params())
        assert result["scenario_count"] == 5

    def test_exit_years_present(self):
        """Each scenario should have exits at specified years."""
        result = compute_appreciation_stress(_default_params())
        for scenario in result["scenarios"]:
            years = [e["year"] for e in scenario["exits"]]
            assert years == [3, 5, 7, 10]

    def test_bull_scenario_profitable_with_rent(self):
        """Bull scenario (+5%) with rental income should be profitable."""
        result = compute_appreciation_stress(_default_params(
            monthly_rental_income=5_000,
        ))
        bull = next(s for s in result["scenarios"] if "Bull" in s["scenario_name"])
        # At 5% appreciation with rental income offsetting carry
        exit_10 = next(e for e in bull["exits"] if e["year"] == 10)
        assert exit_10["is_profitable"] is True

    def test_crash_scenario_unprofitable(self):
        """Crash scenario (-15%) should show significant losses."""
        result = compute_appreciation_stress(_default_params())
        crash = next(s for s in result["scenarios"] if "Crash" in s["scenario_name"])
        for exit_data in crash["exits"]:
            assert exit_data["is_profitable"] is False
            # Should have meaningful negative profit (at least -$100k loss)
            assert exit_data["profit"] < -100_000
            # ROI should be negative
            assert exit_data["annualized_roi_pct"] < 0

    def test_rental_income_reduces_carry(self):
        """Rental income should reduce carry cost."""
        no_rent = compute_appreciation_stress(_default_params())
        with_rent = compute_appreciation_stress(_default_params(
            monthly_rental_income=3_000,
        ))
        assert with_rent["monthly_carry_cost"] < no_rent["monthly_carry_cost"]

    def test_refi_analysis(self):
        """Refi scenario should compute savings."""
        result = compute_appreciation_stress(_default_params(refi_rate=5.0))
        assert result["refi_analysis"] is not None
        assert result["refi_analysis"]["monthly_savings"] > 0
        assert result["refi_analysis"]["refi_rate"] == 5.0

    def test_no_refi_when_not_specified(self):
        """No refi analysis when refi_rate is None."""
        result = compute_appreciation_stress(_default_params())
        assert result["refi_analysis"] is None

    def test_summary_flags(self):
        """Should report whether any/all scenarios are profitable."""
        result = compute_appreciation_stress(_default_params())
        assert isinstance(result["all_scenarios_profitable"], bool)
        assert isinstance(result["any_scenario_profitable"], bool)


class TestAppreciationStressFacts:
    def test_extracts_fields(self):
        result = compute_appreciation_stress(_default_params())
        facts = compute_appreciation_stress_facts(result)
        assert facts["scenario_count"] == 5
        assert facts["monthly_carry_cost"] == result["monthly_carry_cost"]

    def test_handles_empty(self):
        facts = compute_appreciation_stress_facts({})
        assert facts["scenario_count"] is None


class TestAppreciationStressRegistration:
    def test_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert "appreciation_stress_test" in registry.names

    def test_fact_computer(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_fact_computer("appreciation_stress_test") is not None

    def test_block_type(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_block_type("appreciation_stress_test") == "appreciation_stress_card"
