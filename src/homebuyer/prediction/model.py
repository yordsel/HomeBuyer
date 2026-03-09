"""Model artifact management: save, load, and predict.

The ModelArtifact bundles the trained model(s), label encoders,
feature names, and training metadata into a single serializable
object. This is the interface used by CLI commands and the listing
scorer to make predictions.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import LabelEncoder

from homebuyer.config import DATA_DIR
from homebuyer.prediction.features import FeatureBuilder
from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)

# Default path for model artifacts
MODEL_DIR = DATA_DIR / "models"
DEFAULT_MODEL_PATH = MODEL_DIR / "berkeley_price_model.joblib"


@dataclass
class PredictionResult:
    """Result of a single price prediction."""

    predicted_price: int
    price_lower: int  # 5th percentile (90% prediction interval)
    price_upper: int  # 95th percentile
    feature_contributions: Optional[list[dict]] = None  # [{name, value, raw_feature}]
    base_value: Optional[int] = None  # model's baseline prediction (avg)
    neighborhood: Optional[str] = None
    list_price: Optional[int] = None
    predicted_premium_pct: Optional[float] = None  # vs list price
    data_warnings: Optional[list[str]] = None  # data quality warnings


@dataclass
class ModelArtifact:
    """Serializable model artifact with everything needed for predictions.

    Attributes:
        model: Main regression model (point estimate).
        model_lower: Quantile model for lower bound (5th percentile).
        model_upper: Quantile model for upper bound (95th percentile).
        feature_names: Ordered list of feature column names.
        label_encoders: Dict of fitted LabelEncoders for categoricals.
        training_metrics: Dict of evaluation metrics from test set.
        trained_at: Timestamp when the model was trained.
        data_cutoff_date: Latest sale date in training data.
        feature_importances: Dict of feature name → importance weight.
        train_size: Number of training examples.
        test_size: Number of test examples.
        neighborhood_metrics: Per-neighborhood evaluation results.
        hyperparameters: Best hyperparameters from grid search.
    """

    model: HistGradientBoostingRegressor
    model_lower: HistGradientBoostingRegressor
    model_upper: HistGradientBoostingRegressor
    feature_names: list[str]
    label_encoders: dict[str, LabelEncoder]
    training_metrics: dict = field(default_factory=dict)
    trained_at: datetime = field(default_factory=datetime.now)
    data_cutoff_date: str = ""
    feature_importances: dict[str, float] = field(default_factory=dict)
    train_size: int = 0
    test_size: int = 0
    neighborhood_metrics: list[dict] = field(default_factory=list)
    hyperparameters: dict = field(default_factory=dict)
    log_target: bool = False  # Whether the model was trained on log1p(y)
    property_type_metrics: list[dict] = field(default_factory=list)

    def save(self, path: Optional[Path] = None) -> Path:
        """Save the model artifact to disk.

        Args:
            path: File path. Defaults to data/models/berkeley_price_model.joblib.

        Returns:
            The path where the artifact was saved.
        """
        if path is None:
            path = DEFAULT_MODEL_PATH

        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        logger.info("Model artifact saved to %s (%.1f MB).", path, path.stat().st_size / 1e6)
        return path

    @staticmethod
    def load(path: Optional[Path] = None) -> "ModelArtifact":
        """Load a model artifact from disk.

        Args:
            path: File path. Defaults to data/models/berkeley_price_model.joblib.

        Returns:
            The loaded ModelArtifact.

        Raises:
            FileNotFoundError: If the model file doesn't exist.
        """
        if path is None:
            path = DEFAULT_MODEL_PATH

        if not path.exists():
            raise FileNotFoundError(
                f"No model found at {path}. Run 'homebuyer train' first."
            )

        artifact = joblib.load(path)
        logger.info("Model artifact loaded from %s.", path)
        return artifact

    def predict(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Make predictions with prediction intervals.

        Args:
            X: Feature DataFrame with columns matching self.feature_names.

        Returns:
            (predictions, lower_bounds, upper_bounds) as numpy arrays.
        """
        # Ensure column order matches training
        X = X[self.feature_names]

        y_pred = self.model.predict(X)
        y_lower = self.model_lower.predict(X)
        y_upper = self.model_upper.predict(X)

        # Inverse log transform if model was trained on log1p(y)
        if getattr(self, "log_target", False):
            y_pred = np.expm1(y_pred)
            y_lower = np.expm1(y_lower)
            y_upper = np.expm1(y_upper)

        # Ensure bounds are sensible
        y_lower = np.minimum(y_lower, y_pred)
        y_upper = np.maximum(y_upper, y_pred)

        return y_pred, y_lower, y_upper

    def predict_single(
        self,
        db: Database,
        property_dict: dict,
    ) -> PredictionResult:
        """Predict the sale price for a single property.

        Args:
            db: Database connection (needed for market context features).
            property_dict: Dict with property attributes:
                Required: neighborhood, zip_code
                Optional: beds, baths, sqft, year_built, lot_size_sqft,
                         hoa_per_month, latitude, longitude, property_type,
                         sale_date, list_price

        Returns:
            PredictionResult with predicted price, interval, and SHAP contributions.
        """
        # Build feature vector — try to load zoning classifier for spatial lookup
        zoning_classifier = None
        try:
            from homebuyer.processing.zoning import ZoningClassifier
            zoning_classifier = ZoningClassifier()
        except (FileNotFoundError, ImportError):
            logger.debug("ZoningClassifier not available; zoning_class will be NaN if not provided.")

        builder = FeatureBuilder(db, zoning_classifier=zoning_classifier)
        builder.set_encoders(self.label_encoders)

        X = builder.build_single_prediction(property_dict)
        y_pred, y_lower, y_upper = self.predict(X)

        predicted_price = int(round(y_pred[0], -3))  # Round to nearest $1K
        price_lower = int(round(y_lower[0], -3))
        price_upper = int(round(y_upper[0], -3))

        # Ensure minimum price
        predicted_price = max(predicted_price, 0)
        price_lower = max(price_lower, 0)

        # Calculate premium over list if provided
        list_price = property_dict.get("list_price")
        premium_pct = None
        if list_price and list_price > 0:
            premium_pct = round((predicted_price - list_price) / list_price * 100, 1)

        # Compute SHAP feature contributions
        base_value, contributions = self._compute_shap_contributions(
            X, property_dict, builder, predicted_price,
        )

        return PredictionResult(
            predicted_price=predicted_price,
            price_lower=price_lower,
            price_upper=price_upper,
            feature_contributions=contributions,
            base_value=base_value,
            neighborhood=property_dict.get("neighborhood"),
            list_price=list_price,
            predicted_premium_pct=premium_pct,
        )

    def predict_batch_single(
        self,
        property_dict: dict,
        builder: FeatureBuilder,
        explainer: Optional[shap.TreeExplainer] = None,
    ) -> PredictionResult:
        """Predict for a single property using shared builder & explainer.

        Unlike ``predict_single()``, this does NOT create a new
        FeatureBuilder, ZoningClassifier, or TreeExplainer per call.
        The caller pre-creates them once and passes them in for
        efficient batch processing across thousands of properties.

        Args:
            property_dict: Property attributes (same format as predict_single).
            builder: Pre-initialised FeatureBuilder with encoders set.
            explainer: Pre-created shap.TreeExplainer (optional; skips SHAP
                       if ``None``).

        Returns:
            PredictionResult with predicted price, interval, and optionally
            SHAP contributions.
        """
        X = builder.build_single_prediction(property_dict)
        y_pred, y_lower, y_upper = self.predict(X)

        predicted_price = max(int(round(y_pred[0], -3)), 0)
        price_lower = max(int(round(y_lower[0], -3)), 0)
        price_upper = int(round(y_upper[0], -3))

        list_price = property_dict.get("list_price")
        premium_pct = None
        if list_price and list_price > 0:
            premium_pct = round((predicted_price - list_price) / list_price * 100, 1)

        base_value, contributions = None, None
        if explainer is not None:
            base_value, contributions = self._compute_shap_contributions_with_explainer(
                X, property_dict, builder, predicted_price, explainer,
            )

        return PredictionResult(
            predicted_price=predicted_price,
            price_lower=price_lower,
            price_upper=price_upper,
            feature_contributions=contributions,
            base_value=base_value,
            neighborhood=property_dict.get("neighborhood"),
            list_price=list_price,
            predicted_premium_pct=premium_pct,
        )

    def _compute_shap_contributions_with_explainer(
        self,
        X: pd.DataFrame,
        property_dict: dict,
        builder: FeatureBuilder,
        predicted_price: int,
        explainer: shap.TreeExplainer,
    ) -> tuple[Optional[int], Optional[list[dict]]]:
        """Compute SHAP contributions using a pre-created TreeExplainer.

        Identical logic to ``_compute_shap_contributions`` but avoids
        creating a new ``shap.TreeExplainer`` each time.
        """
        try:
            shap_values = explainer.shap_values(X[self.feature_names])

            ev = explainer.expected_value
            if hasattr(ev, '__len__'):
                base = float(np.asarray(ev).flat[0])
            else:
                base = float(ev)
        except Exception:
            logger.warning("SHAP computation failed; skipping contributions.", exc_info=True)
            return None, None

        sv = np.asarray(shap_values)
        sv = sv[0] if sv.ndim == 2 else sv

        # If model was trained on log1p(y), convert SHAP values from
        # log-space to approximate dollar-space using the marginal impact
        # formula: dollar_impact_i ≈ expm1(base + sv[i]) - expm1(base)
        is_log = getattr(self, "log_target", False)
        if is_log:
            base_dollar = float(np.expm1(base))
            sv_dollar = np.array([
                float(np.expm1(base + sv[i]) - np.expm1(base))
                for i in range(len(sv))
            ])
            base = base_dollar
        else:
            sv_dollar = sv.astype(float)

        base_value = int(round(base, -3))

        raw_contributions: list[dict] = []
        for i, feat_name in enumerate(self.feature_names):
            dollar_value = float(sv_dollar[i])
            if abs(dollar_value) < 1.0:
                continue

            label = self._feature_label(
                feat_name, X.iloc[0], property_dict, builder,
            )
            raw_contributions.append({
                "name": label,
                "value": int(round(dollar_value, -2)),
                "raw_feature": feat_name,
            })

        raw_contributions.sort(key=lambda c: abs(c["value"]), reverse=True)

        max_show = 12
        if len(raw_contributions) > max_show:
            top = raw_contributions[:max_show]
            rest_count = len(raw_contributions) - max_show
            top_sum = sum(c["value"] for c in top)
            rest_value = predicted_price - base_value - top_sum
            if abs(rest_value) > 0:
                top.append({
                    "name": f"{rest_count} other factors",
                    "value": rest_value,
                    "raw_feature": "_other",
                })
            raw_contributions = top
        else:
            contrib_sum = sum(c["value"] for c in raw_contributions)
            residual = predicted_price - base_value - contrib_sum
            if abs(residual) > 0 and raw_contributions:
                raw_contributions[-1]["value"] += residual

        return base_value, raw_contributions

    def _compute_shap_contributions(
        self,
        X: pd.DataFrame,
        property_dict: dict,
        builder: FeatureBuilder,
        predicted_price: int,
    ) -> tuple[Optional[int], Optional[list[dict]]]:
        """Compute per-feature SHAP contributions for a single prediction.

        Uses shap.TreeExplainer for exact Shapley values on the
        HistGradientBoostingRegressor model.

        The contributions are rounded for display but adjusted so that
        base_value + sum(contributions) == predicted_price exactly.

        Args:
            X: Single-row feature DataFrame.
            property_dict: Original property dict (for human-readable labels).
            builder: The FeatureBuilder (for reverse-encoding categoricals).
            predicted_price: The final rounded predicted price (for reconciliation).

        Returns:
            (base_value, contributions) where contributions is a list of dicts
            with keys: name (human-readable), value (dollar amount), raw_feature.
        """
        try:
            explainer = shap.TreeExplainer(self.model)
            shap_values = explainer.shap_values(X[self.feature_names])

            # expected_value may be scalar or 0-d/1-d array
            ev = explainer.expected_value
            if hasattr(ev, '__len__'):
                base = float(np.asarray(ev).flat[0])
            else:
                base = float(ev)
        except Exception:
            logger.warning("SHAP computation failed; skipping contributions.", exc_info=True)
            return None, None

        # shap_values shape: (1, n_features) for single prediction
        sv = np.asarray(shap_values)
        sv = sv[0] if sv.ndim == 2 else sv

        # If model was trained on log1p(y), convert SHAP values from
        # log-space to approximate dollar-space.  Each SHAP value represents
        # the additive contribution in log1p(price) space.  To get the
        # dollar impact we compute the marginal effect:
        #   dollar_impact_i ≈ expm1(base + sv[i]) - expm1(base)
        # This converts the small log-space numbers (0.01-0.5) into
        # meaningful dollar amounts (thousands to hundreds of thousands).
        is_log = getattr(self, "log_target", False)
        if is_log:
            base_dollar = float(np.expm1(base))
            sv_dollar = np.array([
                float(np.expm1(base + sv[i]) - np.expm1(base))
                for i in range(len(sv))
            ])
            base = base_dollar
        else:
            sv_dollar = sv.astype(float)

        base_value = int(round(base, -3))

        # Build human-readable contribution dicts
        raw_contributions: list[dict] = []
        for i, feat_name in enumerate(self.feature_names):
            dollar_value = float(sv_dollar[i])
            if abs(dollar_value) < 1.0:
                continue  # skip negligible contributions

            label = self._feature_label(
                feat_name, X.iloc[0], property_dict, builder,
            )
            raw_contributions.append({
                "name": label,
                "value": int(round(dollar_value, -2)),  # round to nearest $100
                "raw_feature": feat_name,
            })

        # Sort by absolute value (largest first)
        raw_contributions.sort(key=lambda c: abs(c["value"]), reverse=True)

        # Keep top contributions; aggregate the rest as "Other factors"
        max_show = 12
        if len(raw_contributions) > max_show:
            top = raw_contributions[:max_show]
            rest_count = len(raw_contributions) - max_show
            # Compute the "other" bucket as the exact residual so everything adds up
            top_sum = sum(c["value"] for c in top)
            rest_value = predicted_price - base_value - top_sum
            if abs(rest_value) > 0:
                top.append({
                    "name": f"{rest_count} other factors",
                    "value": rest_value,
                    "raw_feature": "_other",
                })
            raw_contributions = top
        else:
            # All contributions shown — adjust the smallest one to absorb rounding
            contrib_sum = sum(c["value"] for c in raw_contributions)
            residual = predicted_price - base_value - contrib_sum
            if abs(residual) > 0 and raw_contributions:
                raw_contributions[-1]["value"] += residual

        return base_value, raw_contributions

    @staticmethod
    def _feature_label(
        feat_name: str,
        row: pd.Series,
        property_dict: dict,
        builder: FeatureBuilder,
    ) -> str:
        """Create a human-readable label for a feature contribution.

        Maps internal feature names to user-friendly descriptions,
        including the actual value where informative.
        """
        val = row.get(feat_name)

        # --- Categorical features: decode back to original value ---
        if feat_name == "neighborhood_encoded":
            neighborhood = property_dict.get("neighborhood", "Unknown")
            return f"{neighborhood} neighborhood"

        if feat_name == "zip_code_encoded":
            return f"Zip code {property_dict.get('zip_code', '?')}"

        if feat_name == "zoning_encoded":
            zoning = property_dict.get("zoning_class", "")
            return f"{zoning} zoning" if zoning else "Zoning district"

        if feat_name == "property_type_encoded":
            ptype = property_dict.get("property_type", "")
            if ptype:
                return ptype
            return "Property type"

        # --- Numeric features with readable labels ---
        _LABEL_MAP = {
            "sqft": ("Square footage", "{:,.0f} sqft"),
            "beds": ("Bedrooms", "{:.0f}"),
            "baths": ("Bathrooms", "{:.0f}"),
            "lot_size_sqft": ("Lot size", "{:,.0f} sqft"),
            "unit_count": ("Unit count", "{:.0f}"),
            "building_sqft": ("Building sqft", "{:,.0f} sqft"),
            "effective_sqft": ("Effective sqft", "{:,.0f} sqft"),
            "building_to_listing_sqft_ratio": ("Bldg/listing sqft ratio", "{:.1f}x"),
            "year_built": ("Year built", "{:.0f}"),
            "hoa_per_month": ("HOA", "${:,.0f}/mo"),
            "property_age": ("Property age", "{:.0f} years"),
            "sale_month": ("Sale month", None),
            "sale_quarter": ("Sale quarter", "Q{:.0f}"),
            "bed_bath_ratio": ("Bed/bath ratio", "{:.1f}"),
            "sqft_per_bed": ("Sqft per bedroom", "{:,.0f}"),
            "lot_to_living_ratio": ("Lot/living ratio", "{:.1f}x"),
            "latitude": ("Latitude", "{:.4f}"),
            "longitude": ("Longitude", "{:.4f}"),
            "market_median_price": ("Market median price", "${:,.0f}"),
            "market_sale_to_list": ("Sale-to-list ratio", "{:.1%}"),
            "market_sold_above_pct": ("Sold above list %", "{:.0f}%"),
            "market_median_dom": ("Days on market", "{:.0f}"),
            "rate_30yr": ("30-yr mortgage rate", "{:.2f}%"),
            "nasdaq_level": ("NASDAQ level", "{:,.0f}"),
            "treasury_10yr": ("10-yr Treasury", "{:.2f}%"),
            "consumer_sentiment": ("Consumer sentiment", "{:.1f}"),
            "cpi_sf_yoy": ("Bay Area CPI (YoY)", "{:.1%}"),
            "zip_median_income": ("Zip median income", "${:,.0f}"),
            "price_to_income": ("Price-to-income ratio", "{:.1f}x"),
            # Permit features
            "permit_count_5yr": ("Permits (5yr)", "{:.0f}"),
            "permit_count_total": ("Total permits", "{:.0f}"),
            "total_permit_value": ("Total permit value", "${:,.0f}"),
            "years_since_last_permit": ("Years since permit", "{:.1f}"),
            "has_kitchen_remodel": ("Kitchen remodel", None),
            "has_bath_remodel": ("Bath remodel", None),
            "has_addition": ("Addition/expansion", None),
            "has_adu": ("ADU/conversion", None),
            "has_seismic_retrofit": ("Seismic retrofit", None),
            "has_roof_work": ("Roof work", None),
            "has_solar": ("Solar installed", None),
            "has_electrical_upgrade": ("Electrical upgrade", None),
            "years_since_kitchen": ("Years since kitchen", "{:.1f}"),
            "years_since_bath": ("Years since bath", "{:.1f}"),
            "years_since_roof": ("Years since roof", "{:.1f}"),
            "modernization_value": ("Modernization invest.", "${:,.0f}"),
            "maintenance_value": ("Maintenance invest.", "${:,.0f}"),
            "modernization_recency": ("Recent modernization", "${:,.0f}"),
        }

        if feat_name in _LABEL_MAP:
            label, fmt = _LABEL_MAP[feat_name]
            if fmt and pd.notna(val):
                try:
                    return f"{label} ({fmt.format(val)})"
                except (ValueError, TypeError):
                    pass
            return label

        # Fallback: use the raw feature name
        return feat_name.replace("_", " ").title()

    def simulate_improvements(
        self,
        db: Database,
        property_dict: dict,
        improvements: list[dict],
    ) -> dict:
        """Simulate the effect of improvements on predicted price.

        Takes the property's current features, modifies permit-related features
        to simulate each improvement, and re-predicts. Returns the predicted
        price delta for each improvement individually and combined.

        Args:
            db: Database connection.
            property_dict: Property dict (same format as predict_single).
            improvements: List of dicts with keys:
                - category: str (e.g. "kitchen", "bathroom", "adu")
                - estimated_cost: float (permit job value)

        Returns:
            Dict with:
                - current_price: int
                - improved_price: int (all improvements combined)
                - total_delta: int
                - total_cost: int
                - roi_ratio: float (delta / cost)
                - individual: list of per-improvement dicts
        """
        from homebuyer.prediction.features import (
            _MODERNIZATION_CATEGORIES,
            _MAINTENANCE_CATEGORIES,
        )

        # Get current prediction
        current = self.predict_single(db, property_dict)
        current_price = current.predicted_price

        # Build feature vector for the current property
        zoning_classifier = None
        try:
            from homebuyer.processing.zoning import ZoningClassifier
            zoning_classifier = ZoningClassifier()
        except (FileNotFoundError, ImportError):
            pass

        builder = FeatureBuilder(db, zoning_classifier=zoning_classifier)
        builder.set_encoders(self.label_encoders)

        # Ensure caches are loaded
        if builder._market_cache is None:
            builder._load_market_cache()
        if builder._rate_cache is None:
            builder._load_rate_cache()
        if builder._econ_cache is None:
            builder._load_econ_cache()
        if builder._income_cache is None:
            builder._load_income_cache()
        if builder._permit_cache is None:
            builder._load_permit_cache()

        base_X = builder.build_single_prediction(property_dict.copy())

        individual_results = []
        total_cost = 0

        for imp in improvements:
            cat = imp["category"].lower()
            cost = imp.get("estimated_cost", 0)
            total_cost += cost

            # Simulate: modify permit features on a copy
            sim_X = base_X.copy()

            # Increment permit counts
            if "permit_count_5yr" in sim_X.columns:
                cur = sim_X["permit_count_5yr"].iloc[0]
                sim_X.iloc[0, sim_X.columns.get_loc("permit_count_5yr")] = (
                    (cur if pd.notna(cur) else 0) + 1
                )
            if "permit_count_total" in sim_X.columns:
                cur = sim_X["permit_count_total"].iloc[0]
                sim_X.iloc[0, sim_X.columns.get_loc("permit_count_total")] = (
                    (cur if pd.notna(cur) else 0) + 1
                )

            # Set years_since_last_permit to 0 (just done)
            if "years_since_last_permit" in sim_X.columns:
                sim_X.iloc[0, sim_X.columns.get_loc("years_since_last_permit")] = 0.0

            # Update composite scores based on category
            if cat in _MODERNIZATION_CATEGORIES:
                if "modernization_recency" in sim_X.columns:
                    cur = sim_X["modernization_recency"].iloc[0]
                    # decay=1.0 for brand new (0 years ago)
                    sim_X.iloc[0, sim_X.columns.get_loc("modernization_recency")] = (
                        (cur if pd.notna(cur) else 0) + cost * 1.0
                    )
            elif cat in _MAINTENANCE_CATEGORIES:
                if "maintenance_value" in sim_X.columns:
                    cur = sim_X["maintenance_value"].iloc[0]
                    sim_X.iloc[0, sim_X.columns.get_loc("maintenance_value")] = (
                        (cur if pd.notna(cur) else 0) + cost
                    )

            # Predict with simulated features
            y_pred, _, _ = self.predict(sim_X)
            sim_price = int(round(y_pred[0], -3))
            delta = sim_price - current_price

            individual_results.append({
                "category": imp["category"],
                "estimated_cost": int(cost),
                "predicted_delta": delta,
                "roi_ratio": round(delta / cost, 2) if cost > 0 else 0,
            })

        # Combined simulation: apply ALL improvements together
        combined_X = base_X.copy()
        total_mod_cost = 0
        total_maint_cost = 0
        n_improvements = len(improvements)

        for imp in improvements:
            cat = imp["category"].lower()
            cost = imp.get("estimated_cost", 0)
            if cat in _MODERNIZATION_CATEGORIES:
                total_mod_cost += cost
            elif cat in _MAINTENANCE_CATEGORIES:
                total_maint_cost += cost

        if "permit_count_5yr" in combined_X.columns:
            cur = combined_X["permit_count_5yr"].iloc[0]
            combined_X.iloc[0, combined_X.columns.get_loc("permit_count_5yr")] = (
                (cur if pd.notna(cur) else 0) + n_improvements
            )
        if "permit_count_total" in combined_X.columns:
            cur = combined_X["permit_count_total"].iloc[0]
            combined_X.iloc[0, combined_X.columns.get_loc("permit_count_total")] = (
                (cur if pd.notna(cur) else 0) + n_improvements
            )
        if "years_since_last_permit" in combined_X.columns:
            combined_X.iloc[0, combined_X.columns.get_loc("years_since_last_permit")] = 0.0
        if "modernization_recency" in combined_X.columns:
            cur = combined_X["modernization_recency"].iloc[0]
            combined_X.iloc[0, combined_X.columns.get_loc("modernization_recency")] = (
                (cur if pd.notna(cur) else 0) + total_mod_cost
            )
        if "maintenance_value" in combined_X.columns:
            cur = combined_X["maintenance_value"].iloc[0]
            combined_X.iloc[0, combined_X.columns.get_loc("maintenance_value")] = (
                (cur if pd.notna(cur) else 0) + total_maint_cost
            )

        y_combined, _, _ = self.predict(combined_X)
        improved_price = int(round(y_combined[0], -3))
        total_delta = improved_price - current_price

        return {
            "current_price": current_price,
            "improved_price": improved_price,
            "total_delta": total_delta,
            "total_cost": int(total_cost),
            "roi_ratio": round(total_delta / total_cost, 2) if total_cost > 0 else 0,
            "individual": individual_results,
        }

    def format_info(self) -> str:
        """Format model metadata as a human-readable string."""
        lines = []
        lines.append("=" * 55)
        lines.append("  BERKELEY PRICE PREDICTION MODEL")
        lines.append("=" * 55)
        lines.append("")
        lines.append(f"  Trained at:      {self.trained_at:%Y-%m-%d %H:%M}")
        lines.append(f"  Data cutoff:     {self.data_cutoff_date}")
        lines.append(f"  Training size:   {self.train_size:,} sales")
        lines.append(f"  Test size:       {self.test_size:,} sales")
        lines.append(f"  Features:        {len(self.feature_names)}")
        lines.append("")

        # Key metrics
        m = self.training_metrics
        if m:
            lines.append("  KEY METRICS (test set)")
            lines.append("  " + "-" * 35)
            lines.append(f"  MAE:             ${m.get('mae', 0):,.0f}")
            lines.append(f"  MAPE:            {m.get('mape', 0):.1f}%")
            lines.append(f"  R²:              {m.get('r2', 0):.4f}")
            lines.append(f"  Within 10%:      {m.get('within_10pct', 0):.1f}%")
            lines.append(f"  Within 20%:      {m.get('within_20pct', 0):.1f}%")
            if "interval_coverage" in m:
                lines.append(f"  90% CI coverage: {m['interval_coverage']:.1f}%")
            lines.append("")

        # Hyperparameters
        if self.hyperparameters:
            lines.append("  BEST HYPERPARAMETERS")
            lines.append("  " + "-" * 35)
            for k, v in self.hyperparameters.items():
                lines.append(f"  {k:<22s} {v}")
            lines.append("")

        # Top features
        if self.feature_importances:
            lines.append("  TOP 10 FEATURES")
            lines.append("  " + "-" * 35)
            sorted_feats = sorted(
                self.feature_importances.items(), key=lambda x: x[1], reverse=True
            )
            for name, imp in sorted_feats[:10]:
                bar = "█" * int(imp * 50)
                lines.append(f"  {name:<22s} {imp:.4f} {bar}")
            lines.append("")

        # Per-property-type accuracy
        pt_metrics = getattr(self, "property_type_metrics", [])
        if pt_metrics:
            lines.append("  PER-PROPERTY-TYPE ACCURACY")
            lines.append("  " + "-" * 35)
            for pm in pt_metrics:
                lines.append(
                    f"  {pm['name']:<25s} MAPE: {pm['mape']:.1f}%"
                )
            lines.append("")

        lines.append("=" * 55)
        return "\n".join(lines)
