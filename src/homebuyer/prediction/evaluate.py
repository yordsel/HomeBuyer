"""Evaluation metrics and reporting for price prediction models.

Computes standard regression metrics (MAE, MAPE, R^2) and
Berkeley-specific analyses like per-neighborhood accuracy,
per-property-type accuracy, and prediction interval calibration.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def evaluate_model(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_pred_lower: Optional[np.ndarray] = None,
    y_pred_upper: Optional[np.ndarray] = None,
) -> dict:
    """Compute comprehensive evaluation metrics.

    Args:
        y_true: Actual sale prices.
        y_pred: Predicted sale prices (point estimates).
        y_pred_lower: Lower bound predictions (5th percentile).
        y_pred_upper: Upper bound predictions (95th percentile).

    Returns:
        Dict of metric name -> value.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    # Filter out any NaN
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    y_true = y_true[mask]
    y_pred = y_pred[mask]

    n = len(y_true)
    if n == 0:
        return {"error": "No valid predictions to evaluate."}

    errors = y_true - y_pred
    abs_errors = np.abs(errors)
    pct_errors = abs_errors / np.maximum(y_true, 1)  # avoid div by zero

    metrics: dict = {
        "n_samples": n,
        "mae": float(np.mean(abs_errors)),
        "median_ae": float(np.median(abs_errors)),
        "mape": float(np.mean(pct_errors) * 100),
        "mdape": float(np.median(pct_errors) * 100),
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "r2": float(1 - np.sum(errors ** 2) / np.sum((y_true - np.mean(y_true)) ** 2)),
        "mean_error": float(np.mean(errors)),  # positive = model underestimates
        "within_5pct": float(np.mean(pct_errors <= 0.05) * 100),
        "within_10pct": float(np.mean(pct_errors <= 0.10) * 100),
        "within_15pct": float(np.mean(pct_errors <= 0.15) * 100),
        "within_20pct": float(np.mean(pct_errors <= 0.20) * 100),
    }

    # Prediction interval calibration
    if y_pred_lower is not None and y_pred_upper is not None:
        y_pred_lower = np.asarray(y_pred_lower, dtype=float)[mask]
        y_pred_upper = np.asarray(y_pred_upper, dtype=float)[mask]

        in_interval = (y_true >= y_pred_lower) & (y_true <= y_pred_upper)
        metrics["interval_coverage"] = float(np.mean(in_interval) * 100)
        metrics["avg_interval_width"] = float(np.mean(y_pred_upper - y_pred_lower))
        metrics["avg_interval_width_pct"] = float(
            np.mean((y_pred_upper - y_pred_lower) / np.maximum(y_pred, 1)) * 100
        )

    return metrics


def evaluate_by_neighborhood(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    neighborhoods: np.ndarray,
    min_samples: int = 5,
) -> list[dict]:
    """Compute per-neighborhood accuracy metrics.

    Args:
        y_true: Actual sale prices.
        y_pred: Predicted sale prices.
        neighborhoods: Array of neighborhood names (same length as y_true/y_pred).
        min_samples: Minimum sales in a neighborhood to include.

    Returns:
        List of dicts sorted by MAPE (best first), each with:
        - name, n_samples, mae, mape, mdape, mean_error_pct
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    neighborhoods = np.asarray(neighborhoods)

    results = []
    for hood in np.unique(neighborhoods):
        mask = neighborhoods == hood
        n = mask.sum()
        if n < min_samples:
            continue

        yt = y_true[mask]
        yp = y_pred[mask]
        abs_pct_errors = np.abs(yt - yp) / np.maximum(yt, 1)

        results.append(
            {
                "name": str(hood),
                "n_samples": int(n),
                "mae": float(np.mean(np.abs(yt - yp))),
                "mape": float(np.mean(abs_pct_errors) * 100),
                "mdape": float(np.median(abs_pct_errors) * 100),
                "mean_error_pct": float(np.mean((yt - yp) / np.maximum(yt, 1)) * 100),
            }
        )

    results.sort(key=lambda r: r["mape"])
    return results


def evaluate_by_property_type(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    property_types: np.ndarray,
    min_samples: int = 3,
) -> list[dict]:
    """Compute per-property-type accuracy metrics.

    Args:
        y_true: Actual sale prices.
        y_pred: Predicted sale prices.
        property_types: Array of normalized property type strings.
        min_samples: Minimum sales for a property type to include.

    Returns:
        List of dicts sorted by MAPE (best first), each with:
        - name, n_samples, mae, mape, mdape, mean_error_pct
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    property_types = np.asarray(property_types)

    results = []
    for ptype in np.unique(property_types):
        mask = property_types == ptype
        n = mask.sum()
        if n < min_samples:
            continue

        yt = y_true[mask]
        yp = y_pred[mask]
        abs_pct_errors = np.abs(yt - yp) / np.maximum(yt, 1)

        results.append(
            {
                "name": str(ptype),
                "n_samples": int(n),
                "mae": float(np.mean(np.abs(yt - yp))),
                "mape": float(np.mean(abs_pct_errors) * 100),
                "mdape": float(np.median(abs_pct_errors) * 100),
                "mean_error_pct": float(np.mean((yt - yp) / np.maximum(yt, 1)) * 100),
            }
        )

    results.sort(key=lambda r: r["mape"])
    return results


def format_evaluation_report(
    metrics: dict,
    neighborhood_metrics: Optional[list[dict]] = None,
    feature_importances: Optional[dict[str, float]] = None,
    property_type_metrics: Optional[list[dict]] = None,
) -> str:
    """Format evaluation results as a human-readable report.

    Args:
        metrics: Output from evaluate_model().
        neighborhood_metrics: Output from evaluate_by_neighborhood().
        feature_importances: Dict of feature name -> importance.
        property_type_metrics: Output from evaluate_by_property_type().

    Returns:
        Formatted string report.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("  PRICE PREDICTION MODEL \u2014 EVALUATION REPORT")
    lines.append("=" * 60)
    lines.append("")

    # Overall metrics
    lines.append("  OVERALL METRICS")
    lines.append("  " + "-" * 40)
    lines.append(f"  Test samples:          {metrics.get('n_samples', 'N/A'):,}")
    lines.append(f"  MAE:                   ${metrics.get('mae', 0):,.0f}")
    lines.append(f"  Median AE:             ${metrics.get('median_ae', 0):,.0f}")
    lines.append(f"  MAPE:                  {metrics.get('mape', 0):.1f}%")
    lines.append(f"  Median APE:            {metrics.get('mdape', 0):.1f}%")
    lines.append(f"  RMSE:                  ${metrics.get('rmse', 0):,.0f}")
    lines.append(f"  R\u00b2:                    {metrics.get('r2', 0):.4f}")
    lines.append(f"  Mean Error (bias):     ${metrics.get('mean_error', 0):+,.0f}")
    lines.append("")

    # Accuracy buckets
    lines.append("  ACCURACY DISTRIBUTION")
    lines.append("  " + "-" * 40)
    lines.append(f"  Within  5% of actual:  {metrics.get('within_5pct', 0):.1f}%")
    lines.append(f"  Within 10% of actual:  {metrics.get('within_10pct', 0):.1f}%")
    lines.append(f"  Within 15% of actual:  {metrics.get('within_15pct', 0):.1f}%")
    lines.append(f"  Within 20% of actual:  {metrics.get('within_20pct', 0):.1f}%")
    lines.append("")

    # Prediction interval
    if "interval_coverage" in metrics:
        lines.append("  90% PREDICTION INTERVAL")
        lines.append("  " + "-" * 40)
        lines.append(f"  Actual coverage:       {metrics['interval_coverage']:.1f}%")
        lines.append(f"  Avg interval width:    ${metrics['avg_interval_width']:,.0f}")
        lines.append(f"  Avg interval width:    {metrics['avg_interval_width_pct']:.1f}% of price")
        lines.append("")

    # Feature importances (top 10)
    if feature_importances:
        lines.append("  TOP 10 FEATURE IMPORTANCES")
        lines.append("  " + "-" * 40)
        sorted_feats = sorted(
            feature_importances.items(), key=lambda x: x[1], reverse=True
        )
        for name, imp in sorted_feats[:10]:
            bar = "\u2588" * int(imp * 100)
            lines.append(f"  {name:<25s} {imp:.4f} {bar}")
        lines.append("")

    # Per-property-type metrics
    if property_type_metrics:
        lines.append("  PER-PROPERTY-TYPE ACCURACY")
        lines.append("  " + "-" * 60)
        lines.append(
            f"  {'Property Type':<30s} {'Sales':>6s} {'MAPE':>7s} {'MdAPE':>7s} {'Bias':>8s}"
        )
        lines.append("  " + "-" * 60)
        for pm in property_type_metrics:
            lines.append(
                f"  {pm['name']:<30s} {pm['n_samples']:>6d} "
                f"{pm['mape']:>6.1f}% {pm['mdape']:>6.1f}% "
                f"{pm['mean_error_pct']:>+7.1f}%"
            )
        lines.append("")

    # Per-neighborhood metrics
    if neighborhood_metrics:
        lines.append("  PER-NEIGHBORHOOD ACCURACY")
        lines.append("  " + "-" * 60)
        lines.append(
            f"  {'Neighborhood':<25s} {'Sales':>6s} {'MAPE':>7s} {'MdAPE':>7s} {'Bias':>8s}"
        )
        lines.append("  " + "-" * 60)
        for nm in neighborhood_metrics:
            lines.append(
                f"  {nm['name']:<25s} {nm['n_samples']:>6d} "
                f"{nm['mape']:>6.1f}% {nm['mdape']:>6.1f}% "
                f"{nm['mean_error_pct']:>+7.1f}%"
            )
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
