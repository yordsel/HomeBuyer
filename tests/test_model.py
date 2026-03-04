"""Tests for model training, prediction, and evaluation."""

from datetime import date

import numpy as np
import pytest

from homebuyer.prediction.evaluate import evaluate_model, evaluate_by_neighborhood
from homebuyer.prediction.features import FeatureBuilder
from homebuyer.prediction.model import ModelArtifact, PredictionResult
from homebuyer.storage.database import Database
from homebuyer.storage.models import MarketMetric, MortgageRate, PropertySale


def _seed_model_data(db: Database, n_train: int = 50, n_test: int = 20) -> None:
    """Insert enough data for model training with temporal split.

    Creates n_train sales in 2024 (training) and n_test in 2025 (test).
    Prices scale linearly with sqft to give the model a learnable pattern.
    """
    for i in range(n_train + n_test):
        is_train = i < n_train
        year = 2024 if is_train else 2025
        month = (i % 12) + 1
        if month > 12:
            month = 12

        # Create a learnable price = base + sqft_factor * sqft
        sqft = 1200 + (i * 40)
        base_price = 500_000
        sqft_factor = 600  # ~$600/sqft
        noise = ((i * 7) % 100_000) - 50_000  # deterministic noise
        price = base_price + sqft_factor * sqft + noise

        neighborhoods = ["North Berkeley", "Claremont", "Elmwood", "Rockridge", "Westbrae"]
        neighborhood = neighborhoods[i % len(neighborhoods)]

        sale = PropertySale(
            mls_number=f"MLM{i:05d}",
            address=f"{200 + i} Model Test Ave",
            city="Berkeley",
            state="CA",
            zip_code="94702",
            sale_date=date(year, month, 15),
            sale_price=max(int(price), 100_000),
            property_type="Single Family Residential",
            beds=3.0 + (i % 3),
            baths=2.0 + (i % 2),
            sqft=sqft,
            lot_size_sqft=5000 + (i * 100),
            year_built=1920 + (i % 50),
            price_per_sqft=round(price / sqft, 2),
            latitude=37.87 + (i * 0.001),
            longitude=-122.27 + (i * 0.001),
            neighborhood=neighborhood,
        )
        db.upsert_sale(sale)

    # Market metrics
    for year in [2024, 2025]:
        for month in range(1, 13):
            if year == 2025 and month > 6:
                break
            db.upsert_market_metric(
                MarketMetric(
                    period_begin=date(year, month, 1),
                    period_end=date(year, month, 28),
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
            rate_30yr=6.50,
            rate_15yr=5.80,
        )
    )
    db.upsert_mortgage_rate(
        MortgageRate(
            observation_date=date(2025, 1, 1),
            rate_30yr=6.30,
            rate_15yr=5.60,
        )
    )


# ---------------------------------------------------------------------------
# Evaluation metric tests
# ---------------------------------------------------------------------------


def test_evaluate_model_basic():
    """evaluate_model computes correct metrics for simple cases."""
    y_true = np.array([100, 200, 300, 400, 500])
    y_pred = np.array([110, 190, 310, 380, 520])

    metrics = evaluate_model(y_true, y_pred)

    assert metrics["n_samples"] == 5
    assert metrics["mae"] > 0
    assert metrics["mape"] > 0
    assert metrics["r2"] > 0.9  # Very close predictions
    assert 0 <= metrics["within_10pct"] <= 100
    assert 0 <= metrics["within_20pct"] <= 100


def test_evaluate_model_perfect():
    """Perfect predictions give MAE=0 and R^2=1."""
    y_true = np.array([100, 200, 300])
    y_pred = np.array([100, 200, 300])

    metrics = evaluate_model(y_true, y_pred)

    assert metrics["mae"] == 0.0
    assert metrics["r2"] == 1.0
    assert metrics["mape"] == 0.0


def test_evaluate_model_with_intervals():
    """Prediction interval metrics are computed when bounds are provided."""
    y_true = np.array([100, 200, 300, 400, 500])
    y_pred = np.array([105, 195, 305, 395, 505])
    y_lower = np.array([80, 170, 280, 370, 480])
    y_upper = np.array([120, 220, 320, 420, 520])

    metrics = evaluate_model(y_true, y_pred, y_lower, y_upper)

    assert "interval_coverage" in metrics
    assert metrics["interval_coverage"] == 100.0  # All within bounds
    assert "avg_interval_width" in metrics


def test_evaluate_by_neighborhood():
    """Per-neighborhood evaluation returns correct structure."""
    y_true = np.array([100, 200, 300, 400, 500, 600])
    y_pred = np.array([110, 190, 310, 380, 520, 580])
    neighborhoods = np.array(["A", "A", "A", "B", "B", "B"])

    results = evaluate_by_neighborhood(y_true, y_pred, neighborhoods, min_samples=2)

    assert len(results) == 2
    assert results[0]["name"] in ["A", "B"]
    assert "mape" in results[0]
    assert "mae" in results[0]


# ---------------------------------------------------------------------------
# Model training and prediction tests (integration)
# ---------------------------------------------------------------------------


def test_model_train_and_predict(tmp_db: Database, tmp_path):
    """Train a model and make a prediction (end-to-end integration)."""
    _seed_model_data(tmp_db, n_train=50, n_test=20)

    # Train
    from homebuyer.prediction.train import train_model

    artifact = train_model(
        tmp_db,
        grid_search=False,  # Skip grid search for speed
        split_date="2025-01-01",
        save_path=tmp_path / "test_model.joblib",
    )

    assert artifact.train_size > 0
    assert artifact.test_size > 0
    assert artifact.training_metrics["mae"] > 0
    assert artifact.training_metrics["r2"] is not None
    assert len(artifact.feature_importances) > 0
    assert len(artifact.feature_names) > 0

    # Predict
    result = artifact.predict_single(
        tmp_db,
        {
            "neighborhood": "North Berkeley",
            "zip_code": "94702",
            "beds": 3.0,
            "baths": 2.0,
            "sqft": 1700,
            "year_built": 1925,
            "property_type": "Single Family Residential",
            "latitude": 37.87,
            "longitude": -122.27,
        },
    )

    assert isinstance(result, PredictionResult)
    assert result.predicted_price > 0
    assert result.price_lower <= result.predicted_price
    assert result.price_upper >= result.predicted_price


def test_model_predict_with_list_price(tmp_db: Database, tmp_path):
    """Prediction with list_price computes premium percentage."""
    _seed_model_data(tmp_db, n_train=50, n_test=20)

    from homebuyer.prediction.train import train_model

    artifact = train_model(
        tmp_db, grid_search=False, split_date="2025-01-01",
        save_path=tmp_path / "test_model.joblib",
    )

    result = artifact.predict_single(
        tmp_db,
        {
            "neighborhood": "North Berkeley",
            "zip_code": "94702",
            "beds": 3.0,
            "baths": 2.0,
            "sqft": 1700,
            "list_price": 1_000_000,
        },
    )

    assert result.list_price == 1_000_000
    assert result.predicted_premium_pct is not None


def test_model_save_and_load(tmp_db: Database, tmp_path):
    """Model can be saved and loaded successfully."""
    _seed_model_data(tmp_db, n_train=50, n_test=20)

    from homebuyer.prediction.train import train_model

    artifact = train_model(
        tmp_db, grid_search=False, split_date="2025-01-01",
        save_path=tmp_path / "train_model.joblib",
    )

    # Save
    save_path = tmp_path / "test_model.joblib"
    artifact.save(save_path)
    assert save_path.exists()

    # Load
    loaded = ModelArtifact.load(save_path)
    assert loaded.train_size == artifact.train_size
    assert loaded.feature_names == artifact.feature_names
    assert len(loaded.label_encoders) == len(artifact.label_encoders)

    # Predict with loaded model
    result = loaded.predict_single(
        tmp_db,
        {
            "neighborhood": "North Berkeley",
            "zip_code": "94702",
            "beds": 3.0,
            "baths": 2.0,
            "sqft": 1700,
        },
    )
    assert result.predicted_price > 0


def test_model_load_not_found(tmp_path):
    """Loading from nonexistent path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="No model found"):
        ModelArtifact.load(tmp_path / "nonexistent.joblib")


def test_model_format_info(tmp_db: Database, tmp_path):
    """format_info returns a non-empty string."""
    _seed_model_data(tmp_db, n_train=50, n_test=20)

    from homebuyer.prediction.train import train_model

    artifact = train_model(
        tmp_db, grid_search=False, split_date="2025-01-01",
        save_path=tmp_path / "test_model.joblib",
    )

    info = artifact.format_info()
    assert "BERKELEY PRICE PREDICTION MODEL" in info
    assert "MAE" in info
    assert "MAPE" in info
