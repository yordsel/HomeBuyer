"""Tests for the PMI model tool.

Phase F-3 (#56) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_pmi_model_facts
from homebuyer.services.faketor.tools.gap.pmi_model import (
    PmiModelParams,
    compute_pmi_model,
    _pmi_rate_for_ltv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_params(**overrides) -> PmiModelParams:
    defaults = {
        "purchase_price": 1_200_000,
        "down_payment_pct": 10.0,
        "mortgage_rate": 7.0,
        "annual_appreciation_pct": 3.0,
        "monthly_savings": None,
        "wait_months": 12,
    }
    defaults.update(overrides)
    return PmiModelParams(**defaults)


# ---------------------------------------------------------------------------
# PMI rate table tests
# ---------------------------------------------------------------------------


class TestPmiRateTable:
    def test_high_ltv_rate(self):
        """LTV of 92% should get the high bracket rate (1.10%)."""
        assert _pmi_rate_for_ltv(0.92) == 0.0110

    def test_mid_ltv_rate(self):
        """LTV of 82% should get the mid bracket rate (0.75%)."""
        assert _pmi_rate_for_ltv(0.82) == 0.0075

    def test_at_threshold_no_pmi(self):
        """LTV of exactly 80% should have no PMI."""
        assert _pmi_rate_for_ltv(0.80) == 0.0

    def test_below_threshold_no_pmi(self):
        """LTV below 80% should have no PMI."""
        assert _pmi_rate_for_ltv(0.75) == 0.0

    def test_at_85_boundary(self):
        """LTV of exactly 85% is in the mid bracket (80.01-85%)."""
        assert _pmi_rate_for_ltv(0.85) == 0.0075

    def test_just_above_85(self):
        """LTV of 85.01% is in the high bracket."""
        assert _pmi_rate_for_ltv(0.8501) == 0.0110


# ---------------------------------------------------------------------------
# Core computation tests
# ---------------------------------------------------------------------------


class TestComputePmiModel:
    def test_20pct_down_no_pmi(self):
        """20% down payment: no PMI applicable."""
        result = compute_pmi_model(_default_params(down_payment_pct=20.0))
        assert result["pmi_applicable"] is False
        assert result["monthly_pmi"] == 0
        assert result["pmi_dropoff_month"] is None
        assert result["total_pmi_cost"] == 0
        assert result["no_pmi_note"] is not None
        assert "20.0%" in result["no_pmi_note"]

    def test_10pct_down_has_pmi(self):
        """10% down on $1.2M: PMI should be applicable."""
        result = compute_pmi_model(_default_params())
        assert result["pmi_applicable"] is True
        assert result["initial_ltv_pct"] == 90.0
        # 10% down → LTV=0.90 → high bracket (1.10%)
        # $1,080,000 * 0.011 / 12 = 990
        assert result["monthly_pmi"] == 990
        assert result["annual_pmi"] == 990 * 12
        assert result["pmi_dropoff_month"] is not None
        assert result["total_pmi_cost"] > 0

    def test_15pct_down_mid_bracket(self):
        """15% down → LTV=0.85 → mid bracket (0.75%)."""
        result = compute_pmi_model(_default_params(down_payment_pct=15.0))
        assert result["pmi_applicable"] is True
        assert result["initial_ltv_pct"] == 85.0
        assert result["current_pmi_rate_pct"] == 0.75
        # $1,020,000 * 0.0075 / 12 = 637.5 → 638
        assert result["monthly_pmi"] == 638

    def test_5pct_down_higher_rate(self):
        """5% down → LTV=0.95 → high bracket (1.10%)."""
        result = compute_pmi_model(_default_params(down_payment_pct=5.0))
        assert result["pmi_applicable"] is True
        assert result["initial_ltv_pct"] == 95.0
        assert result["current_pmi_rate_pct"] == 1.10
        # $1,140,000 * 0.011 / 12 = 1045
        assert result["monthly_pmi"] == 1045

    def test_appreciation_accelerates_dropoff(self):
        """Higher appreciation should produce earlier PMI drop-off."""
        low_appr = compute_pmi_model(_default_params(annual_appreciation_pct=0.0))
        high_appr = compute_pmi_model(_default_params(annual_appreciation_pct=5.0))

        assert low_appr["pmi_dropoff_month"] is not None
        assert high_appr["pmi_dropoff_month"] is not None
        assert high_appr["pmi_dropoff_month"] < low_appr["pmi_dropoff_month"]

    def test_appreciation_acceleration_months(self):
        """The tool should report how many months appreciation saves."""
        result = compute_pmi_model(_default_params())
        assert result["appreciation_acceleration_months"] is not None
        assert result["appreciation_acceleration_months"] > 0
        # Combined drop-off + acceleration = amort-only drop-off
        assert (
            result["pmi_dropoff_month"] + result["appreciation_acceleration_months"]
            == result["pmi_dropoff_via_amortization_only_month"]
        )

    def test_total_pmi_equals_bracket_sum(self):
        """Total PMI cost should equal sum of bracket costs."""
        result = compute_pmi_model(_default_params())
        bracket_total = sum(b["total_cost_in_bracket"] for b in result["ltv_brackets"])
        assert bracket_total == result["total_pmi_cost"]

    def test_dropoff_description_present(self):
        """Drop-off description should be a human-readable string."""
        result = compute_pmi_model(_default_params())
        assert result["pmi_dropoff_description"] is not None
        assert "PMI drops after" in result["pmi_dropoff_description"]
        assert result["pmi_dropoff_years"] is not None
        assert result["pmi_dropoff_years"] > 0


class TestBuyNowVsWait:
    def test_wait_analysis_none_when_no_savings(self):
        """When monthly_savings is None, wait_analysis should be None."""
        result = compute_pmi_model(_default_params(monthly_savings=None))
        assert result["wait_analysis"] is None

    def test_buy_now_verdict_high_appreciation(self):
        """With high appreciation, market outpaces savings → buy_now."""
        result = compute_pmi_model(_default_params(
            monthly_savings=500,
            wait_months=12,
            annual_appreciation_pct=5.0,
        ))
        wait = result["wait_analysis"]
        assert wait is not None
        # $500/mo * 12 = $6k saved vs ~$60k price increase at 5% on $1.2M
        assert wait["verdict"] == "buy_now"
        assert wait["price_increase"] > wait["pmi_savings_from_waiting"]

    def test_wait_verdict_near_threshold(self):
        """Buyer near 20% threshold with aggressive savings → wait.

        At 19% down on $600k with $5k/mo savings over 4 months and low
        appreciation (0.5%), saving $20k pushes the buyer past 20% LTV,
        eliminating all PMI for a modest price increase.
        """
        result = compute_pmi_model(_default_params(
            purchase_price=600_000,
            down_payment_pct=19.0,
            monthly_savings=5_000,
            wait_months=4,
            annual_appreciation_pct=0.5,
        ))
        wait = result["wait_analysis"]
        assert wait is not None
        # Saving $20k pushes past 20% threshold, eliminating all PMI
        assert wait["new_down_payment_pct"] >= 20.0
        assert wait["total_pmi_cost_after_wait"] == 0
        assert wait["verdict"] == "wait"

    def test_wait_analysis_fields_present(self):
        """Wait analysis should have all expected fields."""
        result = compute_pmi_model(_default_params(monthly_savings=1_000))
        wait = result["wait_analysis"]
        assert wait is not None
        expected_fields = [
            "wait_months", "monthly_savings", "savings_gained",
            "projected_purchase_price", "price_increase",
            "new_down_payment_amount", "new_down_payment_pct",
            "new_monthly_pmi", "new_pmi_dropoff_month",
            "total_pmi_cost_buy_now", "total_pmi_cost_after_wait",
            "pmi_savings_from_waiting", "net_cost_of_waiting",
            "verdict", "verdict_description",
        ]
        for field in expected_fields:
            assert field in wait, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Fact computer tests
# ---------------------------------------------------------------------------


class TestPmiModelFacts:
    def test_fact_computer_extracts_headline_fields(self):
        result = compute_pmi_model(_default_params())
        facts = compute_pmi_model_facts(result)

        assert facts["pmi_applicable"] == result["pmi_applicable"]
        assert facts["monthly_pmi"] == result["monthly_pmi"]
        assert facts["pmi_dropoff_month"] == result["pmi_dropoff_month"]
        assert facts["total_pmi_cost"] == result["total_pmi_cost"]

    def test_fact_computer_with_wait_analysis(self):
        result = compute_pmi_model(_default_params(monthly_savings=1_000))
        facts = compute_pmi_model_facts(result)

        assert facts["wait_verdict"] == result["wait_analysis"]["verdict"]
        assert facts["net_cost_of_waiting"] == result["wait_analysis"]["net_cost_of_waiting"]

    def test_fact_computer_handles_empty_dict(self):
        facts = compute_pmi_model_facts({})
        assert facts["pmi_applicable"] is None
        assert facts["wait_verdict"] is None


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestPmiModelRegistration:
    def test_tool_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert "pmi_model" in registry.names

    def test_fact_computer_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_fact_computer("pmi_model") is not None

    def test_block_type_registered(self):
        from homebuyer.services.faketor.tools import registry
        assert registry.get_block_type("pmi_model") == "pmi_model_card"
