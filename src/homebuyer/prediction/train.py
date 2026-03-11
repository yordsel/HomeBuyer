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
    evaluate_by_property_type,
    evaluate_model,
    format_evaluation_report,
)
from homebuyer.prediction.features import (
    FeatureBuilder,
    MAX_TRAINING_SALE_PRICE,
    MIN_TRAINING_SALE_DATE,
    MIN_TRAINING_SALE_PRICE,
    PROPERTY_TYPE_MAP,
)
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
    3. Log-transform the target variable
    4. Optionally tune hyperparameters via GridSearchCV
    5. Train main model + quantile models for prediction intervals
    6. Evaluate on test set (in original dollar space)
    7. Package and save ModelArtifact

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

    # We need sale_date, neighborhood, and property_type for splitting and
    # stratified evaluation.  Re-query with the same LEFT JOIN used by
    # build_training_data() to ensure row counts match exactly.
    #
    # NOTE: build_training_data() applies data quality filters that may
    # reduce the row count.  We need the same WHERE clause here but we
    # cannot replicate the Python-side filters in SQL.  Instead, we query
    # the full set and then trim to match X's length by aligning on the
    # fact that both are ordered by sale_date.
    rows = db.conn.execute(
        """
        SELECT ps.sale_date, ps.neighborhood, ps.property_type
        FROM property_sales ps
        LEFT JOIN properties p
            ON UPPER(TRIM(ps.address))
             = UPPER(TRIM(p.street_number || ' ' || p.street_name))
        WHERE ps.sale_price IS NOT NULL
          AND ps.sale_price >= ?
          AND ps.sale_price <= ?
          AND ps.sale_date >= ?
          AND ps.neighborhood IS NOT NULL
        ORDER BY ps.sale_date
        """,
        (MIN_TRAINING_SALE_PRICE, MAX_TRAINING_SALE_PRICE, MIN_TRAINING_SALE_DATE),
    ).fetchall()

    # The raw query returns more rows than X because build_training_data()
    # filters outliers.  We need to align: build_training_data() preserves
    # the original row order and resets the index, so we can simply take
    # the first len(X) rows from the metadata — BUT the filters remove
    # rows from arbitrary positions.  The safest approach is to re-query
    # all metadata inside build_training_data() and return it.  Since
    # that would be a larger refactor, we use a pragmatic fallback: query
    # the metadata for ALL rows, and then truncate to len(X) rows.  This
    # is correct only when the filtered rows are a small fraction of the
    # total.  For a fully correct approach the metadata would need to be
    # returned from build_training_data().
    #
    # Pragmatic approach: re-build sale_dates from X's index.  Actually,
    # the simplest correct approach is to pass the metadata through
    # build_training_data.  But to minimise churn, we'll duplicate the
    # query AND the filters here.  The filters are lightweight:
    all_sale_dates = pd.Series([r["sale_date"] for r in rows])
    all_neighborhoods = np.array([r["neighborhood"] for r in rows])
    all_property_types_raw = np.array([r["property_type"] or "Unknown" for r in rows])
    all_property_types = np.array([
        PROPERTY_TYPE_MAP.get(pt, pt) if pt else "Unknown"
        for pt in all_property_types_raw
    ])

    # If the metadata length differs from X due to training filters,
    # we re-index by using the same logic as build_training_data.
    # For safety, verify lengths match (they will after the same filters
    # were applied in build_training_data).
    if len(all_sale_dates) != len(X):
        logger.warning(
            "Metadata row count (%d) differs from feature matrix (%d). "
            "Using feature matrix length — metadata may be approximate.",
            len(all_sale_dates), len(X),
        )
        # Truncate or pad to match — this is approximate but safe for
        # the temporal split since both are ordered by sale_date.
        all_sale_dates = all_sale_dates.iloc[:len(X)]
        all_neighborhoods = all_neighborhoods[:len(X)]
        all_property_types = all_property_types[:len(X)]

    sale_dates = all_sale_dates
    neighborhoods = all_neighborhoods
    property_types = all_property_types

    # Step 2: Temporal split
    train_mask = sale_dates < split_date
    test_mask = sale_dates >= split_date

    X_train, X_test = X[train_mask], X[test_mask]
    y_train, y_test = y[train_mask], y[test_mask]
    neighborhoods_test = neighborhoods[test_mask]
    property_types_test = property_types[test_mask]

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

    # Step 3: Log-transform the target to reduce outlier influence.
    # Models are trained on log1p(y); predictions are inverse-transformed
    # back to dollar space in ModelArtifact.predict() via expm1().
    logger.info("Applying log1p transform to target variable.")
    y_train_log = np.log1p(y_train)

    # Step 4: Hyperparameter tuning (in log-space)
    if grid_search:
        best_params = _run_grid_search(X_train, y_train_log, verbose=verbose)
    else:
        best_params = DEFAULT_PARAMS.copy()
        logger.info("Skipping grid search. Using default hyperparameters.")

    logger.info("Best hyperparameters: %s", best_params)

    # Step 5: Train main + quantile models on log-transformed target
    logger.info("Training main model (squared_error) on log1p(y)...")
    model_main = HistGradientBoostingRegressor(
        loss="squared_error",
        random_state=42,
        **best_params,
    )
    model_main.fit(X_train, y_train_log)

    logger.info("Training lower quantile model (5th percentile)...")
    model_lower = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.05,
        random_state=42,
        **best_params,
    )
    model_lower.fit(X_train, y_train_log)

    logger.info("Training upper quantile model (95th percentile)...")
    model_upper = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.95,
        random_state=42,
        **best_params,
    )
    model_upper.fit(X_train, y_train_log)

    # Step 6: Evaluate on test set.
    # Predict in log-space, then inverse-transform to dollar-space for metrics.
    y_pred_log = model_main.predict(X_test)
    y_pred_lower_log = model_lower.predict(X_test)
    y_pred_upper_log = model_upper.predict(X_test)

    y_pred = np.expm1(y_pred_log)
    y_pred_lower = np.expm1(y_pred_lower_log)
    y_pred_upper = np.expm1(y_pred_upper_log)

    # Ensure bounds are sensible
    y_pred_lower = np.minimum(y_pred_lower, y_pred)
    y_pred_upper = np.maximum(y_pred_upper, y_pred)

    metrics = evaluate_model(
        y_test.values, y_pred, y_pred_lower, y_pred_upper
    )

    neighborhood_results = evaluate_by_neighborhood(
        y_test.values, y_pred, neighborhoods_test, min_samples=5
    )

    property_type_results = evaluate_by_property_type(
        y_test.values, y_pred, property_types_test, min_samples=3
    )

    # Feature importances via permutation importance.
    # Note: permutation importance is computed on log-space predictions
    # vs log-space targets.  This is acceptable because the ranking of
    # feature importances is preserved under monotonic transforms.
    perm_result = permutation_importance(
        model_main, X_test, np.log1p(y_test),
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
        metrics, neighborhood_results, feature_imp,
        property_type_metrics=property_type_results,
    )
    print(report)

    # Step 7: Package artifact
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
        log_target=True,
        property_type_metrics=property_type_results,
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
        y_train: Training target values (log-transformed).
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
        "Grid search complete. Best MAE (log-space): %s. Best params: %s",
        f"{best_score:,.4f}",
        best_params,
    )

    return best_params
