"""Training orchestrator for the price prediction model.

Handles temporal train/test splitting, hyperparameter tuning via
GridSearchCV, training the main + quantile models, evaluation,
and saving the model artifact.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit

from homebuyer.prediction.evaluate import (
    evaluate_by_neighborhood,
    evaluate_model,
    format_evaluation_report,
)
from homebuyer.prediction.features import FeatureBuilder
from homebuyer.prediction.model import ModelArtifact
from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default hyperparameter grid for GridSearchCV
# ---------------------------------------------------------------------------

DEFAULT_PARAM_GRID = {
    "max_depth": [4, 6, 8],
    "learning_rate": [0.05, 0.1, 0.2],
    "max_iter": [200, 500],
    "min_samples_leaf": [10, 20, 30],
    "l2_regularization": [0.0, 0.1, 1.0],
}

# Default hyperparameters when skipping grid search
DEFAULT_PARAMS = {
    "max_depth": 6,
    "learning_rate": 0.1,
    "max_iter": 500,
    "min_samples_leaf": 20,
    "l2_regularization": 0.1,
}

# Temporal split date: train on data before this, test on data from this date
SPLIT_DATE = "2025-01-01"


def train_model(
    db: Database,
    grid_search: bool = True,
    split_date: str = SPLIT_DATE,
    verbose: bool = False,
    save_path: Optional[Path] = None,
) -> ModelArtifact:
    """Train the price prediction model end-to-end.

    Steps:
    1. Build feature matrix from database
    2. Split temporally (pre-2025 train, 2025+ test)
    3. Optionally tune hyperparameters via GridSearchCV
    4. Train main model + quantile models for prediction intervals
    5. Evaluate on test set
    6. Package and save ModelArtifact

    Args:
        db: Connected database instance.
        grid_search: Whether to run hyperparameter tuning.
        split_date: ISO date string for temporal split.
        verbose: Print detailed progress.

    Returns:
        Trained ModelArtifact with evaluation metrics.
    """
    logger.info("Starting model training pipeline...")

    # Step 1: Build features
    builder = FeatureBuilder(db)
    X, y = builder.build_training_data()

    # We need sale_date for splitting but it's not a feature.
    # Re-query to get sale_dates and neighborhoods aligned with X.
    rows = db.conn.execute(
        """
        SELECT sale_date, neighborhood
        FROM property_sales
        WHERE sale_price IS NOT NULL
          AND sale_price >= 50000
          AND neighborhood IS NOT NULL
        ORDER BY sale_date
        """
    ).fetchall()
    sale_dates = pd.Series([r["sale_date"] for r in rows])
    neighborhoods = np.array([r["neighborhood"] for r in rows])

    # Step 2: Temporal split
    train_mask = sale_dates < split_date
    test_mask = sale_dates >= split_date

    X_train, X_test = X[train_mask], X[test_mask]
    y_train, y_test = y[train_mask], y[test_mask]
    neighborhoods_test = neighborhoods[test_mask]

    logger.info(
        "Temporal split at %s: %d train, %d test.",
        split_date, len(X_train), len(X_test),
    )

    if len(X_train) < 30:
        raise ValueError(
            f"Only {len(X_train)} training samples before {split_date}. "
            "Need at least 30 for a meaningful model."
        )
    if len(X_test) < 10:
        raise ValueError(
            f"Only {len(X_test)} test samples after {split_date}. "
            "Need at least 10 for evaluation."
        )

    # Step 3: Hyperparameter tuning
    if grid_search:
        best_params = _run_grid_search(X_train, y_train, verbose=verbose)
    else:
        best_params = DEFAULT_PARAMS.copy()
        logger.info("Skipping grid search. Using default hyperparameters.")

    logger.info("Best hyperparameters: %s", best_params)

    # Step 4: Train main + quantile models
    logger.info("Training main model (squared_error)...")
    model_main = HistGradientBoostingRegressor(
        loss="squared_error",
        random_state=42,
        **best_params,
    )
    model_main.fit(X_train, y_train)

    logger.info("Training lower quantile model (5th percentile)...")
    model_lower = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.05,
        random_state=42,
        **best_params,
    )
    model_lower.fit(X_train, y_train)

    logger.info("Training upper quantile model (95th percentile)...")
    model_upper = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.95,
        random_state=42,
        **best_params,
    )
    model_upper.fit(X_train, y_train)

    # Step 5: Evaluate on test set
    y_pred = model_main.predict(X_test)
    y_pred_lower = model_lower.predict(X_test)
    y_pred_upper = model_upper.predict(X_test)

    # Ensure bounds are sensible
    y_pred_lower = np.minimum(y_pred_lower, y_pred)
    y_pred_upper = np.maximum(y_pred_upper, y_pred)

    metrics = evaluate_model(
        y_test.values, y_pred, y_pred_lower, y_pred_upper
    )

    neighborhood_results = evaluate_by_neighborhood(
        y_test.values, y_pred, neighborhoods_test, min_samples=5
    )

    # Feature importances via permutation importance
    # (HistGradientBoostingRegressor removed feature_importances_ in sklearn 1.8)
    perm_result = permutation_importance(
        model_main, X_test, y_test,
        n_repeats=10, random_state=42, n_jobs=-1,
    )
    importances = perm_result.importances_mean
    # Normalize to sum to 1 for easier interpretation
    total = importances.sum()
    if total > 0:
        importances = importances / total
    feature_imp = dict(zip(builder.feature_names, importances))

    # Print evaluation report
    report = format_evaluation_report(
        metrics, neighborhood_results, feature_imp
    )
    print(report)

    # Step 6: Package artifact
    data_cutoff = sale_dates[train_mask].max()

    artifact = ModelArtifact(
        model=model_main,
        model_lower=model_lower,
        model_upper=model_upper,
        feature_names=builder.feature_names,
        label_encoders=builder.get_encoders(),
        training_metrics=metrics,
        trained_at=datetime.now(),
        data_cutoff_date=data_cutoff,
        feature_importances=feature_imp,
        train_size=len(X_train),
        test_size=len(X_test),
        neighborhood_metrics=neighborhood_results,
        hyperparameters=best_params,
    )

    # Save to disk
    path = artifact.save(save_path)
    logger.info("Model training complete. Artifact saved to %s.", path)

    return artifact


def _run_grid_search(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    verbose: bool = False,
) -> dict:
    """Run GridSearchCV with TimeSeriesSplit to find best hyperparameters.

    Args:
        X_train: Training feature matrix.
        y_train: Training target values.
        verbose: Print detailed CV progress.

    Returns:
        Dict of best hyperparameters.
    """
    logger.info(
        "Running grid search with %d parameter combinations...",
        (
            len(DEFAULT_PARAM_GRID["max_depth"])
            * len(DEFAULT_PARAM_GRID["learning_rate"])
            * len(DEFAULT_PARAM_GRID["max_iter"])
            * len(DEFAULT_PARAM_GRID["min_samples_leaf"])
            * len(DEFAULT_PARAM_GRID["l2_regularization"])
        ),
    )

    base_model = HistGradientBoostingRegressor(
        loss="squared_error",
        random_state=42,
    )

    # TimeSeriesSplit preserves temporal order within the training set
    tscv = TimeSeriesSplit(n_splits=3)

    grid = GridSearchCV(
        base_model,
        DEFAULT_PARAM_GRID,
        cv=tscv,
        scoring="neg_mean_absolute_error",
        n_jobs=-1,  # Use all cores
        verbose=2 if verbose else 0,
        refit=False,  # We'll refit with the full pipeline
    )

    grid.fit(X_train, y_train)

    best_params = grid.best_params_
    best_score = -grid.best_score_  # Negate because sklearn uses neg_MAE

    logger.info(
        "Grid search complete. Best MAE: $%s. Best params: %s",
        f"{best_score:,.0f}",
        best_params,
    )

    return best_params
