"""Tests for the dual property model tool.

Phase F-6 (#59) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_dual_property_facts
from homebuyer.services.faketor.tools.gap.dual_property import (
    DualPropertyParams,
    compute_dual_property,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_params(**overrides) -> DualPropertyParams:
    # Equity-leveraging investor: $1.5M primary (owes $400k at 3.25%),
    # pulling $200k HELOC, buying $800k investment property.
    defaults = {
        "primary_value": 1_500_000,
        "primary_mortgage_balance": 400_000,
        "primary_mortgage_rate": 3.25,
        "primary_mortgage_remaining_months": 300,
        "extraction_method": "heloc",
        "extraction_amount": 200_000,
        "heloc_rate": 8.5,
        "investment_price": 800_000,
        "investment_down_payment_pct": 25.0,
        "investment_rate": 7.5,
        "investment_monthly_rent": 4_000,
        "investment_hoa": 0,
    }
    defaults.update(overrides)
    return DualPropertyParams(**defaults)


# ---------------------------------------------------------------------------
# Core computation tests
# ---------------------------------------------------------------------------


class TestDualPropertyBaseline:
    def test_available_equity(self):
        """Available equity = primary value - mortgage balance."""
        result = compute_dual_property(_default_params())
        assert result["available_equity"] == 1_100_000

    def test_max_heloc(self):
        """Max HELOC = 80% of primary value - mortgage balance."""
        result = compute_dual_property(_default_params())
        # 80% of $1.5M = $1.2M - $400k = $800k
        assert result["max_heloc_amount"] == 800_000

    def test_heloc_cost_computed(self):
        """HELOC monthly cost = extraction * rate / 12."""
        result = compute_dual_property(_default_params())
        extraction = result["extraction"]
        # $200k * 8.5% / 12 = $1,416.67 → $1,417
        assert extraction["monthly_cost"] == 1417
        assert extraction["method"] == "heloc"

    def test_investment_cashflow(self):
        """Investment property should have cash flow computed."""
        result = compute_dual_property(_default_params())
        inv = result["investment"]
        assert inv["monthly_gross_rent"] == 4_000
        assert inv["effective_gross_rent"] < inv["monthly_gross_rent"]  # vacancy
        assert inv["monthly_debt_service"] > 0
        assert inv["cap_rate_pct"] > 0

    def test_combined_cashflow(self):
        """Combined cash flow = investment CF - extraction increase."""
        result = compute_dual_property(_default_params())
        expected = (
            result["investment"]["monthly_net_cash_flow"]
            - result["extraction"]["monthly_increase"]
        )
        assert result["combined_monthly_cash_flow"] == expected
        assert result["combined_annual_cash_flow"] == expected * 12

    def test_stress_tests_present(self):
        """Should have 4 stress test scenarios."""
        result = compute_dual_property(_default_params())
        assert len(result["stress_tests"]) == 4
        scenarios = [t["scenario"] for t in result["stress_tests"]]
        assert "High vacancy (15%)" in scenarios
        assert "Rate increase (+2%)" in scenarios
        assert "Maintenance spike (3%)" in scenarios


class TestDualPropertyScenarios:
    def test_no_extraction(self):
        """Zero extraction: no additional cost on primary."""
        result = compute_dual_property(_default_params(extraction_amount=0))
        assert result["extraction"]["monthly_increase"] == 0

    def test_cashout_refi(self):
        """Cash-out refi should compute new payment on combined balance."""
        result = compute_dual_property(_default_params(
            extraction_method="cashout_refi",
            cashout_refi_rate=7.0,
        ))
        extraction = result["extraction"]
        assert extraction["method"] == "cashout_refi"
        # New balance = $400k + $200k = $600k at 7%
        assert extraction["new_balance"] == 600_000
        assert extraction["monthly_increase"] > 0

    def test_high_rent_positive_cf(self):
        """Very high rent should produce positive combined cash flow."""
        result = compute_dual_property(_default_params(
            investment_monthly_rent=8_000,
            extraction_amount=0,
        ))
        assert result["is_cash_flow_positive"] is True

    def test_low_rent_negative_cf(self):
        """Very low rent should produce negative combined cash flow."""
        result = compute_dual_property(_default_params(
            investment_monthly_rent=1_000,
        ))
        assert result["is_cash_flow_positive"] is False

    def test_expense_breakdown(self):
        """Investment expenses should have all components."""
        result = compute_dual_property(_default_params())
        expenses = result["investment"]["expense_breakdown"]
        assert expenses["property_tax"] > 0
        assert expenses["insurance"] > 0
        assert expenses["maintenance"] > 0
        assert expenses["management"] > 0
        assert expenses["total"] > 0


class TestDualPropertyStressTests:
    def test_worst_case_identified(self):
        """Worst case should be the combined scenario."""
        result = compute_dual_property(_default_params())
        # Combined scenario (vacancy + rate) is typically worst
        assert result["worst_case_scenario"] is not None
        assert result["worst_case_monthly"] <= result["combined_monthly_cash_flow"]

    def test_stress_tests_have_deltas(self):
        """Each stress test should show delta from base."""
        result = compute_dual_property(_default_params())
        for test in result["stress_tests"]:
            assert "delta_from_base" in test
            assert test["delta_from_base"] <= 0  # stress always worse


# ---------------------------------------------------------------------------
# Fact computer tests
# ---------------------------------------------------------------------------


class TestDualPropertyFacts:
    def test_fact_computer_extracts_fields(self):
        result = compute_dual_property(_default_params())
        facts = compute_dual_property_facts(result)

        assert facts["available_equity"] == result["available_equity"]
        assert facts["combined_monthly_cash_flow"] == result["combined_monthly_cash_flow"]
        assert facts["cash_on_cash_pct"] == result["cash_on_cash_pct"]
        assert facts["survives_worst_case"] == result["survives_worst_case"]

    def test_fact_computer_handles_empty_dict(self):
        facts = compute_dual_property_facts({})
        assert facts["available_equity"] is None


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestDualPropertyRegistration:
    def test_tool_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert "dual_property_model" in registry.names

    def test_fact_computer_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_fact_computer("dual_property_model") is not None

    def test_block_type_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_block_type("dual_property_model") == "dual_property_card"
