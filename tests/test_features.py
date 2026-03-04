"""Tests for the feature engineering pipeline."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from homebuyer.prediction.features import ALL_FEATURE_NAMES, FeatureBuilder
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
    assert "property_age" in X.columns
    assert "is_sfr" in X.columns
    assert "sale_month" in X.columns
    assert "neighborhood_encoded" in X.columns
    assert "market_median_price" in X.columns
    assert "rate_30yr" in X.columns


def test_derived_features_computed(tmp_db: Database):
    """Derived features like property_age and is_sfr are correctly computed."""
    _seed_training_data(tmp_db)
    builder = FeatureBuilder(tmp_db)

    X, y = builder.build_training_data()

    # Property age should be positive (year_built is 1920+)
    valid_ages = X["property_age"].dropna()
    assert len(valid_ages) > 0
    assert valid_ages.min() > 0

    # is_sfr should be 0 or 1
    sfr_values = X["is_sfr"].dropna()
    assert set(sfr_values.unique()).issubset({0.0, 1.0})

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
