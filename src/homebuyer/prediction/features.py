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
_DERIVED_FEATURES = [
    "property_age",
    "is_sfr",
    "sale_month",
    "sale_quarter",
    "bed_bath_ratio",
    "sqft_per_bed",
    "lot_to_living_ratio",
]

# Label-encoded categorical features
_CATEGORICAL_FEATURES = [
    "neighborhood_encoded",
    "zip_code_encoded",
    "zoning_encoded",
    "property_type_encoded",
]

# Market context features (joined from market_metrics)
# Note: market_inventory and market_months_supply were removed — they exhibit
# regime shift between train and test periods, hurting generalization.
_MARKET_FEATURES = [
    "market_median_price",
    "market_sale_to_list",
    "market_sold_above_pct",
    "market_median_dom",
]

# Mortgage rate features (joined from mortgage_rates)
# Note: rate_15yr removed — collinear with rate_30yr, adds noise.
_RATE_FEATURES = [
    "rate_30yr",
]

# Economic indicator features (joined from economic_indicators)
# Note: Removed nasdaq_3mo_return, nasdaq_6mo_return (temporal regime shift),
# treasury_mortgage_spread (derived + collinear), cpi_sf (raw level, keep YoY),
# unemployment_rate (temporal regime shift).
_ECONOMIC_FEATURES = [
    "nasdaq_level",
    "treasury_10yr",
    "consumer_sentiment",
    "cpi_sf_yoy",
]

# Census income features (joined from census_income)
_INCOME_FEATURES = [
    "zip_median_income",
    "price_to_income",
]

# Building permit features (joined from building_permits)
_PERMIT_FEATURES = [
    "permit_count_5yr",        # Permits filed in 5 years before sale
    "permit_count_total",      # Total permits on record for this address
    "total_permit_value",      # Sum of job_value for all permits
    "has_major_renovation",    # 1 if any permit description has major work keywords
    "years_since_last_permit", # Years between sale_date and most recent permit
    "recent_permit_value",     # Job value of most recent permit (0 if none)
]

# Keywords indicating major renovation work in permit descriptions
_MAJOR_WORK_KEYWORDS = [
    "addition", "adu", "accessory dwelling", "remodel", "renovation",
    "kitchen", "bathroom", "seismic", "retrofit", "foundation",
    "new construction", "rebuild", "convert", "expand", "extension",
    "second story", "2nd story", "solar", "electrical panel",
]

ALL_FEATURE_NAMES = (
    _PROPERTY_FEATURES
    + _DERIVED_FEATURES
    + _CATEGORICAL_FEATURES
    + _MARKET_FEATURES
    + _RATE_FEATURES
    + _ECONOMIC_FEATURES
    + _INCOME_FEATURES
    + _PERMIT_FEATURES
)


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
        min_sale_price: int = 50_000,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Build the full feature matrix and target vector from the database.

        Args:
            min_sale_price: Exclude sales below this amount (likely errors).

        Returns:
            (X, y) where X is a DataFrame of features and y is the sale_price.
        """
        logger.info("Building training data from database...")

        # Load all property sales
        rows = self.db.conn.execute(
            """
            SELECT
                sale_date, sale_price, beds, baths, sqft, lot_size_sqft,
                year_built, hoa_per_month, latitude, longitude,
                property_type, neighborhood, zip_code, zoning_class,
                address
            FROM property_sales
            WHERE sale_price IS NOT NULL
              AND sale_price >= ?
              AND neighborhood IS NOT NULL
            ORDER BY sale_date
            """,
            (min_sale_price,),
        ).fetchall()

        if not rows:
            raise ValueError("No qualifying sales found in database.")

        df = pd.DataFrame([dict(r) for r in rows])
        logger.info("Loaded %d sales from database.", len(df))

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
        # Fit property type encoder on non-null values
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
        # Property age
        current_year = datetime.now().year
        features["property_age"] = np.where(
            features["year_built"].notna(),
            current_year - features["year_built"],
            np.nan,
        )

        # Is single-family residential
        if "property_type" in df.columns:
            features["is_sfr"] = (
                df["property_type"]
                .fillna("")
                .str.contains("Single Family", case=False, na=False)
                .astype(float)
            )
        else:
            features["is_sfr"] = np.nan

        # Temporal features
        sale_dates = pd.to_datetime(df["sale_date"], errors="coerce")
        features["sale_month"] = sale_dates.dt.month.astype(float)
        features["sale_quarter"] = sale_dates.dt.quarter.astype(float)

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

        features["lot_to_living_ratio"] = np.where(
            (features["sqft"].notna()) & (features["sqft"] > 0),
            features["lot_size_sqft"] / features["sqft"],
            np.nan,
        )

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

        # Property type (full categorical, not just binary is_sfr)
        if "property_type" in df.columns:
            features["property_type_encoded"] = self._safe_label_encode(
                df["property_type"].values, self.property_type_encoder
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
            "median_dom": "market_median_dom",
        }

        for i, month in enumerate(sale_months):
            if month in self._market_cache.index:
                row = self._market_cache.loc[month]
                # If multiple rows for same month, take the first
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                for src_col, dst_col in col_mapping.items():
                    if dst_col not in result.columns:
                        result[dst_col] = np.nan
                    result.loc[result.index[i], dst_col] = row.get(src_col, np.nan)
            else:
                for dst_col in col_mapping.values():
                    if dst_col not in result.columns:
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

        for i, date_str in enumerate(sale_dates):
            try:
                sale_dt = pd.Timestamp(date_str)
            except (ValueError, TypeError):
                continue

            # Find closest rate on or before sale date
            mask = self._rate_cache["observation_date"] <= sale_dt
            if mask.any():
                closest = self._rate_cache.loc[mask].iloc[-1]
                result.iloc[i, result.columns.get_loc("rate_30yr")] = closest["rate_30yr"]

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

        # Map FRED series IDs to feature names
        series_feature_map = {
            "NASDAQCOM": "nasdaq_level",
            "GS10": "treasury_10yr",
            "UMCSENT": "consumer_sentiment",
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

    def _join_permit_features(
        self, addresses: pd.Series, sale_dates: pd.Series
    ) -> pd.DataFrame:
        """Compute permit-derived features for each property sale.

        For each sale, looks up all permits at that address and computes:
        - permit_count_5yr: permits filed in the 5 years before the sale
        - permit_count_total: total permits on record
        - total_permit_value: sum of job_value across all permits
        - has_major_renovation: 1 if any description contains major work keywords
        - years_since_last_permit: years between sale and most recent permit
        - recent_permit_value: job_value of the most recent permit

        Args:
            addresses: Series of street addresses.
            sale_dates: Series of sale date timestamps.

        Returns:
            DataFrame with permit feature columns, aligned to input index.
        """
        result = pd.DataFrame(index=addresses.index)
        for col in _PERMIT_FEATURES:
            result[col] = np.nan

        if not self._permit_cache:
            return result

        for i, (address, sale_dt) in enumerate(zip(addresses, sale_dates)):
            if pd.isna(address) or pd.isna(sale_dt):
                continue

            key = str(address).upper().strip()
            permits = self._permit_cache.get(key, [])

            if not permits:
                # Address has no permits — set counts to 0 (not NaN)
                result.iloc[i, result.columns.get_loc("permit_count_5yr")] = 0
                result.iloc[i, result.columns.get_loc("permit_count_total")] = 0
                result.iloc[i, result.columns.get_loc("total_permit_value")] = 0
                result.iloc[i, result.columns.get_loc("has_major_renovation")] = 0
                result.iloc[i, result.columns.get_loc("recent_permit_value")] = 0
                continue

            try:
                sale_timestamp = pd.Timestamp(sale_dt)
            except (ValueError, TypeError):
                continue

            # Total permits
            result.iloc[i, result.columns.get_loc("permit_count_total")] = len(permits)

            # Total job value
            total_value = sum(
                p["job_value"] for p in permits if p["job_value"] is not None
            )
            result.iloc[i, result.columns.get_loc("total_permit_value")] = total_value

            # Has major renovation
            has_major = 0
            for p in permits:
                desc = (p.get("description") or "").lower()
                if any(kw in desc for kw in _MAJOR_WORK_KEYWORDS):
                    has_major = 1
                    break
            result.iloc[i, result.columns.get_loc("has_major_renovation")] = has_major

            # Parse filed dates for time-relative features
            permit_dates = []
            for p in permits:
                filed = p.get("filed_date")
                if filed:
                    try:
                        permit_dates.append(
                            (pd.Timestamp(filed), p.get("job_value"))
                        )
                    except (ValueError, TypeError):
                        pass

            # Permits in the 5 years before sale
            if permit_dates:
                five_yr_ago = sale_timestamp - pd.Timedelta(days=5 * 365)
                count_5yr = sum(
                    1 for dt, _ in permit_dates
                    if five_yr_ago <= dt <= sale_timestamp
                )
                result.iloc[i, result.columns.get_loc("permit_count_5yr")] = count_5yr

                # Most recent permit
                past_permits = [
                    (dt, val) for dt, val in permit_dates if dt <= sale_timestamp
                ]
                if past_permits:
                    most_recent_dt, most_recent_val = max(past_permits, key=lambda x: x[0])
                    years_since = (sale_timestamp - most_recent_dt).days / 365.25
                    result.iloc[
                        i, result.columns.get_loc("years_since_last_permit")
                    ] = years_since
                    result.iloc[
                        i, result.columns.get_loc("recent_permit_value")
                    ] = most_recent_val if most_recent_val is not None else 0
                else:
                    result.iloc[i, result.columns.get_loc("recent_permit_value")] = 0
            else:
                result.iloc[i, result.columns.get_loc("permit_count_5yr")] = 0
                result.iloc[i, result.columns.get_loc("recent_permit_value")] = 0

        return result
