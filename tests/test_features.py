"""Tests for the feature engineering pipeline."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from homebuyer.prediction.features import (
    ALL_FEATURE_NAMES,
    FeatureBuilder,
    flag_training_outliers,
)
from homebuyer.storage.database import Database
from homebuyer.storage.models import MarketMetric, MortgageRate, PropertySale


def _seed_training_data(db: Database) -> None:
    """Insert enough data for feature building and model training."""
    # Insert property sales spanning pre-2025 and post-2025 for temporal split
    for i in range(30):
        year = 2024 if i < 20 else 2025
        month = (i % 12) + 1
        if year == 2025 and month > 6:
            month = (i % 6) + 1

        sale = PropertySale(
            mls_number=f"MLF{i:05d}",
            address=f"{100 + i} Feature Test St",
            city="Berkeley",
            state="CA",
            zip_code="94702" if i < 15 else "94705",
            sale_date=date(year, month, 15),
            sale_price=1_000_000 + (i * 50_000),
            property_type="Single Family Residential" if i < 25 else "Condo/Co-op",
            beds=3.0 if i < 20 else 2.0,
            baths=2.0,
            sqft=1500 + (i * 30),
            lot_size_sqft=5000 if i < 25 else None,
            year_built=1920 + i,
            price_per_sqft=round((1_000_000 + i * 50_000) / (1500 + i * 30), 2),
            latitude=37.87 + (i * 0.001),
            longitude=-122.27 + (i * 0.001),
            neighborhood="North Berkeley" if i < 15 else "Claremont",
        )
        db.upsert_sale(sale)

    # Insert market metrics
    for month in range(1, 13):
        db.upsert_market_metric(
            MarketMetric(
                period_begin=date(2024, month, 1),
                period_end=date(2024, month, 28),
                period_duration="30",
                region_name="Berkeley, CA",
                property_type="All Residential",
                median_sale_price=1_300_000 + month * 10_000,
                median_list_price=1_100_000 + month * 5_000,
                avg_sale_to_list=1.18,
                sold_above_list_pct=0.65,
                homes_sold=50 + month,
                median_dom=15,
                inventory=100,
                months_of_supply=1.5,
            )
        )

    for month in range(1, 7):
        db.upsert_market_metric(
            MarketMetric(
                period_begin=date(2025, month, 1),
                period_end=date(2025, month, 28),
                period_duration="30",
                region_name="Berkeley, CA",
                property_type="All Residential",
                median_sale_price=1_400_000 + month * 10_000,
                median_list_price=1_200_000 + month * 5_000,
                avg_sale_to_list=1.20,
                sold_above_list_pct=0.70,
                homes_sold=55 + month,
                median_dom=12,
                inventory=90,
                months_of_supply=1.3,
            )
        )

    # Insert mortgage rates
    for i in range(52):
        month = (i // 4) + 1
        day = (i % 4) * 7 + 1
        if month > 12:
            month = 12
        if day > 28:
            day = 28
        db.upsert_mortgage_rate(
            MortgageRate(
                observation_date=date(2024, month, day),
                rate_30yr=6.5 + (i % 10) * 0.05,
                rate_15yr=5.8 + (i % 10) * 0.05,
            )
        )


def test_build_training_data(tmp_db: Database):
    """build_training_data returns correct shape and column names."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)

    X, y = builder.build_training_data()

    assert len(X) == 30
    assert len(y) == 30
    assert list(X.columns) == ALL_FEATURE_NAMES
    assert y.dtype == float
    assert y.min() > 0


def test_feature_names_complete(tmp_db: Database):
    """All expected feature names are present."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)

    X, y = builder.build_training_data()

    assert "beds" in X.columns
    assert "baths" in X.columns
    assert "sqft" in X.columns
    assert "effective_sqft" in X.columns
    assert "building_to_listing_sqft_ratio" in X.columns
    assert "sale_month" in X.columns
    assert "neighborhood_encoded" in X.columns
    assert "market_median_price" in X.columns
    assert "rate_30yr" in X.columns


def test_derived_features_computed(tmp_db: Database):
    """Derived features like effective_sqft and bed_bath_ratio are correctly computed."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)

    X, y = builder.build_training_data()

    # effective_sqft should be populated (same as sqft when no building_sqft)
    effective = X["effective_sqft"].dropna()
    assert len(effective) > 0
    assert effective.min() > 0

    # building_to_listing_sqft_ratio should be 1.0 when no building_sqft
    ratios_bldg = X["building_to_listing_sqft_ratio"].dropna()
    # May be NaN for records without building_sqft; any present should be > 0
    if len(ratios_bldg) > 0:
        assert ratios_bldg.min() > 0

    # bed_bath_ratio should be positive
    ratios = X["bed_bath_ratio"].dropna()
    assert ratios.min() > 0


def test_label_encoding(tmp_db: Database):
    """Label encoding assigns distinct integers to neighborhoods."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)

    X, y = builder.build_training_data()

    encoded = X["neighborhood_encoded"].dropna().unique()
    assert len(encoded) >= 2  # At least North Berkeley and Claremont

    # Verify encoders are stored
    encoders = builder.get_encoders()
    assert "neighborhood" in encoders
    assert "zip_code" in encoders
    assert len(encoders["neighborhood"].classes_) >= 2


def test_market_features_joined(tmp_db: Database):
    """Market context features are joined for training rows."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)

    X, y = builder.build_training_data()

    # Most rows should have market context (we inserted 18 months of data)
    market_non_null = X["market_median_price"].notna().sum()
    assert market_non_null > 0


def test_rate_features_joined(tmp_db: Database):
    """Mortgage rate features are joined for training rows."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)

    X, y = builder.build_training_data()

    # Most rows should have rate data (we inserted 52 weeks of 2024)
    rate_non_null = X["rate_30yr"].notna().sum()
    assert rate_non_null > 0


def test_build_single_prediction(tmp_db: Database):
    """build_single_prediction produces a single-row DataFrame."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)

    # Must fit first
    X, y = builder.build_training_data()

    # Now build a single prediction
    prop = {
        "neighborhood": "North Berkeley",
        "zip_code": "94702",
        "beds": 3.0,
        "baths": 2.0,
        "sqft": 1700,
        "year_built": 1925,
        "lot_size_sqft": 5000,
        "property_type": "Single Family Residential",
        "latitude": 37.87,
        "longitude": -122.27,
    }

    X_pred = builder.build_single_prediction(prop)
    assert len(X_pred) == 1
    assert list(X_pred.columns) == ALL_FEATURE_NAMES


def test_single_prediction_requires_fitting(tmp_db: Database):
    """build_single_prediction raises if not fitted."""
    builder = FeatureBuilder(tmp_db)

    with pytest.raises(ValueError, match="not been fitted"):
        builder.build_single_prediction({"neighborhood": "Test", "zip_code": "94702"})


def test_unseen_neighborhood_encoded_as_nan(tmp_db: Database):
    """Unseen neighborhoods get NaN encoding (HistGBR handles it)."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)
    X, y = builder.build_training_data()

    # Predict with unseen neighborhood
    prop = {
        "neighborhood": "Fictional Heights",
        "zip_code": "94702",
        "beds": 3.0,
        "baths": 2.0,
        "sqft": 1700,
    }

    X_pred = builder.build_single_prediction(prop)
    assert np.isnan(X_pred["neighborhood_encoded"].iloc[0])


# ---------------------------------------------------------------------------
# New tests for data quality filters and new features
# ---------------------------------------------------------------------------


def _seed_training_data_with_apartments(db: Database) -> None:
    """Insert training data including poisoned apartment records.

    Creates 25 normal SFR records plus 5 apartment records with
    per-unit features (beds=1, sqft=600) and whole-building prices ($5M+).
    """
    # Normal SFR records
    for i in range(25):
        month = (i % 12) + 1
        sale = PropertySale(
            mls_number=f"MLN{i:05d}",
            address=f"{300 + i} Normal St",
            city="Berkeley",
            state="CA",
            zip_code="94702",
            sale_date=date(2024, month, 15),
            sale_price=1_000_000 + (i * 50_000),
            property_type="Single Family Residential",
            beds=3.0,
            baths=2.0,
            sqft=1500 + (i * 30),
            lot_size_sqft=5000,
            year_built=1920 + i,
            price_per_sqft=round((1_000_000 + i * 50_000) / (1500 + i * 30), 2),
            latitude=37.87 + (i * 0.001),
            longitude=-122.27 + (i * 0.001),
            neighborhood="North Berkeley",
        )
        db.upsert_sale(sale)

    # Poisoned apartment records: per-unit features + whole-building price
    for i in range(5):
        sale = PropertySale(
            mls_number=f"MLA{i:05d}",
            address=f"{400 + i} Apartment Ave",
            city="Berkeley",
            state="CA",
            zip_code="94702",
            sale_date=date(2024, (i % 12) + 1, 15),
            sale_price=5_000_000 + (i * 500_000),
            property_type="Apartment",  # maps to "Multi-Family (5+ Unit)"
            beds=1.0,   # per-unit
            baths=1.0,
            sqft=600,    # per-unit
            lot_size_sqft=8000,
            year_built=1960,
            price_per_sqft=round((5_000_000 + i * 500_000) / 600, 2),
            latitude=37.88,
            longitude=-122.26,
            neighborhood="Downtown Berkeley",
        )
        db.upsert_sale(sale)

    # Insert market metrics (minimal for test)
    for month in range(1, 13):
        db.upsert_market_metric(
            MarketMetric(
                period_begin=date(2024, month, 1),
                period_end=date(2024, month, 28),
                period_duration="30",
                region_name="Berkeley, CA",
                property_type="All Residential",
                median_sale_price=1_300_000,
                avg_sale_to_list=1.18,
                sold_above_list_pct=0.65,
                homes_sold=50,
                median_dom=15,
            )
        )

    # Mortgage rates
    db.upsert_mortgage_rate(
        MortgageRate(
            observation_date=date(2024, 1, 1),
            rate_30yr=6.5,
            rate_15yr=5.8,
        )
    )


def test_apartment_per_unit_records_filtered(tmp_db: Database):
    """Apartment records with per-unit features are filtered from training data.

    Seeds 25 normal SFR + 5 poisoned apartment records. The 5 apartment
    records should be removed because they have beds <= 2 and sqft <= 1000
    with the 'Apartment' property type (normalized to 'Multi-Family (5+ Unit)').
    """
    _seed_training_data_with_apartments(tmp_db)
    builder = FeatureBuilder(tmp_db)

    X, y = builder.build_training_data()

    # Should have the 25 normal SFR records, not 30
    assert len(X) == 25
    # Max sale price should be < $2.5M (SFR range), not $7.5M (apartment range)
    assert y.max() < 3_000_000


def test_price_per_sqft_outlier_detection():
    """flag_training_outliers flags extreme price/sqft records.

    Uses a large enough normal group so that the extreme record stands
    out at >3 std devs. With 20 tight records + 1 extreme, the z-score
    is well above 3.
    """
    # 20 normal SFR records with ~$667-$778/sqft (tight distribution)
    n_normal = 20
    normal_prices = [1_000_000 + i * 10_000 for i in range(n_normal)]
    normal_sqft = [1400 + i * 20 for i in range(n_normal)]

    # 1 extreme outlier: $15M / 600 sqft = $25K/sqft
    all_prices = normal_prices + [15_000_000]
    all_sqft = normal_sqft + [600]
    all_types = ["SFR"] * (n_normal + 1)

    df = pd.DataFrame({
        "sale_price": all_prices,
        "sqft": all_sqft,
        "property_type": all_types,
    })

    outliers = flag_training_outliers(df)

    # The extreme record should be flagged
    assert bool(outliers.iloc[-1]) is True
    # Normal records should NOT be flagged
    assert bool(outliers.iloc[0]) is False
    assert bool(outliers.iloc[5]) is False


def test_effective_sqft_uses_sqft_for_sfr(tmp_db: Database):
    """For SFR properties, effective_sqft should equal sqft."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)

    X, y = builder.build_training_data()

    # All test records are SFR with no building_sqft from assessor,
    # so effective_sqft should be the same as sqft
    sqft_vals = X["sqft"].dropna()
    effective_vals = X["effective_sqft"].dropna()

    if len(sqft_vals) > 0 and len(effective_vals) > 0:
        # For records where both are present, they should match
        both_present = X[X["sqft"].notna() & X["effective_sqft"].notna()]
        if len(both_present) > 0:
            np.testing.assert_array_almost_equal(
                both_present["effective_sqft"].values,
                both_present["sqft"].values,
            )
