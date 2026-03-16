"""Dependency ports (Protocols) for the faketor package.

Nothing inside faketor/ imports from api.py or touches AppState directly.
All infrastructure access goes through these typed interfaces.

The DataLayer Protocol defines the boundary between the faketor package and
the rest of the application. Concrete implementation: AppStateDataLayer
(constructed in api.py). Test implementation: any object satisfying this
Protocol.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataLayer(Protocol):
    """Infrastructure facade for faketor tool execution.

    Concrete implementation lives in ``_infra.AppStateDataLayer``.
    Test implementations can be plain classes that satisfy this Protocol.

    Methods return plain ``dict`` / ``list[dict]`` — no domain objects leak
    through the boundary.  This keeps the protocol stable even as the
    concrete implementations evolve.
    """

    # --- Database ---

    def db_fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        """Execute a SQL query and return the first row, or None."""
        ...

    def db_fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a SQL query and return all rows."""
        ...

    def get_precomputed_scenario(
        self, property_id: int, scenario_type: str
    ) -> dict | None:
        """Retrieve a precomputed scenario by property ID."""
        ...

    def get_precomputed_by_location(
        self,
        lat: float,
        lon: float,
        scenario_type: str,
        max_distance_m: float = 5,
    ) -> dict | None:
        """Retrieve a precomputed scenario by lat/lon proximity."""
        ...

    def find_nearest_sale(
        self, lat: float, lon: float, max_distance_m: float = 50
    ) -> dict | None:
        """Find the nearest property sale record by lat/lon."""
        ...

    # --- ML Model ---

    @property
    def model_available(self) -> bool:
        """Whether the ML price prediction model is loaded."""
        ...

    def predict_price(self, prop: dict) -> dict:
        """Run ML price prediction. Returns dict with predicted_price, price_lower, etc."""
        ...

    # --- Development calculator ---

    @property
    def dev_calc_available(self) -> bool:
        """Whether the development potential calculator is loaded."""
        ...

    def compute_development_potential(
        self,
        lat: float,
        lon: float,
        lot_size_sqft: int | None,
        sqft: int | None,
        address: str | None,
        record_type: str | None,
        lot_group_key: str | None,
        property_category: str | None,
    ) -> dict:
        """Compute zoning, ADU, SB9, and development data for a property."""
        ...

    def get_improvement_roi_data(self) -> list[dict]:
        """Get improvement ROI data (category, avg_cost, premium_pct)."""
        ...

    # --- Rental analyzer ---

    def estimate_rent(
        self,
        beds: int,
        baths: float,
        sqft: int | None,
        neighborhood: str,
        property_value: int,
    ) -> dict:
        """Estimate monthly rent for a property."""
        ...

    def calculate_expenses(
        self, property_value: int, annual_rent: int
    ) -> dict:
        """Calculate annual operating expenses for a rental property."""
        ...

    def find_comparables(self, **kwargs: Any) -> list[dict]:
        """Find comparable sales for a property."""
        ...

    def get_neighborhood_stats(
        self, neighborhood: str, lookback_years: int = 2
    ) -> dict:
        """Get market statistics for a neighborhood."""
        ...

    def generate_market_summary(self) -> dict:
        """Generate a market-wide summary report."""
        ...

    def analyze_investment_scenarios(self, prop: dict, **kwargs: Any) -> dict:
        """Run multi-scenario investment analysis for a property."""
        ...

    # --- Geocoder ---

    def geocode_neighborhood(self, lat: float, lon: float) -> str | None:
        """Reverse-geocode lat/lon to a neighborhood name."""
        ...

    # --- Regulation / Glossary services ---

    def lookup_regulation(
        self, topic: str, zone_code: str | None = None
    ) -> dict:
        """Look up a Berkeley regulation by topic and optional zone code."""
        ...

    def lookup_glossary_term(
        self, topic: str, category: str | None = None
    ) -> dict:
        """Look up a financial/real estate glossary term."""
        ...

    # --- TTL cache ---

    def cache_get(self, key: str) -> Any | None:
        """Get a value from the in-memory TTL cache."""
        ...

    def cache_set(self, key: str, value: Any) -> None:
        """Store a value in the in-memory TTL cache."""
        ...
