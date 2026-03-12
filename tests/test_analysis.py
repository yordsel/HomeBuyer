"""Tests for the market analysis module."""

from datetime import date

from homebuyer.analysis.market_analysis import MarketAnalyzer
from homebuyer.storage.database import Database
from homebuyer.storage.models import MarketMetric, MortgageRate, PropertySale


def _seed_test_data(db: Database) -> None:
    """Seed a test database with realistic-looking Berkeley data."""
    # Insert property sales across two neighborhoods
    sales = [
        PropertySale(
            mls_number=f"ML{i:05d}",
            address=f"{100+i} Test St",
            city="Berkeley",
            state="CA",
            zip_code="94702",
            sale_date=date(2025, 1 + (i % 6), 15),
            sale_price=1_200_000 + (i * 50_000),
            property_type="Single Family Residential",
            beds=3.0,
            baths=2.0,
            sqft=1600 + (i * 50),
            lot_size_sqft=5000,
            year_built=1920 + i,
            price_per_sqft=round((1_200_000 + i * 50_000) / (1600 + i * 50), 2),
            latitude=37.87,
            longitude=-122.27,
            neighborhood="North Berkeley",
        )
        for i in range(12)
    ]

    # Add some in a different neighborhood
    sales.extend([
        PropertySale(
            mls_number=f"ML{100+i:05d}",
            address=f"{200+i} Oak Ave",
            city="Berkeley",
            state="CA",
            zip_code="94705",
            sale_date=date(2025, 1 + (i % 6), 20),
            sale_price=2_000_000 + (i * 100_000),
            property_type="Single Family Residential",
            beds=4.0,
            baths=3.0,
            sqft=2200 + (i * 100),
            lot_size_sqft=8000,
            year_built=1935 + i,
            price_per_sqft=round((2_000_000 + i * 100_000) / (2200 + i * 100), 2),
            latitude=37.86,
            longitude=-122.25,
            neighborhood="Claremont",
        )
        for i in range(8)
    ])

    for sale in sales:
        db.upsert_sale(sale)

    # Insert market metrics
    for month in range(1, 7):
        db.upsert_market_metric(
            MarketMetric(
                period_begin=date(2025, month, 1),
                period_end=date(2025, month, 28),
                period_duration="30",
                region_name="Berkeley, CA",
                property_type="All Residential",
                median_sale_price=1_300_000 + month * 10_000,
                median_list_price=1_100_000 + month * 5_000,
                avg_sale_to_list=1.18 + month * 0.005,
                sold_above_list_pct=0.65 + month * 0.01,
                homes_sold=50 + month,
                median_dom=15,
            )
        )

    # Insert mortgage rates
    db.upsert_mortgage_rate(
        MortgageRate(
            observation_date=date(2025, 6, 1),
            rate_30yr=6.50,
            rate_15yr=5.80,
        )
    )


def test_neighborhood_stats(tmp_db: Database):
    """Neighborhood stats are computed correctly."""
    _seed_test_data(tmp_db)
    analyzer = MarketAnalyzer(tmp_db)

    stats = analyzer.get_neighborhood_stats("North Berkeley", lookback_years=2)
    assert stats.name == "North Berkeley"
    assert stats.sale_count == 12
    assert stats.avg_price is not None
    assert stats.avg_price > 1_000_000
    assert stats.min_price <= stats.max_price


def test_neighborhood_rankings(tmp_db: Database):
    """Neighborhood rankings return sorted results."""
    _seed_test_data(tmp_db)
    analyzer = MarketAnalyzer(tmp_db)

    rankings = analyzer.get_all_neighborhood_rankings(lookback_years=2, min_sales=5)
    assert len(rankings) >= 2

    # Claremont should be more expensive than North Berkeley
    names = [r.name for r in rankings]
    assert "Claremont" in names
    assert "North Berkeley" in names

    claremont_idx = names.index("Claremont")
    nb_idx = names.index("North Berkeley")
    assert claremont_idx < nb_idx  # Claremont ranked higher (more expensive)


def test_market_trend(tmp_db: Database):
    """Market trend returns monthly snapshots."""
    _seed_test_data(tmp_db)
    analyzer = MarketAnalyzer(tmp_db)

    trend = analyzer.get_market_trend(months=12)
    assert len(trend) >= 1
    assert trend[0].median_sale_price is not None
    assert trend[0].sale_to_list_ratio is not None


def test_find_comparables(tmp_db: Database):
    """Finding comparables returns scored results."""
    _seed_test_data(tmp_db)
    analyzer = MarketAnalyzer(tmp_db)

    comps = analyzer.find_comparables(
        neighborhood="North Berkeley",
        beds=3,
        baths=2,
        sqft=1700,
    )
    assert len(comps) > 0
    assert comps[0].neighborhood == "North Berkeley"
    # Should be sorted by similarity score (ascending)
    for i in range(len(comps) - 1):
        assert comps[i].similarity_score <= comps[i + 1].similarity_score


def test_price_estimate(tmp_db: Database):
    """Price estimation produces reasonable results."""
    _seed_test_data(tmp_db)
    analyzer = MarketAnalyzer(tmp_db)

    estimate = analyzer.estimate_price(
        neighborhood="North Berkeley",
        beds=3,
        baths=2,
        sqft=1700,
        year_built=1925,
    )

    assert estimate.estimated_price > 0
    assert estimate.price_range_low < estimate.estimated_price
    assert estimate.price_range_high > estimate.estimated_price
    assert estimate.comparable_count > 0
    assert estimate.confidence in ("high", "medium", "low")
    assert len(estimate.methodology_notes) > 0


def test_affordability(tmp_db: Database):
    """Affordability analysis produces valid results."""
    _seed_test_data(tmp_db)
    analyzer = MarketAnalyzer(tmp_db)

    result = analyzer.assess_affordability(
        monthly_budget=8000,
        down_payment_pct=20,
    )

    assert result["max_affordable_price"] > 0
    assert result["loan_amount"] > 0
    assert result["mortgage_rate_30yr"] > 0
    assert isinstance(result["is_jumbo_loan"], bool)
    assert isinstance(result["affordable_neighborhoods"], list)


def test_summary_report(tmp_db: Database):
    """Summary report contains all expected sections."""
    _seed_test_data(tmp_db)
    analyzer = MarketAnalyzer(tmp_db)

    report = analyzer.generate_summary_report()

    assert "data_coverage" in report
    assert "current_market" in report
    assert "price_distribution_2yr" in report
    assert "top_neighborhoods_by_price" in report

    assert report["data_coverage"]["total_sales"] == 20  # 12 + 8
    # Note: neighborhoods_covered uses min_sales=10 by default,
    # so only North Berkeley (12 sales) qualifies; Claremont has 8
    assert report["data_coverage"]["neighborhoods_covered"] >= 1


def test_empty_neighborhood(tmp_db: Database):
    """Querying a nonexistent neighborhood returns empty stats."""
    _seed_test_data(tmp_db)
    analyzer = MarketAnalyzer(tmp_db)

    stats = analyzer.get_neighborhood_stats("Nonexistent Area")
    assert stats.sale_count == 0
    assert stats.median_price is None
