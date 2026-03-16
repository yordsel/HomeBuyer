"""Concrete DataLayer implementation backed by AppState infrastructure.

This module is the ONLY place inside faketor/ that knows about the concrete
infrastructure types (Database, ModelArtifact, DevelopmentPotentialCalculator,
etc.).  It is NOT imported by any other faketor submodule — only api.py's
AppState.__init__ constructs an instance and stores it.

Phase A: All methods raise NotImplementedError.  Phase E will fill in the
real delegation logic (migrating from _faketor_tool_executor in api.py).
"""

from __future__ import annotations

from typing import Any, Callable


class AppStateDataLayer:
    """Wraps AppState-owned services behind the DataLayer Protocol.

    Constructor parameters use untyped annotations to avoid importing
    infrastructure types and creating circular dependencies.  The actual
    types are documented in comments.
    """

    def __init__(
        self,
        *,
        db: Any,  # homebuyer.storage.database.Database
        model: Any,  # homebuyer.prediction.model.ModelArtifact | None
        dev_calc: Any,  # DevelopmentPotentialCalculator | None
        rental_analyzer: Any,  # RentalAnalyzer
        geocoder: Any,  # NeighborhoodGeocoder | None
        regulation_service: Any,  # BerkeleyRegulationService
        glossary_service: Any,  # GlossaryService
        cache_get: Callable[[str], Any | None],
        cache_set: Callable[[str, Any], None],
    ) -> None:
        self._db = db
        self._model = model
        self._dev_calc = dev_calc
        self._rental_analyzer = rental_analyzer
        self._geocoder = geocoder
        self._reg_service = regulation_service
        self._glossary_service = glossary_service
        self._cache_get = cache_get
        self._cache_set = cache_set

    # --- Database ---

    def db_fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        raise NotImplementedError("DataLayer.db_fetchone — Phase E")

    def db_fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        raise NotImplementedError("DataLayer.db_fetchall — Phase E")

    def get_precomputed_scenario(
        self, property_id: int, scenario_type: str
    ) -> dict | None:
        raise NotImplementedError("DataLayer.get_precomputed_scenario — Phase E")

    def get_precomputed_by_location(
        self,
        lat: float,
        lon: float,
        scenario_type: str,
        max_distance_m: float = 5,
    ) -> dict | None:
        raise NotImplementedError("DataLayer.get_precomputed_by_location — Phase E")

    def find_nearest_sale(
        self, lat: float, lon: float, max_distance_m: float = 50
    ) -> dict | None:
        raise NotImplementedError("DataLayer.find_nearest_sale — Phase E")

    # --- ML Model ---

    @property
    def model_available(self) -> bool:
        return self._model is not None

    def predict_price(self, prop: dict) -> dict:
        raise NotImplementedError("DataLayer.predict_price — Phase E")

    # --- Development calculator ---

    @property
    def dev_calc_available(self) -> bool:
        return self._dev_calc is not None

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
        raise NotImplementedError("DataLayer.compute_development_potential — Phase E")

    def get_improvement_roi_data(self) -> list[dict]:
        raise NotImplementedError("DataLayer.get_improvement_roi_data — Phase E")

    # --- Rental analyzer ---

    def estimate_rent(
        self,
        beds: int,
        baths: float,
        sqft: int | None,
        neighborhood: str,
        property_value: int,
    ) -> dict:
        raise NotImplementedError("DataLayer.estimate_rent — Phase E")

    def calculate_expenses(
        self, property_value: int, annual_rent: int
    ) -> dict:
        raise NotImplementedError("DataLayer.calculate_expenses — Phase E")

    def find_comparables(self, **kwargs: Any) -> list[dict]:
        raise NotImplementedError("DataLayer.find_comparables — Phase E")

    def get_neighborhood_stats(
        self, neighborhood: str, lookback_years: int = 2
    ) -> dict:
        raise NotImplementedError("DataLayer.get_neighborhood_stats — Phase E")

    def generate_market_summary(self) -> dict:
        raise NotImplementedError("DataLayer.generate_market_summary — Phase E")

    def analyze_investment_scenarios(self, prop: dict, **kwargs: Any) -> dict:
        raise NotImplementedError("DataLayer.analyze_investment_scenarios — Phase E")

    # --- Geocoder ---

    def geocode_neighborhood(self, lat: float, lon: float) -> str | None:
        raise NotImplementedError("DataLayer.geocode_neighborhood — Phase E")

    # --- Regulation / Glossary services ---

    def lookup_regulation(
        self, topic: str, zone_code: str | None = None
    ) -> dict:
        raise NotImplementedError("DataLayer.lookup_regulation — Phase E")

    def lookup_glossary_term(
        self, topic: str, category: str | None = None
    ) -> dict:
        raise NotImplementedError("DataLayer.lookup_glossary_term — Phase E")

    # --- TTL cache ---

    def cache_get(self, key: str) -> Any | None:
        return self._cache_get(key)

    def cache_set(self, key: str, value: Any) -> None:
        self._cache_set(key, value)
