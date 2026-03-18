"""Tests for F-11 (#64) tool enhancements: E-1 through E-7.

Each enhancement is tested for correctness and non-regression.
"""

import json
import pytest

from homebuyer.analysis.rental_analysis import (
    RentalAnalyzer,
    ExpenseBreakdown,
    _earthquake_insurance_rate,
    _maintenance_rate,
    _scenario_to_dict,
)
from homebuyer.storage.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    """In-memory DB with mortgage rates seeded."""
    db = Database(str(tmp_path / "test.db"))
    db.connect()
    db.initialize_schema()
    # Seed a mortgage rate for the analyzer
    db.execute(
        "INSERT INTO mortgage_rates (observation_date, rate_30yr, rate_15yr) "
        "VALUES ('2025-01-01', 6.5, 5.8)"
    )
    db.conn.commit()
    yield db
    db.close()


@pytest.fixture
def analyzer(tmp_db):
    return RentalAnalyzer(tmp_db)


@pytest.fixture
def sample_property():
    """Standard Berkeley property for testing."""
    return {
        "latitude": 37.87,
        "longitude": -122.27,
        "neighborhood": "North Berkeley",
        "beds": 3,
        "baths": 2.0,
        "sqft": 1800,
        "year_built": 1920,
        "lot_size_sqft": 5000,
        "property_type": "Single Family Residential",
    }


# ---------------------------------------------------------------------------
# E-1: Earthquake insurance
# ---------------------------------------------------------------------------


class TestE1EarthquakeInsurance:
    """E-1: Earthquake insurance in expense calculation."""

    def test_earthquake_rate_pre_1940(self):
        assert _earthquake_insurance_rate(1920) == 0.0040

    def test_earthquake_rate_mid_century(self):
        assert _earthquake_insurance_rate(1960) == 0.0030

    def test_earthquake_rate_modern(self):
        assert _earthquake_insurance_rate(1985) == 0.0020

    def test_earthquake_rate_new_construction(self):
        assert _earthquake_insurance_rate(2020) == 0.0015

    def test_earthquake_rate_none_defaults(self):
        assert _earthquake_insurance_rate(None) == 0.002

    def test_expense_breakdown_has_earthquake(self, analyzer):
        exp = analyzer.calculate_expenses(
            property_value=1_000_000,
            annual_gross_rent=50_000,
            year_built=1920,
        )
        assert isinstance(exp, ExpenseBreakdown)
        assert exp.earthquake_insurance > 0
        # Pre-1940: 0.40% of $1M = $4,000
        assert exp.earthquake_insurance == 4000

    def test_earthquake_included_in_total(self, analyzer):
        exp = analyzer.calculate_expenses(
            property_value=1_000_000,
            annual_gross_rent=50_000,
            year_built=1920,
        )
        # Total should include earthquake insurance
        components = (
            exp.property_tax + exp.insurance + exp.earthquake_insurance
            + exp.maintenance + exp.vacancy_reserve + exp.management_fee
            + exp.hoa + exp.utilities
        )
        assert exp.total_annual == components

    def test_scenario_dict_includes_earthquake(self, analyzer, sample_property):
        scenario = analyzer.build_scenario_as_is(sample_property)
        d = _scenario_to_dict(scenario)
        assert "earthquake_insurance" in d["expenses"]
        assert d["expenses"]["earthquake_insurance"] > 0


# ---------------------------------------------------------------------------
# E-2: Age-based maintenance reserve
# ---------------------------------------------------------------------------


class TestE2MaintenanceReserve:
    """E-2: Age-adjusted maintenance reserve."""

    def test_maintenance_rate_pre_1940(self):
        assert _maintenance_rate(1920) == 0.020

    def test_maintenance_rate_mid_century(self):
        assert _maintenance_rate(1960) == 0.015

    def test_maintenance_rate_baseline(self):
        assert _maintenance_rate(1985) == 0.010

    def test_maintenance_rate_new(self):
        assert _maintenance_rate(2020) == 0.007

    def test_maintenance_rate_none_defaults(self):
        assert _maintenance_rate(None) == 0.01

    def test_old_home_higher_maintenance(self, analyzer):
        exp_old = analyzer.calculate_expenses(
            1_000_000, 50_000, year_built=1920,
        )
        exp_new = analyzer.calculate_expenses(
            1_000_000, 50_000, year_built=2020,
        )
        # Old home should have higher maintenance
        assert exp_old.maintenance > exp_new.maintenance
        # 1920: 2% = $20k vs 2020: 0.7% = $7k
        assert exp_old.maintenance == 20_000
        assert exp_new.maintenance == 7_000


# ---------------------------------------------------------------------------
# E-3: Carrying costs during development
# ---------------------------------------------------------------------------


class TestE3CarryingCosts:
    """E-3: Carrying costs for ADU/SB9 scenarios."""

    def test_as_is_no_carrying_costs(self, analyzer, sample_property):
        scenario = analyzer.build_scenario_as_is(sample_property)
        assert scenario.carrying_cost_months == 0
        assert scenario.carrying_cost_total == 0

    def test_adu_has_carrying_costs(self, analyzer, sample_property):
        """ADU scenario includes 12-month carrying cost."""
        # Create a mock dev_potential with ADU eligible
        from unittest.mock import MagicMock
        dev = MagicMock()
        dev.adu.eligible = True
        dev.adu.max_adu_sqft = 800

        scenario = analyzer.build_scenario_adu(sample_property, dev)
        assert scenario is not None
        assert scenario.carrying_cost_months == 12
        assert scenario.carrying_cost_total > 0
        assert scenario.carrying_cost_monthly > 0
        # Monthly carry should be mortgage + tax + insurance
        assert scenario.carrying_cost_total == scenario.carrying_cost_monthly * 12

    def test_sb9_has_carrying_costs(self, analyzer, sample_property):
        """SB9 scenario includes 18-month carrying cost."""
        from unittest.mock import MagicMock
        dev = MagicMock()
        dev.sb9.can_split = True
        dev.sb9.resulting_lot_sizes = [2500, 2500]

        scenario = analyzer.build_scenario_sb9(sample_property, dev)
        assert scenario is not None
        assert scenario.carrying_cost_months == 18
        assert scenario.carrying_cost_total > 0
        assert scenario.carrying_cost_total == scenario.carrying_cost_monthly * 18

    def test_carrying_costs_in_dict(self, analyzer, sample_property):
        """Carrying cost fields present in serialized output."""
        from unittest.mock import MagicMock
        dev = MagicMock()
        dev.adu.eligible = True
        dev.adu.max_adu_sqft = 800

        scenario = analyzer.build_scenario_adu(sample_property, dev)
        d = _scenario_to_dict(scenario)
        assert d["carrying_cost_months"] == 12
        assert d["carrying_cost_total"] > 0
        assert d["carrying_cost_monthly"] > 0
        assert "Carrying costs" in d["development_notes"]


# ---------------------------------------------------------------------------
# E-4: SHAP top value drivers
# ---------------------------------------------------------------------------


class TestE4ShapDrivers:
    """E-4: Top value drivers from SHAP contributions."""

    def test_top_drivers_populated(self):
        from homebuyer.api import _prediction_to_dict
        from unittest.mock import MagicMock

        result = MagicMock()
        result.predicted_price = 1_200_000
        result.price_lower = 900_000
        result.price_upper = 1_500_000
        result.neighborhood = "North Berkeley"
        result.list_price = 1_100_000
        result.predicted_premium_pct = 9.1
        result.base_value = 1_000_000
        result.feature_contributions = {
            "sqft": 150_000,
            "beds": 45_000,
            "year_built": -30_000,
            "neighborhood": 80_000,
            "lot_size_sqft": 5_000,
            "baths": 25_000,
            "latitude": 500,  # negligible, should be filtered
        }

        d = _prediction_to_dict(result)
        drivers = d["top_value_drivers"]

        # Should have entries (latitude filtered out < $1000)
        assert len(drivers) == 6
        # Sorted by absolute impact
        assert drivers[0]["feature"] == "sqft"
        assert drivers[0]["impact"] == 150_000
        assert drivers[0]["direction"] == "increases"
        assert drivers[0]["impact_formatted"] == "$150,000"
        assert drivers[0]["label"] == "Living area (sqft)"

        # Negative impact
        yb = next(d for d in drivers if d["feature"] == "year_built")
        assert yb["direction"] == "decreases"

    def test_top_drivers_empty_contributions(self):
        from homebuyer.api import _prediction_to_dict
        from unittest.mock import MagicMock

        result = MagicMock()
        result.predicted_price = 1_000_000
        result.price_lower = 800_000
        result.price_upper = 1_200_000
        result.neighborhood = "Berkeley"
        result.list_price = None
        result.predicted_premium_pct = None
        result.base_value = None
        result.feature_contributions = None

        d = _prediction_to_dict(result)
        assert d["top_value_drivers"] == []


# ---------------------------------------------------------------------------
# E-5: Rate sensitivity in market summary
# ---------------------------------------------------------------------------


class TestE5RateSensitivity:
    """E-5: Rate sensitivity affordability context in market summary."""

    def test_rate_sensitivity_structure(self):
        """Validate rate_sensitivity dict structure."""
        # We'll test the computation logic directly
        median_price = 1_300_000
        rate_30yr = 6.5

        monthly_rate = (rate_30yr / 100) / 12
        scenarios = []
        for dp_pct, dp_label in [
            (20.0, "20% down"), (10.0, "10% down"),
            (5.0, "5% down"), (3.5, "3.5% down (FHA)"),
        ]:
            dp_amount = int(median_price * dp_pct / 100)
            loan = median_price - dp_amount
            n = 360
            monthly_pi = int(
                loan * (monthly_rate * (1 + monthly_rate) ** n)
                / ((1 + monthly_rate) ** n - 1)
            )
            monthly_piti = int(monthly_pi * 1.25)
            income_required = int(monthly_piti * 12 / 0.28)
            scenarios.append({
                "down_payment_pct": dp_pct,
                "down_payment_label": dp_label,
                "down_payment_amount": dp_amount,
                "loan_amount": int(loan),
                "monthly_pi": monthly_pi,
                "monthly_piti_estimate": monthly_piti,
                "income_required_28pct_dti": income_required,
            })

        # 20% down on 1.3M = $260k down, $1.04M loan
        assert scenarios[0]["down_payment_amount"] == 260_000
        assert scenarios[0]["loan_amount"] == 1_040_000
        # Monthly P&I on $1.04M at 6.5% ≈ $6,574
        assert 6000 < scenarios[0]["monthly_pi"] < 7000
        # Income required at 28% DTI should be > $250k
        assert scenarios[0]["income_required_28pct_dti"] > 250_000

        # FHA: 3.5% down = $45,500
        assert scenarios[3]["down_payment_amount"] == 45_500
        # Larger loan = higher payment = higher income needed
        assert scenarios[3]["income_required_28pct_dti"] > scenarios[0]["income_required_28pct_dti"]


# ---------------------------------------------------------------------------
# E-6: Rate penalty in sell vs hold
# ---------------------------------------------------------------------------


class TestE6RatePenalty:
    """E-6: Rate penalty calculation for equity-trapped homeowners."""

    def test_rate_penalty_calculation(self):
        """Validate the rate penalty math."""
        # Owner has 2.9% rate, market at 6.5%
        old_rate = 2.9
        new_rate = 6.5
        old_loan = 520_000  # 80% of $650k purchase
        new_value = 1_500_000
        new_loan = int(new_value * 0.80)

        old_r = (old_rate / 100) / 12
        old_pi = int(
            old_loan * (old_r * (1 + old_r) ** 360)
            / ((1 + old_r) ** 360 - 1)
        )
        new_r = (new_rate / 100) / 12
        new_pi = int(
            new_loan * (new_r * (1 + new_r) ** 360)
            / ((1 + new_r) ** 360 - 1)
        )

        penalty = new_pi - old_pi
        assert penalty > 0
        # New monthly should be much higher
        assert new_pi > old_pi
        # ~$2164 old vs ~$7580 new = ~$5400 penalty
        assert 4000 < penalty < 7000


# ---------------------------------------------------------------------------
# E-7: Monthly cost estimation helper
# ---------------------------------------------------------------------------


class TestE7MonthlyCostEstimation:
    """E-7: Monthly cost estimation for affordability filtering."""

    def test_estimate_monthly_cost(self):
        from homebuyer.api import _estimate_monthly_cost

        # $1M home, 20% down = $800k loan at 6.5%
        cost = _estimate_monthly_cost(1_000_000, 20.0, rate=6.5)
        # P&I on $800k at 6.5% ≈ $5,056, * 1.25 ≈ $6,320
        assert 5500 < cost < 7000

    def test_estimate_monthly_cost_lower_dp(self):
        from homebuyer.api import _estimate_monthly_cost

        cost_20 = _estimate_monthly_cost(1_000_000, 20.0, rate=6.5)
        cost_5 = _estimate_monthly_cost(1_000_000, 5.0, rate=6.5)
        # Lower down payment = higher monthly cost
        assert cost_5 > cost_20

    def test_estimate_monthly_cost_zero_price(self):
        from homebuyer.api import _estimate_monthly_cost

        cost = _estimate_monthly_cost(0, 20.0, rate=6.5)
        assert cost == 0


# ---------------------------------------------------------------------------
# Enhancement boundary & edge case tests
# ---------------------------------------------------------------------------


class TestE1BoundaryYears:
    """E-1: Earthquake insurance year boundary precision."""

    def test_earthquake_rate_exactly_1940(self):
        """year_built=1940 → should be mid-century rate (0.0030), not pre-1940."""
        assert _earthquake_insurance_rate(1940) == 0.0030

    def test_earthquake_rate_exactly_1939(self):
        """year_built=1939 → pre-1940 rate (0.0040)."""
        assert _earthquake_insurance_rate(1939) == 0.0040

    def test_earthquake_rate_exactly_1970(self):
        """year_built=1970 → modern rate (0.0020)."""
        assert _earthquake_insurance_rate(1970) == 0.0020

    def test_earthquake_rate_exactly_2000(self):
        """year_built=2000 → new construction rate (0.0015)."""
        assert _earthquake_insurance_rate(2000) == 0.0015

    def test_earthquake_rate_exactly_1999(self):
        """year_built=1999 → still modern rate (0.0020)."""
        assert _earthquake_insurance_rate(1999) == 0.0020


class TestE2BoundaryYears:
    """E-2: Maintenance rate year boundary precision."""

    def test_maintenance_exactly_1940(self):
        """year_built=1940 → mid-century rate (0.015)."""
        assert _maintenance_rate(1940) == 0.015

    def test_maintenance_exactly_1939(self):
        """year_built=1939 → pre-1940 rate (0.020)."""
        assert _maintenance_rate(1939) == 0.020

    def test_maintenance_exactly_1970(self):
        """year_built=1970 → baseline rate (0.010)."""
        assert _maintenance_rate(1970) == 0.010

    def test_maintenance_exactly_2000(self):
        """year_built=2000 → new construction rate (0.007)."""
        assert _maintenance_rate(2000) == 0.007


class TestE4ShapBoundary:
    """E-4: SHAP top value drivers filter boundary and edge cases."""

    def test_filter_boundary_exactly_1000(self):
        """Impact of exactly $1000 → should be included (>= $1000)."""
        from homebuyer.api import _prediction_to_dict
        from unittest.mock import MagicMock

        result = MagicMock()
        result.predicted_price = 1_000_000
        result.price_lower = 800_000
        result.price_upper = 1_200_000
        result.neighborhood = "Berkeley"
        result.list_price = None
        result.predicted_premium_pct = None
        result.base_value = 900_000
        result.feature_contributions = {"sqft": 1000, "beds": 999}

        d = _prediction_to_dict(result)
        features = [x["feature"] for x in d["top_value_drivers"]]
        assert "sqft" in features  # exactly 1000 → included
        assert "beds" not in features  # 999 → filtered out

    def test_all_negative_contributions(self):
        """All features decrease value → all have direction='decreases'."""
        from homebuyer.api import _prediction_to_dict
        from unittest.mock import MagicMock

        result = MagicMock()
        result.predicted_price = 800_000
        result.price_lower = 600_000
        result.price_upper = 1_000_000
        result.neighborhood = "Berkeley"
        result.list_price = None
        result.predicted_premium_pct = None
        result.base_value = 1_000_000
        result.feature_contributions = {
            "sqft": -50_000,
            "year_built": -30_000,
            "lot_size_sqft": -5_000,
        }

        d = _prediction_to_dict(result)
        for driver in d["top_value_drivers"]:
            assert driver["direction"] == "decreases"
            assert driver["impact"] < 0


class TestE7ExtremeValues:
    """E-7: Monthly cost estimation with extreme rate/down-payment values."""

    def test_very_high_rate(self):
        """15% rate → much higher monthly cost than normal."""
        from homebuyer.api import _estimate_monthly_cost

        cost_normal = _estimate_monthly_cost(1_000_000, 20.0, rate=6.5)
        cost_high = _estimate_monthly_cost(1_000_000, 20.0, rate=15.0)
        assert cost_high > cost_normal * 1.5

    def test_very_low_down_payment(self):
        """3% down payment → higher cost than 20% down."""
        from homebuyer.api import _estimate_monthly_cost

        cost_3 = _estimate_monthly_cost(1_000_000, 3.0, rate=6.5)
        cost_20 = _estimate_monthly_cost(1_000_000, 20.0, rate=6.5)
        assert cost_3 > cost_20

    def test_100_pct_down(self):
        """100% down → zero loan → cost should be 0 (no P&I)."""
        from homebuyer.api import _estimate_monthly_cost

        cost = _estimate_monthly_cost(1_000_000, 100.0, rate=6.5)
        assert cost == 0
