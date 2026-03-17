"""Tests for the true cost ownership calculator.

Phase F-1 (#54) of Epic #23.
"""

from homebuyer.services.faketor.facts import compute_true_cost_facts
from homebuyer.services.faketor.tools.gap.true_cost import (
    TrueCostParams,
    _calc_monthly_earthquake,
    _calc_monthly_maintenance,
    _calc_monthly_pi,
    _calc_monthly_pmi,
    calc_pmi_dropoff_month,
    compute_true_cost,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_params(**overrides) -> TrueCostParams:
    """Create default TrueCostParams with optional overrides."""
    defaults = {
        "purchase_price": 1_200_000,
        "down_payment_pct": 20.0,
        "mortgage_rate": 7.0,
        "year_built": 1950,
        "construction_type": "wood_frame",
        "hoa_monthly": 0,
        "current_rent": None,
    }
    defaults.update(overrides)
    return TrueCostParams(**defaults)


# ---------------------------------------------------------------------------
# Component tests
# ---------------------------------------------------------------------------


class TestMonthlyPI:
    def test_standard_loan(self):
        """$960k loan at 7% should be roughly $6,388/mo."""
        pi = _calc_monthly_pi(960_000, 7.0)
        assert 6300 < pi < 6500

    def test_zero_loan(self):
        """All-cash purchase: $0 P&I."""
        assert _calc_monthly_pi(0, 7.0) == 0

    def test_higher_rate(self):
        """Higher rate should produce higher payment."""
        low = _calc_monthly_pi(960_000, 5.0)
        high = _calc_monthly_pi(960_000, 8.0)
        assert high > low


class TestMonthlyPMI:
    def test_no_pmi_at_20_percent(self):
        """20% down → no PMI."""
        assert _calc_monthly_pmi(960_000, 1_200_000) == 0

    def test_pmi_at_10_percent(self):
        """10% down → PMI on $1.08M loan at 1.10% (LTV 90%)."""
        pmi = _calc_monthly_pmi(1_080_000, 1_200_000)
        # 1.10% of $1.08M / 12 = $990
        assert pmi == 990

    def test_pmi_at_5_percent(self):
        """5% down → PMI on $1.14M loan at 1.10% (LTV 95%)."""
        pmi = _calc_monthly_pmi(1_140_000, 1_200_000)
        assert pmi == 1045  # round(1_140_000 * 0.011 / 12) = 1045

    def test_pmi_exactly_at_threshold(self):
        """Exactly 80% LTV → no PMI (threshold is <=)."""
        assert _calc_monthly_pmi(960_000, 1_200_000) == 0


class TestPMIDropoff:
    def test_no_dropoff_when_no_pmi(self):
        """20% down → no PMI dropoff."""
        assert calc_pmi_dropoff_month(960_000, 1_200_000, 7.0) is None

    def test_dropoff_exists_for_10_percent(self):
        """10% down should have a dropoff month."""
        month = calc_pmi_dropoff_month(1_080_000, 1_200_000, 7.0)
        assert month is not None
        assert 60 < month < 180  # reasonable range

    def test_lower_rate_drops_sooner(self):
        """Lower rate means faster principal paydown."""
        high = calc_pmi_dropoff_month(1_080_000, 1_200_000, 8.0)
        low = calc_pmi_dropoff_month(1_080_000, 1_200_000, 4.0)
        assert low < high


class TestEarthquakeInsurance:
    def test_wood_frame(self):
        """Wood frame: 0.25% of 80% of $1.2M / 12."""
        eq = _calc_monthly_earthquake(1_200_000, "wood_frame")
        # 1_200_000 * 0.80 * 0.0025 / 12 = 200
        assert eq == 200

    def test_masonry_higher(self):
        """Masonry should be more expensive than wood frame."""
        wood = _calc_monthly_earthquake(1_200_000, "wood_frame")
        masonry = _calc_monthly_earthquake(1_200_000, "masonry")
        assert masonry > wood

    def test_soft_story_highest(self):
        """Soft story is the most expensive construction type."""
        soft = _calc_monthly_earthquake(1_200_000, "soft_story")
        masonry = _calc_monthly_earthquake(1_200_000, "masonry")
        assert soft > masonry

    def test_unknown_type_defaults_to_wood(self):
        """Unknown construction type falls back to wood_frame rate."""
        unknown = _calc_monthly_earthquake(1_200_000, "unknown_type")
        wood = _calc_monthly_earthquake(1_200_000, "wood_frame")
        assert unknown == wood


class TestMaintenanceReserve:
    def test_new_construction(self):
        """< 10 years old: 0.75% rate."""
        maint = _calc_monthly_maintenance(1_200_000, 2020)
        # 1_200_000 * 0.0075 / 12 = 750
        assert maint == 750

    def test_old_property(self):
        """40+ years old (built 1950): 1.5% rate."""
        maint = _calc_monthly_maintenance(1_200_000, 1950)
        # 1_200_000 * 0.015 / 12 = 1500
        assert maint == 1500

    def test_mid_age(self):
        """20-39 years old: 1.25% rate."""
        maint = _calc_monthly_maintenance(1_200_000, 2000)
        # 1_200_000 * 0.0125 / 12 = 1250
        assert maint == 1250

    def test_unknown_year(self):
        """Unknown year_built: default 1.0% rate."""
        maint = _calc_monthly_maintenance(1_200_000, None)
        # 1_200_000 * 0.01 / 12 = 1000
        assert maint == 1000


# ---------------------------------------------------------------------------
# Full compute_true_cost tests
# ---------------------------------------------------------------------------


class TestComputeTrueCost:
    def test_baseline_20_percent_down(self):
        """Standard 20% down, no PMI, no HOA."""
        result = compute_true_cost(_default_params())

        assert result["purchase_price"] == 1_200_000
        assert result["down_payment_amount"] == 240_000
        assert result["loan_amount"] == 960_000
        assert result["is_pmi_applicable"] is False
        assert result["monthly_pmi"] == 0
        assert result["monthly_hoa"] == 0
        assert result["pmi_note"] is None

        # Total should be sum of all components
        total = (
            result["monthly_principal_and_interest"]
            + result["monthly_property_tax"]
            + result["monthly_hoi"]
            + result["monthly_earthquake_insurance"]
            + result["monthly_maintenance_reserve"]
            + result["monthly_pmi"]
            + result["monthly_hoa"]
        )
        assert result["total_monthly_cost"] == total
        assert result["total_monthly_cost_no_eq"] == total - result["monthly_earthquake_insurance"]

    def test_10_percent_down_has_pmi(self):
        """10% down triggers PMI."""
        result = compute_true_cost(_default_params(down_payment_pct=10.0))

        assert result["down_payment_amount"] == 120_000
        assert result["loan_amount"] == 1_080_000
        assert result["is_pmi_applicable"] is True
        assert result["monthly_pmi"] > 0
        assert result["pmi_note"] is not None
        assert "drops when balance reaches" in result["pmi_note"]

    def test_masonry_construction(self):
        """Masonry construction has higher earthquake insurance."""
        wood = compute_true_cost(_default_params(construction_type="wood_frame"))
        masonry = compute_true_cost(_default_params(construction_type="masonry"))

        assert masonry["monthly_earthquake_insurance"] > wood["monthly_earthquake_insurance"]
        assert masonry["total_monthly_cost"] > wood["total_monthly_cost"]

    def test_with_current_rent(self):
        """Rent comparison fields populated when current_rent is given."""
        result = compute_true_cost(_default_params(current_rent=3_800))

        assert result["current_rent"] == 3_800
        assert result["monthly_delta_vs_rent"] is not None
        assert result["delta_direction"] == "more_than_rent"
        assert result["monthly_delta_vs_rent"] == (
            result["total_monthly_cost"] - 3_800
        )

    def test_without_current_rent(self):
        """No rent comparison when current_rent is None."""
        result = compute_true_cost(_default_params())

        assert result["current_rent"] is None
        assert result["monthly_delta_vs_rent"] is None
        assert result["delta_direction"] is None

    def test_old_property_higher_maintenance(self):
        """1925 property has higher maintenance than 2020 property."""
        old = compute_true_cost(_default_params(year_built=1925))
        new = compute_true_cost(_default_params(year_built=2020))

        assert old["monthly_maintenance_reserve"] > new["monthly_maintenance_reserve"]

    def test_with_hoa(self):
        """HOA dues are added to total."""
        no_hoa = compute_true_cost(_default_params(hoa_monthly=0))
        with_hoa = compute_true_cost(_default_params(hoa_monthly=500))

        assert with_hoa["monthly_hoa"] == 500
        assert with_hoa["total_monthly_cost"] == no_hoa["total_monthly_cost"] + 500

    def test_all_cash_purchase(self):
        """100% down: no P&I, no PMI."""
        result = compute_true_cost(_default_params(down_payment_pct=100.0))

        assert result["loan_amount"] == 0
        assert result["monthly_principal_and_interest"] == 0
        assert result["monthly_pmi"] == 0
        assert result["is_pmi_applicable"] is False
        # Still has tax, insurance, maintenance
        assert result["total_monthly_cost"] > 0

    def test_rent_equal_to_cost(self):
        """When rent equals total cost, delta_direction is 'equal'."""
        result = compute_true_cost(_default_params())
        total = result["total_monthly_cost"]
        result2 = compute_true_cost(_default_params(current_rent=total))
        assert result2["delta_direction"] == "equal"
        assert result2["monthly_delta_vs_rent"] == 0

    def test_rent_more_than_cost(self):
        """When rent exceeds ownership cost (unusual), direction is 'less_than_rent'."""
        result = compute_true_cost(_default_params(current_rent=999_999))
        assert result["delta_direction"] == "less_than_rent"
        assert result["monthly_delta_vs_rent"] < 0


# ---------------------------------------------------------------------------
# Fact computer tests
# ---------------------------------------------------------------------------


class TestTrueCostFacts:
    def test_fact_computer_extracts_key_fields(self):
        """Fact computer extracts the fields Claude needs to cite."""
        result = compute_true_cost(_default_params(current_rent=3_800))
        facts = compute_true_cost_facts(result)

        assert facts["total_monthly_cost"] == result["total_monthly_cost"]
        assert facts["monthly_pi"] == result["monthly_principal_and_interest"]
        assert facts["monthly_tax"] == result["monthly_property_tax"]
        assert facts["monthly_insurance"] == result["monthly_hoi"]
        assert facts["monthly_pmi"] == result["monthly_pmi"]
        assert facts["monthly_hoa"] == result["monthly_hoa"]
        assert facts["is_pmi_applicable"] == result["is_pmi_applicable"]
        assert facts["monthly_delta_vs_rent"] == result["monthly_delta_vs_rent"]
        assert facts["delta_direction"] == result["delta_direction"]

    def test_fact_computer_handles_missing_fields(self):
        """Fact computer doesn't crash on empty dict."""
        facts = compute_true_cost_facts({})
        assert facts["total_monthly_cost"] is None
        assert facts["monthly_pi"] is None


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestTrueCostRegistration:
    def test_tool_registered(self):
        """compute_true_cost is registered in the tool registry."""
        from homebuyer.services.faketor.tools import registry

        assert "compute_true_cost" in registry.names

    def test_tool_schema_present(self):
        """Tool schema is available for the Anthropic API."""
        from homebuyer.services.faketor.tools import registry

        schemas = registry.get_tool_schemas()
        names = [s["name"] for s in schemas]
        assert "compute_true_cost" in names

    def test_fact_computer_registered(self):
        """Fact computer is discoverable via registry."""
        from homebuyer.services.faketor.tools import registry

        fc = registry.get_fact_computer("compute_true_cost")
        assert fc is not None

    def test_block_type_registered(self):
        """Block type is set for frontend rendering."""
        from homebuyer.services.faketor.tools import registry

        assert registry.get_block_type("compute_true_cost") == "true_cost_card"
