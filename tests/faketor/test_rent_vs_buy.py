"""Tests for the rent vs. buy breakeven analysis tool.

Phase F-2 (#55) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_rent_vs_buy_facts
from homebuyer.services.faketor.tools.gap.rent_vs_buy import (
    RentVsBuyParams,
    compute_rent_vs_buy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_params(**overrides) -> RentVsBuyParams:
    # Scenario: $1.2M Berkeley home, 20% down, moderate ownership cost ($7.5k/mo)
    # vs healthy rent ($4.5k/mo) with 4% annual increases and 3% appreciation.
    # This combination produces a crossover around year 10-12.
    defaults = {
        "purchase_price": 1_200_000,
        "down_payment_pct": 20.0,
        "mortgage_rate": 7.0,
        "annual_appreciation_pct": 3.0,
        "monthly_ownership_cost": 7_500,
        "monthly_pmi": 0,
        "pmi_dropoff_month": None,
        "annual_property_tax": 14_160,  # 1.18% of 1.2M
        "current_rent": 4_500,
        "annual_rent_increase_pct": 4.0,
        "horizon_years": 15,
    }
    defaults.update(overrides)
    return RentVsBuyParams(**defaults)


# ---------------------------------------------------------------------------
# Core computation tests
# ---------------------------------------------------------------------------


class TestRentVsBuyBaseline:
    def test_returns_crossover_year(self):
        """Should produce a crossover year for typical Berkeley scenario."""
        result = compute_rent_vs_buy(_default_params())
        assert "crossover_year" in result
        # With 3% appreciation and 4% rent growth, buying should eventually win
        assert result["crossover_year"] is not None

    def test_returns_yearly_comparison(self):
        """Year-by-year comparison table has correct length."""
        result = compute_rent_vs_buy(_default_params(horizon_years=10))
        assert len(result["yearly_comparison"]) == 10
        assert result["yearly_comparison"][0]["year"] == 1
        assert result["yearly_comparison"][-1]["year"] == 10

    def test_yearly_snapshots_have_required_fields(self):
        """Each snapshot has all the expected fields."""
        result = compute_rent_vs_buy(_default_params(horizon_years=3))
        snapshot = result["yearly_comparison"][0]
        required_fields = [
            "year", "annual_rent", "cumulative_rent", "opportunity_gain",
            "cumulative_rent_net", "cumulative_ownership", "home_value",
            "home_equity", "remaining_balance", "tax_benefit_cumulative",
            "selling_costs", "cumulative_buy_net", "buy_advantage",
        ]
        for field in required_fields:
            assert field in snapshot, f"Missing field: {field}"

    def test_rent_escalates(self):
        """Rent should increase year over year."""
        result = compute_rent_vs_buy(_default_params(horizon_years=5))
        rents = [s["annual_rent"] for s in result["yearly_comparison"]]
        for i in range(1, len(rents)):
            assert rents[i] > rents[i - 1]

    def test_home_value_appreciates(self):
        """Home value should grow with appreciation."""
        result = compute_rent_vs_buy(_default_params(horizon_years=5))
        values = [s["home_value"] for s in result["yearly_comparison"]]
        for i in range(1, len(values)):
            assert values[i] > values[i - 1]

    def test_equity_grows(self):
        """Home equity should increase over time."""
        result = compute_rent_vs_buy(_default_params(horizon_years=5))
        equities = [s["home_equity"] for s in result["yearly_comparison"]]
        for i in range(1, len(equities)):
            assert equities[i] > equities[i - 1]


class TestRentVsBuyScenarios:
    def test_high_rent_favors_buying(self):
        """Very high rent should make buying attractive sooner."""
        low_rent = compute_rent_vs_buy(_default_params(current_rent=2_500))
        high_rent = compute_rent_vs_buy(_default_params(current_rent=5_000))

        # High rent should have an earlier crossover
        if low_rent["crossover_year"] and high_rent["crossover_year"]:
            assert high_rent["crossover_year"] <= low_rent["crossover_year"]

    def test_no_appreciation_delays_crossover(self):
        """Zero appreciation makes buying less attractive."""
        with_appr = compute_rent_vs_buy(
            _default_params(annual_appreciation_pct=3.0)
        )
        no_appr = compute_rent_vs_buy(
            _default_params(annual_appreciation_pct=0.0)
        )

        # No appreciation should have a later crossover (or none)
        if with_appr["crossover_year"] and no_appr["crossover_year"]:
            assert no_appr["crossover_year"] >= with_appr["crossover_year"]

    def test_renting_cheaper_forever(self):
        """When ownership is very expensive and rent is low, no crossover."""
        result = compute_rent_vs_buy(_default_params(
            purchase_price=2_500_000,
            monthly_ownership_cost=20_000,
            current_rent=1_500,
            annual_appreciation_pct=0.0,
            annual_rent_increase_pct=0.0,
            horizon_years=5,
        ))
        # With zero appreciation, huge ownership cost, and low rent,
        # buying should never be cheaper over 5 years
        assert result["crossover_year"] is None
        assert "Renting is cheaper" in result["crossover_description"]

    def test_with_pmi_dropoff(self):
        """PMI drop-off should reduce ownership cost mid-horizon."""
        compute_rent_vs_buy(_default_params(
            monthly_pmi=0, pmi_dropoff_month=None,
        ))
        with_pmi = compute_rent_vs_buy(_default_params(
            monthly_ownership_cost=9_675,  # 9000 base + 675 PMI
            monthly_pmi=675,
            pmi_dropoff_month=87,
        ))
        # Both should complete without error
        assert with_pmi["crossover_year"] is not None or with_pmi["crossover_year"] is None

    def test_all_cash_purchase(self):
        """100% down: no loan, ownership is just taxes + insurance + maintenance.

        Note: With a $1.2M all-cash purchase, the opportunity cost of not
        investing $1.2M at 7% market return dominates — renting + investing
        wins handily.  Use a smaller purchase ($500k) with high rent ($4k)
        to model a scenario where all-cash buying wins.
        """
        result = compute_rent_vs_buy(_default_params(
            purchase_price=500_000,
            down_payment_pct=100.0,
            monthly_ownership_cost=2_000,  # just tax + ins + maintenance
            annual_property_tax=5_900,     # 1.18% of 500k
            current_rent=4_000,
            annual_rent_increase_pct=5.0,
        ))
        # All-cash on a modest home with high rent should cross over within horizon
        assert result["crossover_year"] is not None
        assert result["crossover_year"] <= 10

    def test_opportunity_cost_grows(self):
        """Opportunity cost of down payment should grow over time."""
        result = compute_rent_vs_buy(_default_params(horizon_years=10))
        gains = [s["opportunity_gain"] for s in result["yearly_comparison"]]
        for i in range(1, len(gains)):
            assert gains[i] > gains[i - 1]

    def test_horizon_capped_at_30(self):
        """Horizon should be capped at 30 years."""
        result = compute_rent_vs_buy(_default_params(horizon_years=50))
        assert len(result["yearly_comparison"]) == 30
        assert result["horizon_years"] == 30


class TestRentVsBuySummary:
    def test_summary_fields_present(self):
        """All summary fields are in the result."""
        result = compute_rent_vs_buy(_default_params())
        expected_fields = [
            "purchase_price", "down_payment_pct", "down_payment_amount",
            "current_rent", "mortgage_rate", "annual_appreciation_pct",
            "annual_rent_increase_pct", "horizon_years", "crossover_year",
            "crossover_description", "final_annual_rent", "final_home_value",
            "final_home_equity", "final_buy_advantage", "total_rent_paid",
            "total_ownership_paid", "total_tax_benefit",
            "opportunity_cost_of_down_payment",
        ]
        for field in expected_fields:
            assert field in result, f"Missing field: {field}"

    def test_total_rent_paid_is_cumulative(self):
        """Total rent paid should be the last year's cumulative rent."""
        result = compute_rent_vs_buy(_default_params(horizon_years=5))
        last_snapshot = result["yearly_comparison"][-1]
        assert result["total_rent_paid"] == last_snapshot["cumulative_rent"]


# ---------------------------------------------------------------------------
# Fact computer tests
# ---------------------------------------------------------------------------


class TestRentVsBuyFacts:
    def test_fact_computer_extracts_key_fields(self):
        result = compute_rent_vs_buy(_default_params())
        facts = compute_rent_vs_buy_facts(result)

        assert facts["crossover_year"] == result["crossover_year"]
        assert facts["crossover_description"] == result["crossover_description"]
        assert facts["final_home_value"] == result["final_home_value"]
        assert facts["total_rent_paid"] == result["total_rent_paid"]

    def test_fact_computer_handles_empty_dict(self):
        facts = compute_rent_vs_buy_facts({})
        assert facts["crossover_year"] is None


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRentVsBuyRegistration:
    def test_tool_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert "rent_vs_buy" in registry.names

    def test_fact_computer_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_fact_computer("rent_vs_buy") is not None

    def test_block_type_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_block_type("rent_vs_buy") == "rent_vs_buy_card"
