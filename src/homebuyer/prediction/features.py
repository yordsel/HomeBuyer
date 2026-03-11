"""Feature engineering pipeline for ML price prediction.

Transforms raw property sales data from SQLite into a feature matrix
suitable for scikit-learn's HistGradientBoostingRegressor.

Key design decisions:
- No imputation: HistGBR handles NaN natively, so missing values are
  passed through as-is (np.nan).
- Label encoding for categoricals: neighborhood and zip_code are
  integer-encoded. The encoders are saved with the model artifact
  so we can encode new data at prediction time.
- Market context features: for each sale, we join the closest
  market_metrics row (by sale month) and mortgage_rates row (by date)
  to give the model macroeconomic context.
"""

import logging
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum sale price for training data (filters non-market transactions)
MIN_TRAINING_SALE_PRICE = 100_000

# Maximum sale price for training data.  Excludes large commercial/apartment
# building transactions ($10M+) that are in a fundamentally different market
# segment from residential properties and distort the model.
MAX_TRAINING_SALE_PRICE = 10_000_000

# Earliest sale date to include in training data.  Historical sales from
# the 1990s–2000s are in a completely different price regime and add noise.
# Berkeley home prices roughly 3-5x'd from 2000 to 2024 — including old
# sales forces the model to learn era-specific pricing rather than current
# market drivers.
MIN_TRAINING_SALE_DATE = "2015-01-01"

# Maximum price per sqft for training data (filters per-unit/whole-building mismatches)
# Berkeley's highest legitimate $/sqft is ~$1,500 for premium SFR.
MAX_TRAINING_PRICE_PER_SQFT = 2_000

# Thresholds for detecting "Apartment" records with per-unit features
# but whole-building sale prices (data source mismatch).
_APARTMENT_PER_UNIT_MAX_BEDS = 2
_APARTMENT_PER_UNIT_MAX_SQFT = 1_000

# Canonical property type normalization.
# The property_sales table has "Single Family" (7,512 rows) and
# "Single Family Residential" (2,563 rows) as separate categories.
# The properties table uses "Single Family Residential". Normalize
# so training and inference see the same categories.
PROPERTY_TYPE_MAP: dict[str, str] = {
    "Single Family": "Single Family Residential",
    "Single Family Residential": "Single Family Residential",
    "Multi-Family": "Multi-Family (2-4 Unit)",
    "Apartment": "Multi-Family (5+ Unit)",
    "Multi-Family (2-4 Unit)": "Multi-Family (2-4 Unit)",
    "Multi-Family (5+ Unit)": "Multi-Family (5+ Unit)",
    "Condo/Co-op": "Condo/Co-op",
    "Condo": "Condo/Co-op",
    "Townhouse": "Townhouse",
    "Vacant Land": "Land",
    "Land": "Land",
    "Mobile/Manufactured Home": "Manufactured",
    "Manufactured": "Manufactured",
    "Other": "Other",
}

# Use code → unit count mapping (from Alameda County Assessor codes)
# Corrected per propinfo.acgov.org: 2500 = "2 units, lesser quality"
USE_CODE_UNIT_COUNT: dict[str, int] = {
    "1000": 0,                                          # Vacant land
    "1100": 1, "1200": 1, "1400": 1, "1500": 1,        # SFH variants
    "1505": 1, "1600": 1, "1800": 1,                   # Townhouse condo / detached site condo / other SFR
    "2100": 2, "2200": 2,                               # Duplex (better quality)
    "2300": 3,                                          # Triplex
    "2400": 4,                                          # Fourplex
    "2500": 2,                                          # 2 units, lesser quality (NOT 5+)
    "2501": 5, "2502": 5,                               # 5+ apartments (garden / high-rise)
    "2600": 5,                                          # Mixed use
    "2700": 5,                                          # Other multi
    "7100": 1, "7200": 1, "7300": 1, "7301": 1,        # Condo individual unit
    "7400": 1,                                          # Cooperative unit
    "7700": 5,                                          # Multi-condo (5+)
}

# Features derived directly from property_sales columns
_PROPERTY_FEATURES = [
    "beds",
    "baths",
    "sqft",
    "lot_size_sqft",
    "year_built",
    "hoa_per_month",
    "latitude",
    "longitude",
]

# Derived features computed from property data
# Removed: property_age (r=-1.0 with year_built — perfectly redundant),
#          sale_quarter (r=0.97 with sale_month, zero importance).
_DERIVED_FEATURES = [
    "sale_month",
    "bed_bath_ratio",
    "sqft_per_bed",
    "lot_to_living_ratio",
    "effective_sqft",                  # building_sqft for MF 5+, else sqft
    "building_to_listing_sqft_ratio",  # building_sqft / sqft (signals per-unit mismatch)
    "is_condo_unit",                   # 1 if record_type='unit', else 0
    "effective_lot_size",              # lot_size / units_on_lot for condos, lot_size_sqft for lots
    "units_on_lot",                    # count of properties sharing same lot_group_key
]

# Structural features derived from assessor data (properties table)
_STRUCTURE_FEATURES = [
    "unit_count",       # Number of units (1 for SFH, 2-4 for multi, 5 floor for 5+)
    "building_sqft",    # Total building square footage (vs sqft which is per-unit for multi)
]

# Label-encoded categorical features
_CATEGORICAL_FEATURES = [
    "neighborhood_encoded",
    "zip_code_encoded",
    "zoning_encoded",
    "property_type_encoded",
]

# Market context features (joined from market_metrics)
# Removed: market_inventory, market_months_supply (regime shift),
#          market_median_dom (negative importance).
_MARKET_FEATURES = [
    "market_median_price",
    "market_sale_to_list",
    "market_sold_above_pct",
]

# Mortgage rate features (joined from mortgage_rates)
# Removed: rate_15yr (collinear with rate_30yr).
_RATE_FEATURES = [
    "rate_30yr",
]

# Economic indicator features (joined from economic_indicators)
# Removed: nasdaq_3mo_return, nasdaq_6mo_return (temporal regime shift),
# treasury_mortgage_spread (derived + collinear), cpi_sf (raw level, keep YoY),
# unemployment_rate (temporal regime shift),
# treasury_10yr (r=0.98 with rate_30yr — redundant),
# cpi_sf_yoy (negative importance, 48% temporal shift),
# nasdaq_level (45% temporal shift between train/test — unreliable).
_ECONOMIC_FEATURES = [
    "consumer_sentiment",
]

# Census income features (joined from census_income)
# Removed: price_to_income (100% NaN — never populated, dead weight).
_INCOME_FEATURES = [
    "zip_median_income",
]

# Building permit features (joined from building_permits)
# Removed after analysis:
#   - Individual binary flags (has_kitchen_remodel, has_bath_remodel, etc.) —
#     too sparse (1-8% positive), zero or negative importance. The composite
#     scores capture the same signal better.
#   - total_permit_value — r=0.97 with modernization_value, negative importance.
#   - modernization_value — negative importance, collinear with total_permit_value.
#     Replaced by modernization_recency which weights by recency.
#   - years_since_roof — negative importance.
#   - years_since_kitchen, years_since_bath — >98% NaN, zero importance.
# Kept:
#   - permit_count_5yr, permit_count_total (aggregate activity signals)
#   - years_since_last_permit (recency signal)
#   - maintenance_value (separates upkeep from value-add)
#   - modernization_recency (best composite: weights value × recency)
_PERMIT_FEATURES = [
    "permit_count_5yr",        # Permits filed in 5 years before sale
    "permit_count_total",      # Total permits on record for this address
    "years_since_last_permit", # Years between sale_date and most recent permit
    "maintenance_value",       # $ invested in upkeep (roof, HVAC, plumbing, termite)
    "modernization_recency",   # Recency-weighted modernization (higher = more recent + more $)
]

# Permit category classification by description keywords
# Order matters: first match wins, so put more specific patterns first
_PERMIT_CATEGORIES: list[tuple[str, list[str]]] = [
    ("adu", ["adu", "accessory dwelling", "convert", "duplex"]),
    ("addition", ["addition", "expand", "extension", "2nd story", "second story", "new construction", "rebuild"]),
    ("kitchen", ["kitchen"]),
    ("bathroom", ["bathroom", "bath remodel", "bath renovation"]),
    ("remodel", ["remodel", "renovation", "renovate", "partial renovation"]),
    ("seismic", ["seismic", "retrofit", "foundation replacement", "foundation repair"]),
    ("roof", ["roof", "roofing", "shingle"]),
    ("solar", ["solar", "pv ", "photovoltaic", "ev charger", "energy storage"]),
    ("electrical", ["electrical panel", "panel upgrade", "amp service", "200 amp", "amp upgrade", "rewire"]),
    ("hvac", ["furnace", "hvac", "heater", "heating", "air conditioning", "a/c", "ducting"]),
    ("plumbing", ["plumbing", "sewer", "water line", "water heater", "tankless"]),
    ("windows_doors", ["window", "door", "sliding door", "skylight"]),
    ("exterior", ["fence", "deck", "patio", "siding", "stucco", "paint"]),
    ("termite", ["termite", "pest", "dry rot"]),
]

# Categories considered "modernization" (value-adding improvements)
_MODERNIZATION_CATEGORIES = {"kitchen", "bathroom", "remodel", "addition", "adu", "solar"}
# Categories considered "maintenance" (upkeep, not value-adding)
_MAINTENANCE_CATEGORIES = {"roof", "hvac", "plumbing", "termite", "exterior"}

ALL_FEATURE_NAMES = (
    _PROPERTY_FEATURES
    + _DERIVED_FEATURES
    + _STRUCTURE_FEATURES
    + _CATEGORICAL_FEATURES
    + _MARKET_FEATURES
    + _RATE_FEATURES
    + _ECONOMIC_FEATURES
    + _INCOME_FEATURES
    + _PERMIT_FEATURES
)


# ---------------------------------------------------------------------------
# Training data quality helpers
# ---------------------------------------------------------------------------


def flag_training_outliers(df: pd.DataFrame) -> pd.Series:
    """Flag records with price_per_sqft > 3 std devs from their property_type median.

    Args:
        df: DataFrame with ``sale_price``, ``sqft``, and ``property_type`` columns.

    Returns:
        Boolean Series where ``True`` marks an outlier.
    """
    is_outlier = pd.Series(False, index=df.index)

    valid_sqft = (df["sqft"].notna()) & (pd.to_numeric(df["sqft"], errors="coerce") > 0)
    ppsf = pd.Series(np.nan, index=df.index)
    ppsf[valid_sqft] = (
        pd.to_numeric(df.loc[valid_sqft, "sale_price"], errors="coerce")
        / pd.to_numeric(df.loc[valid_sqft, "sqft"], errors="coerce")
    )

    for ptype in df["property_type"].dropna().unique():
        mask = df["property_type"] == ptype
        group_ppsf = ppsf.loc[mask].dropna()
        if len(group_ppsf) < 5:
            continue  # too few to compute meaningful stats
        median = group_ppsf.median()
        std = group_ppsf.std()
        if std == 0:
            continue
        z_scores = (group_ppsf - median).abs() / std
        outlier_idx = z_scores[z_scores > 3].index
        is_outlier.loc[outlier_idx] = True

    return is_outlier


class FeatureBuilder:
    """Builds feature matrices from the HomeBuyer database.

    Handles label encoding for categorical features and joining market
    context data. Encoders are stored as instance attributes so they
    can be serialized with the model artifact.
    """

    def __init__(
        self,
        db: Database,
        zoning_classifier: Optional["ZoningClassifier"] = None,
    ) -> None:
        self.db = db
        self.neighborhood_encoder = LabelEncoder()
        self.zip_code_encoder = LabelEncoder()
        self.zoning_encoder = LabelEncoder()
        self.property_type_encoder = LabelEncoder()
        self._zoning_classifier = zoning_classifier
        self._market_cache: Optional[pd.DataFrame] = None
        self._rate_cache: Optional[pd.DataFrame] = None
        self._econ_cache: Optional[dict[str, pd.DataFrame]] = None
        self._income_cache: Optional[pd.DataFrame] = None
        self._permit_cache: Optional[dict[str, list[dict]]] = None
        self._is_fitted = False

    @property
    def feature_names(self) -> list[str]:
        """Return the ordered list of feature names."""
        return list(ALL_FEATURE_NAMES)

    # ------------------------------------------------------------------
    # Training data
    # ------------------------------------------------------------------

    def build_training_data(
        self,
        min_sale_price: int = MIN_TRAINING_SALE_PRICE,
        max_sale_price: int = MAX_TRAINING_SALE_PRICE,
        min_sale_date: str = MIN_TRAINING_SALE_DATE,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Build the full feature matrix and target vector from the database.

        Args:
            min_sale_price: Exclude sales below this amount (likely errors).
            max_sale_price: Exclude sales above this amount (commercial buildings).
            min_sale_date: Exclude sales before this date (outdated price regime).

        Returns:
            (X, y) where X is a DataFrame of features and y is the sale_price.
        """
        logger.info("Building training data from database...")

        # Load property sales, enriched with assessor data (use_code,
        # building_sqft, record_type, lot_group_key) via LEFT JOIN
        # to the properties table.
        rows = self.db.conn.execute(
            """
            SELECT
                ps.sale_date, ps.sale_price, ps.beds, ps.baths, ps.sqft,
                ps.lot_size_sqft, ps.year_built, ps.hoa_per_month,
                ps.latitude, ps.longitude, ps.property_type,
                ps.neighborhood, ps.zip_code, ps.zoning_class, ps.address,
                p.use_code,
                p.building_sqft,
                p.record_type,
                p.property_category,
                p.lot_group_key
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
            (min_sale_price, max_sale_price, min_sale_date),
        ).fetchall()

        if not rows:
            raise ValueError("No qualifying sales found in database.")

        df = pd.DataFrame([dict(r) for r in rows])
        logger.info("Loaded %d sales from database.", len(df))

        # Normalize property_type before fitting encoder
        df["property_type"] = df["property_type"].map(
            lambda x: PROPERTY_TYPE_MAP.get(x, x) if pd.notna(x) else x
        )

        # ----- Training data quality filters -----
        # Must run AFTER property_type normalization but BEFORE encoder fitting
        # so that encoders are only fitted on clean data.
        n_before = len(df)

        # 1) Filter "Apartment" records with per-unit features but whole-building
        #    prices. These have beds <= 2, sqft <= 1000 but $M+ sale prices.
        beds_numeric = pd.to_numeric(df["beds"], errors="coerce")
        sqft_numeric = pd.to_numeric(df["sqft"], errors="coerce")
        apartment_per_unit_mask = (
            (df["property_type"] == "Multi-Family (5+ Unit)")
            & (beds_numeric.notna()) & (beds_numeric <= _APARTMENT_PER_UNIT_MAX_BEDS)
            & (sqft_numeric.notna()) & (sqft_numeric <= _APARTMENT_PER_UNIT_MAX_SQFT)
        )
        n_apartment_filtered = int(apartment_per_unit_mask.sum())
        if n_apartment_filtered > 0:
            logger.warning(
                "Removing %d 'Apartment' records with per-unit features "
                "(beds <= %d, sqft <= %d) but whole-building prices.",
                n_apartment_filtered,
                _APARTMENT_PER_UNIT_MAX_BEDS,
                _APARTMENT_PER_UNIT_MAX_SQFT,
            )
            df = df[~apartment_per_unit_mask].reset_index(drop=True)

        # 2) Filter records with extreme price-per-sqft (data mismatch signal).
        sqft_col = pd.to_numeric(df["sqft"], errors="coerce")
        price_col = pd.to_numeric(df["sale_price"], errors="coerce")
        valid_sqft_mask = (sqft_col.notna()) & (sqft_col > 0)
        ppsf = pd.Series(np.nan, index=df.index)
        ppsf[valid_sqft_mask] = price_col[valid_sqft_mask] / sqft_col[valid_sqft_mask]
        extreme_ppsf_mask = ppsf > MAX_TRAINING_PRICE_PER_SQFT
        n_extreme = int(extreme_ppsf_mask.sum())
        if n_extreme > 0:
            logger.warning(
                "Removing %d records with price_per_sqft > $%s/sqft.",
                n_extreme,
                f"{MAX_TRAINING_PRICE_PER_SQFT:,}",
            )
            df = df[~extreme_ppsf_mask.fillna(False)].reset_index(drop=True)

        # 3) Flag statistical outliers by property type (>3 std devs from median $/sqft).
        outlier_mask = flag_training_outliers(df)
        n_outliers = int(outlier_mask.sum())
        if n_outliers > 0:
            logger.warning(
                "Removing %d records flagged as price_per_sqft outliers "
                "(>3 std devs from property_type median).",
                n_outliers,
            )
            df = df[~outlier_mask].reset_index(drop=True)

        n_removed = n_before - len(df)
        if n_removed > 0:
            logger.info(
                "Training data filters: %d -> %d rows (%d removed: "
                "%d apartment per-unit, %d extreme ppsf, %d statistical outliers).",
                n_before, len(df), n_removed,
                n_apartment_filtered, n_extreme, n_outliers,
            )

        # Load contextual data caches
        self._load_market_cache()
        self._load_rate_cache()
        self._load_econ_cache()
        self._load_income_cache()
        self._load_permit_cache()

        # Fit label encoders on all data
        self.neighborhood_encoder.fit(df["neighborhood"].values)
        self.zip_code_encoder.fit(df["zip_code"].values)
        # Fit zoning encoder only on non-null values
        zoning_vals = df["zoning_class"].dropna().values
        if len(zoning_vals) > 0:
            self.zoning_encoder.fit(zoning_vals)
        else:
            logger.warning("No zoning_class values found — zoning feature will be NaN.")
            self.zoning_encoder.fit(["UNKNOWN"])
        # Fit property type encoder on normalized values
        ptype_vals = df["property_type"].dropna().values
        if len(ptype_vals) > 0:
            self.property_type_encoder.fit(ptype_vals)
        else:
            self.property_type_encoder.fit(["Single Family Residential"])
        self._is_fitted = True

        # Build features
        X = self._build_features_df(df)
        y = df["sale_price"].astype(float)

        logger.info(
            "Feature matrix: %d rows × %d columns. Target range: $%s–$%s.",
            X.shape[0],
            X.shape[1],
            f"{y.min():,.0f}",
            f"{y.max():,.0f}",
        )

        return X, y

    # ------------------------------------------------------------------
    # Single-prediction features
    # ------------------------------------------------------------------

    def build_single_prediction(
        self,
        property_dict: dict,
    ) -> pd.DataFrame:
        """Build a feature vector for a single property prediction.

        Args:
            property_dict: Dict with keys matching property_sales columns.
                Required: neighborhood, zip_code
                Optional: beds, baths, sqft, lot_size_sqft, year_built,
                         hoa_per_month, latitude, longitude, property_type,
                         sale_date (defaults to today)

        Returns:
            Single-row DataFrame with the same columns as training data.

        Raises:
            ValueError: If the model hasn't been fitted yet.
        """
        if not self._is_fitted:
            raise ValueError(
                "FeatureBuilder has not been fitted. "
                "Call build_training_data() first or load encoders."
            )

        # Ensure all contextual data caches are loaded
        if self._market_cache is None:
            self._load_market_cache()
        if self._rate_cache is None:
            self._load_rate_cache()
        if self._econ_cache is None:
            self._load_econ_cache()
        if self._income_cache is None:
            self._load_income_cache()
        if self._permit_cache is None:
            self._load_permit_cache()

        # Default sale_date to today if not provided
        if "sale_date" not in property_dict:
            property_dict["sale_date"] = date.today().isoformat()

        # If zoning_class not provided, attempt spatial lookup
        if not property_dict.get("zoning_class"):
            lat = property_dict.get("latitude")
            lon = property_dict.get("longitude")
            if lat and lon and self._zoning_classifier:
                zoning = self._zoning_classifier.classify_point(lat, lon)
                if zoning:
                    property_dict["zoning_class"] = zoning
                    logger.debug("Resolved zoning_class=%s for (%s, %s)", zoning, lat, lon)

        df = pd.DataFrame([property_dict])
        X = self._build_features_df(df)
        return X

    # ------------------------------------------------------------------
    # Encoder management (for serialization)
    # ------------------------------------------------------------------

    def get_encoders(self) -> dict[str, LabelEncoder]:
        """Return the fitted label encoders for serialization."""
        return {
            "neighborhood": self.neighborhood_encoder,
            "zip_code": self.zip_code_encoder,
            "zoning": self.zoning_encoder,
            "property_type": self.property_type_encoder,
        }

    def set_encoders(self, encoders: dict[str, LabelEncoder]) -> None:
        """Restore previously fitted label encoders.

        Args:
            encoders: Dict with 'neighborhood', 'zip_code', and optionally
                     'zoning' and 'property_type' keys.
        """
        self.neighborhood_encoder = encoders["neighborhood"]
        self.zip_code_encoder = encoders["zip_code"]
        if "zoning" in encoders:
            self.zoning_encoder = encoders["zoning"]
        else:
            # Backward compatibility: old models won't have a zoning encoder
            self.zoning_encoder = LabelEncoder()
            self.zoning_encoder.fit(["UNKNOWN"])
        if "property_type" in encoders:
            self.property_type_encoder = encoders["property_type"]
        else:
            # Backward compatibility: old models won't have a property_type encoder
            self.property_type_encoder = LabelEncoder()
            self.property_type_encoder.fit(["Single Family Residential"])
        self._is_fitted = True

    # ------------------------------------------------------------------
    # Private feature construction
    # ------------------------------------------------------------------

    def _build_features_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform a DataFrame of raw sales into the feature matrix.

        Args:
            df: DataFrame with columns from property_sales.

        Returns:
            DataFrame with columns matching ALL_FEATURE_NAMES.
        """
        features = pd.DataFrame(index=df.index)

        # --- Property features (direct columns) ---
        for col in _PROPERTY_FEATURES:
            if col in df.columns:
                features[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                features[col] = np.nan

        # --- Derived features ---
        # Temporal features
        sale_dates = pd.to_datetime(df["sale_date"], errors="coerce")
        features["sale_month"] = sale_dates.dt.month.astype(float)

        # Interaction features
        features["bed_bath_ratio"] = np.where(
            (features["baths"].notna()) & (features["baths"] > 0),
            features["beds"] / features["baths"],
            np.nan,
        )

        features["sqft_per_bed"] = np.where(
            (features["beds"].notna()) & (features["beds"] > 0),
            features["sqft"] / features["beds"],
            np.nan,
        )

        # is_condo_unit: binary flag for condo/unit records
        if "record_type" in df.columns:
            features["is_condo_unit"] = (df["record_type"] == "unit").astype(float)
        else:
            features["is_condo_unit"] = 0.0

        # units_on_lot: count of properties sharing the same lot_group_key.
        # Computed via DB query for training, defaults to 1 for prediction.
        if "lot_group_key" in df.columns:
            lgk = df["lot_group_key"]
            unique_keys = lgk.dropna().unique().tolist()
            if unique_keys and self.db is not None:
                placeholders = ",".join("?" * len(unique_keys))
                rows = self.db.conn.execute(
                    f"SELECT lot_group_key, COUNT(*) FROM properties "
                    f"WHERE lot_group_key IN ({placeholders}) "
                    f"GROUP BY lot_group_key",
                    unique_keys,
                ).fetchall()
                lgk_counts = {r[0]: r[1] for r in rows}
                features["units_on_lot"] = lgk.map(lgk_counts).astype(float)
            else:
                features["units_on_lot"] = np.nan
        else:
            features["units_on_lot"] = np.nan

        # effective_lot_size: for condo units, divide lot_size by units on lot
        # to get per-unit share. For fee_simple lots, use raw lot_size_sqft.
        units_on_lot_safe = features["units_on_lot"].fillna(1).clip(lower=1)
        features["effective_lot_size"] = np.where(
            features["is_condo_unit"] > 0,
            features["lot_size_sqft"] / units_on_lot_safe,
            features["lot_size_sqft"],
        )
        # Set NaN for condos where lot_size is 0 (shared lot with no size data)
        features.loc[
            (features["is_condo_unit"] > 0) & (features["lot_size_sqft"].fillna(0) == 0),
            "effective_lot_size",
        ] = np.nan

        # lot_to_living_ratio: use effective_lot_size for property-type-aware ratio
        features["lot_to_living_ratio"] = np.where(
            (features["sqft"].notna()) & (features["sqft"] > 0)
            & (features["effective_lot_size"].notna()),
            features["effective_lot_size"] / features["sqft"],
            np.nan,
        )

        # effective_sqft: use building_sqft for MF 5+ where available,
        # otherwise fall back to listing sqft.
        if "building_sqft" in df.columns and "use_code" in df.columns:
            unit_count_raw = df["use_code"].map(
                lambda x: USE_CODE_UNIT_COUNT.get(str(x).strip(), np.nan)
                if pd.notna(x) else np.nan
            )
            bldg_sqft = pd.to_numeric(df["building_sqft"], errors="coerce")
            is_mf5plus = unit_count_raw >= 5
            has_bldg = bldg_sqft.notna() & (bldg_sqft > 0)

            features["effective_sqft"] = np.where(
                is_mf5plus & has_bldg,
                bldg_sqft,
                features["sqft"],
            )
        else:
            features["effective_sqft"] = features["sqft"].copy()

        # building_to_listing_sqft_ratio: signals per-unit vs whole-building
        # mismatch.  ~1.0 for SFR, 3-10x for MF with per-unit MLS data.
        if "building_sqft" in df.columns:
            bldg_sqft = pd.to_numeric(df["building_sqft"], errors="coerce")
            features["building_to_listing_sqft_ratio"] = np.where(
                (features["sqft"].notna()) & (features["sqft"] > 0)
                & (bldg_sqft.notna()) & (bldg_sqft > 0),
                bldg_sqft / features["sqft"],
                np.nan,
            )
        else:
            features["building_to_listing_sqft_ratio"] = np.nan

        # --- Structure features (from assessor data) ---
        if "use_code" in df.columns:
            features["unit_count"] = df["use_code"].map(
                lambda x: USE_CODE_UNIT_COUNT.get(str(x).strip(), np.nan)
                if pd.notna(x) else np.nan
            ).astype(float)
        else:
            features["unit_count"] = np.nan

        if "building_sqft" in df.columns:
            features["building_sqft"] = pd.to_numeric(
                df["building_sqft"], errors="coerce"
            )
        else:
            features["building_sqft"] = np.nan

        # --- Categorical features (label encoded) ---
        if "neighborhood" in df.columns:
            features["neighborhood_encoded"] = self._safe_label_encode(
                df["neighborhood"].values, self.neighborhood_encoder
            )
        else:
            features["neighborhood_encoded"] = np.nan

        if "zip_code" in df.columns:
            features["zip_code_encoded"] = self._safe_label_encode(
                df["zip_code"].values, self.zip_code_encoder
            )
        else:
            features["zip_code_encoded"] = np.nan

        # Zoning class
        if "zoning_class" in df.columns:
            features["zoning_encoded"] = self._safe_label_encode(
                df["zoning_class"].values, self.zoning_encoder
            )
        else:
            features["zoning_encoded"] = np.nan

        # Property type (full categorical — normalize before encoding)
        if "property_type" in df.columns:
            normalized_ptypes = df["property_type"].map(
                lambda x: PROPERTY_TYPE_MAP.get(x, x) if pd.notna(x) else x
            )
            features["property_type_encoded"] = self._safe_label_encode(
                normalized_ptypes.values, self.property_type_encoder
            )
        else:
            features["property_type_encoded"] = np.nan

        # --- Market context features ---
        sale_months = sale_dates.dt.to_period("M").astype(str)
        market_features = self._join_market_context(sale_months)
        for col in _MARKET_FEATURES:
            features[col] = market_features[col].values if col in market_features.columns else np.nan

        # --- Mortgage rate features ---
        sale_date_strs = df["sale_date"].astype(str)
        rate_features = self._join_mortgage_rates(sale_date_strs)
        for col in _RATE_FEATURES:
            features[col] = rate_features[col].values if col in rate_features.columns else np.nan

        # --- Economic indicator features ---
        econ_features = self._join_economic_indicators(sale_date_strs)
        for col in _ECONOMIC_FEATURES:
            features[col] = econ_features[col].values if col in econ_features.columns else np.nan

        # --- Census income features ---
        zip_codes = df["zip_code"].astype(str) if "zip_code" in df.columns else pd.Series(dtype=str)
        income_features = self._join_census_income(zip_codes, sale_dates)
        for col in _INCOME_FEATURES:
            features[col] = income_features[col].values if col in income_features.columns else np.nan

        # --- Building permit features ---
        if "address" in df.columns:
            addresses = df["address"].astype(str)
            permit_features = self._join_permit_features(addresses, sale_dates)
            for col in _PERMIT_FEATURES:
                features[col] = (
                    permit_features[col].values
                    if col in permit_features.columns
                    else np.nan
                )
        else:
            for col in _PERMIT_FEATURES:
                features[col] = np.nan

        # Ensure column order matches ALL_FEATURE_NAMES
        for col in ALL_FEATURE_NAMES:
            if col not in features.columns:
                features[col] = np.nan

        features = features[ALL_FEATURE_NAMES]

        return features

    def _safe_label_encode(
        self, values: np.ndarray, encoder: LabelEncoder
    ) -> np.ndarray:
        """Label-encode values, handling unseen categories gracefully.

        Unseen categories get encoded as -1 (which HistGBR treats as
        a valid category, distinct from all known ones).
        """
        result = np.full(len(values), -1, dtype=float)
        known = set(encoder.classes_)

        for i, val in enumerate(values):
            if val in known:
                result[i] = encoder.transform([val])[0]
            else:
                # Unseen category: use NaN so HistGBR handles it natively
                result[i] = np.nan

        return result

    # ------------------------------------------------------------------
    # Market context joining
    # ------------------------------------------------------------------

    def _load_market_cache(self) -> None:
        """Load market metrics into a DataFrame indexed by month."""
        rows = self.db.conn.execute(
            """
            SELECT
                period_begin,
                median_sale_price,
                avg_sale_to_list,
                sold_above_list_pct,
                median_dom
            FROM market_metrics
            WHERE property_type = 'All Residential'
              AND period_duration = '30'
            ORDER BY period_begin
            """
        ).fetchall()

        if rows:
            df = pd.DataFrame([dict(r) for r in rows])
            df["month_key"] = pd.to_datetime(df["period_begin"]).dt.to_period("M").astype(str)
            self._market_cache = df.set_index("month_key")
        else:
            self._market_cache = pd.DataFrame()
            logger.warning("No market metrics found in database.")

    def _join_market_context(self, sale_months: pd.Series) -> pd.DataFrame:
        """Join market context features for each sale by its month.

        Args:
            sale_months: Series of period strings like "2025-01".

        Returns:
            DataFrame with market feature columns, aligned to input index.
        """
        result = pd.DataFrame(index=sale_months.index)

        if self._market_cache is None or self._market_cache.empty:
            for col in _MARKET_FEATURES:
                result[col] = np.nan
            return result

        col_mapping = {
            "median_sale_price": "market_median_price",
            "avg_sale_to_list": "market_sale_to_list",
            "sold_above_list_pct": "market_sold_above_pct",
        }

        # De-duplicate the cache index so .loc always returns a Series
        cache = self._market_cache
        if cache.index.duplicated().any():
            cache = cache[~cache.index.duplicated(keep="first")]

        # Vectorised lookup via .map on a dict per column
        for src_col, dst_col in col_mapping.items():
            if src_col in cache.columns:
                lookup = cache[src_col].to_dict()
                result[dst_col] = sale_months.map(lookup)
            else:
                result[dst_col] = np.nan

        return result

    def _load_rate_cache(self) -> None:
        """Load mortgage rates into a DataFrame indexed by date."""
        rows = self.db.conn.execute(
            """
            SELECT observation_date, rate_30yr, rate_15yr
            FROM mortgage_rates
            WHERE rate_30yr IS NOT NULL
            ORDER BY observation_date
            """
        ).fetchall()

        if rows:
            df = pd.DataFrame([dict(r) for r in rows])
            df["observation_date"] = pd.to_datetime(df["observation_date"])
            self._rate_cache = df
        else:
            self._rate_cache = pd.DataFrame()
            logger.warning("No mortgage rates found in database.")

    def _join_mortgage_rates(self, sale_dates: pd.Series) -> pd.DataFrame:
        """Join the closest mortgage rate for each sale date.

        Uses the most recent observation on or before the sale date.

        Args:
            sale_dates: Series of date strings.

        Returns:
            DataFrame with rate_30yr column.
        """
        result = pd.DataFrame(index=sale_dates.index)
        result["rate_30yr"] = np.nan

        if self._rate_cache is None or self._rate_cache.empty:
            return result

        # Convert sale dates to Timestamps for merge_asof
        sale_ts = pd.to_datetime(sale_dates, errors="coerce")
        valid = sale_ts.notna()
        if not valid.any():
            return result

        # Build a sorted frame of sale dates for merge_asof
        lookup = pd.DataFrame({"sale_dt": sale_ts[valid]}).sort_values("sale_dt")
        rates = self._rate_cache.sort_values("observation_date")

        merged = pd.merge_asof(
            lookup, rates,
            left_on="sale_dt", right_on="observation_date",
            direction="backward",
        )
        result.loc[merged.index, "rate_30yr"] = merged["rate_30yr"].values

        return result

    # ------------------------------------------------------------------
    # Economic indicator joining
    # ------------------------------------------------------------------

    def _load_econ_cache(self) -> None:
        """Load economic indicators into DataFrames keyed by series_id."""
        self._econ_cache = {}

        rows = self.db.conn.execute(
            """
            SELECT series_id, observation_date, value
            FROM economic_indicators
            ORDER BY series_id, observation_date
            """
        ).fetchall()

        if not rows:
            logger.warning("No economic indicators found in database.")
            return

        df = pd.DataFrame([dict(r) for r in rows])
        df["observation_date"] = pd.to_datetime(df["observation_date"])

        for series_id, group in df.groupby("series_id"):
            self._econ_cache[series_id] = group.reset_index(drop=True)

    def _join_economic_indicators(self, sale_dates: pd.Series) -> pd.DataFrame:
        """Join economic indicator features for each sale date.

        For each sale, finds the closest observation on or before the
        sale date. Also computes:
        - cpi_sf_yoy: Bay Area CPI year-over-year % change

        Args:
            sale_dates: Series of date strings.

        Returns:
            DataFrame with economic indicator feature columns.
        """
        result = pd.DataFrame(index=sale_dates.index)
        for col in _ECONOMIC_FEATURES:
            result[col] = np.nan

        if not self._econ_cache:
            return result

        # Map FRED series IDs to feature names — only include those
        # that are in _ECONOMIC_FEATURES (others were removed for
        # collinearity or temporal regime shift).
        _ALL_SERIES_MAP = {
            "NASDAQCOM": "nasdaq_level",
            "GS10": "treasury_10yr",
            "UMCSENT": "consumer_sentiment",
        }
        series_feature_map = {
            k: v for k, v in _ALL_SERIES_MAP.items()
            if v in _ECONOMIC_FEATURES
        }

        for i, date_str in enumerate(sale_dates):
            try:
                sale_dt = pd.Timestamp(date_str)
            except (ValueError, TypeError):
                continue

            # Join each direct series
            for series_id, feature_name in series_feature_map.items():
                series_df = self._econ_cache.get(series_id)
                if series_df is None or series_df.empty:
                    continue

                mask = series_df["observation_date"] <= sale_dt
                if mask.any():
                    closest = series_df.loc[mask].iloc[-1]
                    result.iloc[i, result.columns.get_loc(feature_name)] = closest["value"]

            # Compute Bay Area CPI year-over-year change
            if "cpi_sf_yoy" not in _ECONOMIC_FEATURES:
                continue
            cpi_df = self._econ_cache.get("CUURA422SA0")
            if cpi_df is not None and not cpi_df.empty:
                mask_now = cpi_df["observation_date"] <= sale_dt
                if mask_now.any():
                    current_cpi = cpi_df.loc[mask_now].iloc[-1]["value"]

                    dt_1yr = sale_dt - pd.Timedelta(days=365)
                    mask_1yr = cpi_df["observation_date"] <= dt_1yr
                    if mask_1yr.any():
                        past_cpi = cpi_df.loc[mask_1yr].iloc[-1]["value"]
                        if past_cpi > 0:
                            result.iloc[
                                i, result.columns.get_loc("cpi_sf_yoy")
                            ] = (current_cpi - past_cpi) / past_cpi

        return result

    # ------------------------------------------------------------------
    # Census income joining
    # ------------------------------------------------------------------

    def _load_income_cache(self) -> None:
        """Load Census ACS income data into a DataFrame."""
        rows = self.db.conn.execute(
            """
            SELECT zip_code, acs_year, median_household_income
            FROM census_income
            ORDER BY zip_code, acs_year
            """
        ).fetchall()

        if rows:
            self._income_cache = pd.DataFrame([dict(r) for r in rows])
        else:
            self._income_cache = pd.DataFrame()
            logger.warning("No Census income data found in database.")

    def _join_census_income(
        self, zip_codes: pd.Series, sale_dates: pd.Series
    ) -> pd.DataFrame:
        """Join Census median household income for each sale.

        Uses the ACS vintage year closest to (but not after) the sale
        year. Since ACS 5-year data has a ~2 year lag, the vintage year
        is typically sale_year - 2.

        Also computes price_to_income as a placeholder column (filled
        with NaN here since we don't have sale_price in the feature
        builder; it will be NaN in training since it would be target
        leakage, and can be computed at prediction time from list_price).

        Args:
            zip_codes: Series of zip code strings.
            sale_dates: Series of sale date timestamps.

        Returns:
            DataFrame with zip_median_income and price_to_income columns.
        """
        result = pd.DataFrame(index=zip_codes.index)
        result["zip_median_income"] = np.nan
        result["price_to_income"] = np.nan

        if self._income_cache is None or self._income_cache.empty:
            return result

        for i, (zip_code, sale_dt) in enumerate(zip(zip_codes, sale_dates)):
            if pd.isna(zip_code) or pd.isna(sale_dt):
                continue

            try:
                sale_year = pd.Timestamp(sale_dt).year
            except (ValueError, TypeError):
                continue

            # Find the most recent ACS year for this zip code
            # that is <= sale_year (ACS data is released with ~1yr lag)
            mask = (
                (self._income_cache["zip_code"] == str(zip_code))
                & (self._income_cache["acs_year"] <= sale_year)
            )
            matching = self._income_cache.loc[mask]

            if not matching.empty:
                # Take the most recent vintage
                best = matching.loc[matching["acs_year"].idxmax()]
                income = best["median_household_income"]
                result.iloc[
                    i, result.columns.get_loc("zip_median_income")
                ] = income

        return result

    # ------------------------------------------------------------------
    # Building permit features
    # ------------------------------------------------------------------

    def _load_permit_cache(self) -> None:
        """Load building permits grouped by normalized address.

        Gracefully handles the case where the building_permits table
        does not yet exist (e.g., before any permit collection).
        """
        self._permit_cache = {}

        # Check if the table exists
        table_check = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='building_permits'"
        ).fetchone()
        if not table_check:
            logger.info("No building_permits table found — permit features will be NaN.")
            return

        rows = self.db.conn.execute(
            """
            SELECT address, record_number, permit_type, status,
                   description, job_value, filed_date
            FROM building_permits
            ORDER BY address, filed_date
            """
        ).fetchall()

        if not rows:
            logger.info("No building permits in database — permit features will be NaN.")
            return

        for row in rows:
            r = dict(row)
            key = r["address"].upper().strip()
            if key not in self._permit_cache:
                self._permit_cache[key] = []
            self._permit_cache[key].append(r)

        logger.info(
            "Loaded %d permits for %d unique addresses.",
            len(rows),
            len(self._permit_cache),
        )

    @staticmethod
    def _classify_permit(description: str) -> str:
        """Classify a permit description into a work category.

        Uses keyword matching against _PERMIT_CATEGORIES. First match wins,
        so more specific categories (e.g. 'adu') are checked before broader
        ones (e.g. 'remodel').

        Returns category string or 'other' if no match.
        """
        desc_lower = description.lower()
        for category, keywords in _PERMIT_CATEGORIES:
            if any(kw in desc_lower for kw in keywords):
                return category
        return "other"

    def _join_permit_features(
        self, addresses: pd.Series, sale_dates: pd.Series
    ) -> pd.DataFrame:
        """Compute permit-derived features for each property sale.

        Classifies permits into work categories and computes aggregate,
        composite, and recency features. Only computes features that are
        currently in _PERMIT_FEATURES.

        Args:
            addresses: Series of street addresses.
            sale_dates: Series of sale date timestamps.

        Returns:
            DataFrame with permit feature columns, aligned to input index.
        """
        active = set(_PERMIT_FEATURES)
        result = pd.DataFrame(index=addresses.index)
        for col in _PERMIT_FEATURES:
            result[col] = np.nan

        if not self._permit_cache:
            return result

        # Columns that should be 0 (not NaN) when no permits exist
        zero_cols = [c for c in [
            "permit_count_5yr", "permit_count_total",
            "maintenance_value", "modernization_recency",
        ] if c in active]

        for i, (address, sale_dt) in enumerate(zip(addresses, sale_dates)):
            if pd.isna(address) or pd.isna(sale_dt):
                continue

            key = str(address).upper().strip()
            permits = self._permit_cache.get(key, [])

            if not permits:
                for col in zero_cols:
                    result.iloc[i, result.columns.get_loc(col)] = 0
                continue

            try:
                sale_timestamp = pd.Timestamp(sale_dt)
            except (ValueError, TypeError):
                continue

            # Total permits
            if "permit_count_total" in active:
                result.iloc[i, result.columns.get_loc("permit_count_total")] = len(permits)

            # Classify each permit: (category, filed_timestamp, job_value)
            classified: list[tuple[str, pd.Timestamp | None, float]] = []
            for p in permits:
                desc = p.get("description") or ""
                category = self._classify_permit(desc)
                filed_ts = None
                filed = p.get("filed_date")
                if filed:
                    try:
                        filed_ts = pd.Timestamp(filed)
                    except (ValueError, TypeError):
                        pass
                value = p.get("job_value") or 0.0
                classified.append((category, filed_ts, value))

            # --- Time-based features ---
            dated_permits = [(cat, dt, val) for cat, dt, val in classified if dt is not None]
            if dated_permits:
                past_permits = [
                    (cat, dt, val) for cat, dt, val in dated_permits
                    if dt <= sale_timestamp
                ]

                if "permit_count_5yr" in active:
                    five_yr_ago = sale_timestamp - pd.Timedelta(days=5 * 365)
                    count_5yr = sum(
                        1 for _, dt, _ in dated_permits
                        if five_yr_ago <= dt <= sale_timestamp
                    )
                    result.iloc[i, result.columns.get_loc("permit_count_5yr")] = count_5yr

                if past_permits and "years_since_last_permit" in active:
                    most_recent = max(past_permits, key=lambda x: x[1])
                    years_since = (sale_timestamp - most_recent[1]).days / 365.25
                    result.iloc[
                        i, result.columns.get_loc("years_since_last_permit")
                    ] = years_since
            else:
                if "permit_count_5yr" in active:
                    result.iloc[i, result.columns.get_loc("permit_count_5yr")] = 0

            # --- Composite scores ---
            if "maintenance_value" in active:
                maint_value = sum(
                    val for cat, _, val in classified
                    if cat in _MAINTENANCE_CATEGORIES
                )
                result.iloc[i, result.columns.get_loc("maintenance_value")] = maint_value

            if "modernization_recency" in active:
                mod_recency = 0.0
                for cat, dt, val in classified:
                    if cat in _MODERNIZATION_CATEGORIES and dt is not None and dt <= sale_timestamp:
                        years_ago = max((sale_timestamp - dt).days / 365.25, 0)
                        decay = 1.0 / (1.0 + years_ago)
                        mod_recency += val * decay
                result.iloc[i, result.columns.get_loc("modernization_recency")] = mod_recency

        return result
