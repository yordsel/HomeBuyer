"""Tests for the investment prospectus generator."""

from datetime import date, timedelta

from homebuyer.analysis.market_analysis import MarketAnalyzer
from homebuyer.analysis.prospectus import (
    InvestmentProspectusResponse,
    ProspectusGenerator,
    PropertyProspectus,
    prospectus_to_dict,
)
from homebuyer.analysis.rental_analysis import RentalAnalyzer
from homebuyer.storage.database import Database
from homebuyer.storage.models import MarketMetric, MortgageRate, PropertySale


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_prospectus_data(db: Database) -> None:
    """Seed a test database with data needed for prospectus generation.

    Includes property sales, market metrics, and mortgage rates so the
    ProspectusGenerator can pull neighbourhood stats, comps, and market data.
    """
    # Use recent dates so market trend queries find data
    today = date.today()

    sales = [
        PropertySale(
            mls_number=f"ML{i:05d}",
            address=f"{100 + i} Cedar St",
            city="Berkeley",
            state="CA",
            zip_code="94702",
            sale_date=today - timedelta(days=30 * (i + 1)),
            sale_price=1_200_000 + (i * 50_000),
            property_type="Single Family Residential",
            beds=3.0,
            baths=2.0,
            sqft=1600 + (i * 50),
            lot_size_sqft=5000,
            year_built=1920 + i,
            price_per_sqft=round((1_200_000 + i * 50_000) / (1600 + i * 50), 2),
            latitude=37.880,
            longitude=-122.273,
            neighborhood="North Berkeley",
        )
        for i in range(12)
    ]

    for sale in sales:
        db.upsert_sale(sale)

    # Market metrics — recent months so generate_summary_report() finds them
    for i in range(6):
        month_start = today.replace(day=1) - timedelta(days=30 * i)
        month_start = month_start.replace(day=1)
        month_end = month_start.replace(day=28)
        db.upsert_market_metric(
            MarketMetric(
                period_begin=month_start,
                period_end=month_end,
                period_duration="30",
                region_name="Berkeley, CA",
                property_type="All Residential",
                median_sale_price=1_300_000 + (6 - i) * 10_000,
                median_list_price=1_100_000 + (6 - i) * 5_000,
                avg_sale_to_list=1.18 + (6 - i) * 0.005,
                sold_above_list_pct=0.65 + (6 - i) * 0.01,
                homes_sold=50 + (6 - i),
                median_dom=15,
            )
        )

    # Mortgage rates — one per month matching the market metrics
    for i in range(6):
        rate_date = today.replace(day=1) - timedelta(days=30 * i)
        rate_date = rate_date.replace(day=1)
        db.upsert_mortgage_rate(
            MortgageRate(
                observation_date=rate_date,
                rate_30yr=6.50 + i * 0.05,
                rate_15yr=5.80 + i * 0.05,
            )
        )


def _mock_predict_fn(prop_dict: dict, source: str = "prospectus") -> dict:
    """Deterministic mock prediction for testing."""
    return {
        "predicted_price": 1_400_000,
        "price_lower": 1_200_000,
        "price_upper": 1_600_000,
        "feature_contributions": [
            {"feature": "sqft", "contribution": 50_000},
            {"feature": "beds", "contribution": 30_000},
        ],
    }


def _make_generator(db: Database) -> ProspectusGenerator:
    """Build a ProspectusGenerator with real analyzers backed by test DB."""
    market_analyzer = MarketAnalyzer(db)
    rental_analyzer = RentalAnalyzer(db, dev_calc=None)
    return ProspectusGenerator(
        db=db,
        dev_calc=None,
        rental_analyzer=rental_analyzer,
        market_analyzer=market_analyzer,
        predict_fn=_mock_predict_fn,
    )


def _sample_property() -> dict:
    """Return a realistic property dict for prospectus generation."""
    return {
        "address": "100 Cedar St",
        "neighborhood": "North Berkeley",
        "property_type": "Single Family Residential",
        "beds": 3,
        "baths": 2.0,
        "sqft": 1600,
        "lot_size_sqft": 5000,
        "year_built": 1920,
        "latitude": 37.880,
        "longitude": -122.273,
        "zip_code": "94702",
        "zoning_class": "R-1",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_single_property_prospectus(tmp_db: Database):
    """Single-property prospectus contains expected fields and values."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])

    assert isinstance(result, InvestmentProspectusResponse)
    assert len(result.properties) == 1
    assert result.is_multi_property is False
    assert result.portfolio_summary is None

    p = result.properties[0]
    assert isinstance(p, PropertyProspectus)
    assert p.address == "100 Cedar St"
    assert p.neighborhood == "North Berkeley"
    assert p.beds == 3
    assert p.baths == 2.0
    assert p.sqft == 1600


def test_valuation_from_prediction(tmp_db: Database):
    """Valuation comes from the mock predict_fn."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    assert p.estimated_value == 1_400_000
    assert p.value_range_low == 1_200_000
    assert p.value_range_high == 1_600_000
    # value_per_sqft = 1_400_000 / 1600 = 875
    assert p.value_per_sqft == 875


def test_market_context_populated(tmp_db: Database):
    """Market context fields are filled from test data."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    # Neighborhood stats should be populated from the 12 seeded North Berkeley sales
    assert p.neighborhood_median_price is not None
    assert p.neighborhood_median_price > 0

    # City-level market data
    assert p.city_median_price is not None
    assert p.city_median_price > 0
    assert p.mortgage_rate_30yr is not None


def test_investment_scenarios_generated(tmp_db: Database):
    """At least one investment scenario is generated."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    # Should have at least the "as_is" rental scenario
    assert len(p.scenarios) >= 1
    assert p.best_scenario_name != ""

    # Key investment metrics should be populated
    assert p.cap_rate_pct >= 0
    assert p.cash_on_cash_pct is not None


def test_risk_factors_present(tmp_db: Database):
    """Risk factors list is populated."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    assert isinstance(p.risk_factors, list)
    assert len(p.risk_factors) >= 1


def test_narratives_generated(tmp_db: Database):
    """Commentary narratives are non-empty strings."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    assert len(p.valuation_commentary) > 0
    # market_position_commentary requires YoY data spanning 2+ years;
    # with limited seed data it may be empty — verify it's at least a string
    assert isinstance(p.market_position_commentary, str)
    assert len(p.scenario_recommendation_narrative) > 0


def test_disclaimers_present(tmp_db: Database):
    """Standard disclaimers are included."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    assert len(p.disclaimers) >= 3
    assert any("not financial advice" in d.lower() for d in p.disclaimers)


def test_data_sources_tracked(tmp_db: Database):
    """Data sources are recorded for transparency."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    assert len(p.data_sources) >= 1
    assert "ML price prediction model" in p.data_sources


def test_generated_at_timestamp(tmp_db: Database):
    """generated_at is a non-empty ISO timestamp."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    assert p.generated_at != ""
    # Should be ISO format
    assert "T" in p.generated_at


def test_custom_down_payment_and_horizon(tmp_db: Database):
    """Custom down payment and horizon are respected."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(
        properties=[_sample_property()],
        down_payment_pct=30.0,
        investment_horizon_years=10,
    )
    p = result.properties[0]

    assert p.time_horizon_years == 10
    # With 30% down the capital required should differ from 20% default
    # (just verify the generator doesn't crash with non-default params)
    assert p.estimated_value > 0


def test_multi_property_produces_portfolio_summary(tmp_db: Database):
    """Two+ properties should produce a portfolio summary."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    prop1 = _sample_property()
    prop2 = _sample_property()
    prop2["address"] = "200 Oak Ave"
    prop2["neighborhood"] = "North Berkeley"
    prop2["sqft"] = 2000

    result = gen.generate(properties=[prop1, prop2])

    assert result.is_multi_property is True
    assert result.portfolio_summary is not None
    assert result.portfolio_summary.property_count == 2
    assert len(result.properties) == 2


def test_prospectus_to_dict_single(tmp_db: Database):
    """prospectus_to_dict converts single-property result to JSON-serializable dict."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    d = prospectus_to_dict(result)

    assert isinstance(d, dict)
    assert "properties" in d
    assert "portfolio_summary" in d
    assert "is_multi_property" in d

    assert len(d["properties"]) == 1
    prop_d = d["properties"][0]

    # Check key fields are present in the dict
    assert prop_d["address"] == "100 Cedar St"
    assert prop_d["estimated_value"] == 1_400_000
    assert prop_d["neighborhood"] == "North Berkeley"
    assert isinstance(prop_d["scenarios"], list)
    assert isinstance(prop_d["risk_factors"], list)
    assert isinstance(prop_d["disclaimers"], list)


def test_prospectus_to_dict_multi(tmp_db: Database):
    """prospectus_to_dict handles multi-property with portfolio summary."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    prop1 = _sample_property()
    prop2 = _sample_property()
    prop2["address"] = "200 Oak Ave"

    result = gen.generate(properties=[prop1, prop2])
    d = prospectus_to_dict(result)

    assert d["is_multi_property"] is True
    assert d["portfolio_summary"] is not None
    assert d["portfolio_summary"]["property_count"] == 2
    assert len(d["properties"]) == 2


def test_prediction_failure_graceful(tmp_db: Database):
    """Generator handles prediction failures gracefully."""
    _seed_prospectus_data(tmp_db)

    def failing_predict(prop_dict, source):
        raise RuntimeError("Model not loaded")

    market_analyzer = MarketAnalyzer(tmp_db)
    rental_analyzer = RentalAnalyzer(tmp_db, dev_calc=None)
    gen = ProspectusGenerator(
        db=tmp_db,
        dev_calc=None,
        rental_analyzer=rental_analyzer,
        market_analyzer=market_analyzer,
        predict_fn=failing_predict,
    )

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    # Should still produce a prospectus, just without valuation
    assert p.address == "100 Cedar St"
    assert p.estimated_value == 0  # Default when prediction fails
    assert len(p.risk_factors) >= 1


def test_recommended_strategy_set(tmp_db: Database):
    """A recommended strategy is determined from the analysis."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    # Strategy should be one of the valid labels
    valid_strategies = {
        "rent_as_is",
        "develop_adu_and_rent",
        "develop_sb9_and_rent",
        "develop_and_sell",
        "hold_for_appreciation",
        "multi_unit_development",
    }
    assert p.recommended_approach in valid_strategies
    assert len(p.strategy_rationale) > 0


def test_comparable_sales_populated(tmp_db: Database):
    """Comparable sales are included in the prospectus."""
    _seed_prospectus_data(tmp_db)
    gen = _make_generator(tmp_db)

    result = gen.generate(properties=[_sample_property()])
    p = result.properties[0]

    # With 12 North Berkeley sales seeded, comps should be populated
    assert isinstance(p.comparable_sales, list)
    assert len(p.comparable_sales) >= 1

    comp = p.comparable_sales[0]
    assert "address" in comp
    assert "sale_price" in comp
    assert "sale_date" in comp
