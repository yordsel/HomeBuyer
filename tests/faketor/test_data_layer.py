"""Tests for the DataLayer Protocol and AppStateDataLayer.

Verifies that the Protocol is structural (no inheritance required) and that
the concrete AppStateDataLayer satisfies the Protocol contract.
"""

import pytest

from homebuyer.services.faketor.ports import DataLayer
from homebuyer.services.faketor._infra import AppStateDataLayer


class StubDataLayer:
    """Minimal in-memory DataLayer for testing Protocol satisfaction.

    All methods return safe defaults. This class does NOT inherit from
    DataLayer — it satisfies the Protocol through structural typing.
    """

    def db_fetchone(self, sql, params=()):
        return None

    def db_fetchall(self, sql, params=()):
        return []

    def get_precomputed_scenario(self, property_id, scenario_type):
        return None

    def get_precomputed_by_location(self, lat, lon, scenario_type, max_distance_m=5):
        return None

    def find_nearest_sale(self, lat, lon, max_distance_m=50):
        return None

    @property
    def model_available(self):
        return False

    def predict_price(self, prop):
        return {"predicted_price": 1_000_000}

    @property
    def dev_calc_available(self):
        return False

    def compute_development_potential(
        self, lat, lon, lot_size_sqft, sqft, address, record_type, lot_group_key, property_category
    ):
        return {}

    def get_improvement_roi_data(self):
        return []

    def estimate_rent(self, beds, baths, sqft, neighborhood, property_value):
        return {}

    def calculate_expenses(self, property_value, annual_rent):
        return {}

    def find_comparables(self, **kwargs):
        return []

    def get_neighborhood_stats(self, neighborhood, lookback_years=2):
        return {}

    def generate_market_summary(self):
        return {}

    def analyze_investment_scenarios(self, prop, **kwargs):
        return {}

    def geocode_neighborhood(self, lat, lon):
        return None

    def lookup_regulation(self, topic, zone_code=None):
        return {}

    def lookup_glossary_term(self, topic, category=None):
        return {}

    def cache_get(self, key):
        return None

    def cache_set(self, key, value):
        pass


class TestProtocolSatisfaction:
    """Verify Protocol structural typing behavior."""

    def test_stub_satisfies_protocol(self):
        """StubDataLayer (no inheritance) satisfies DataLayer Protocol."""
        stub = StubDataLayer()
        assert isinstance(stub, DataLayer)

    def test_protocol_is_structural(self):
        """A class with all required methods passes isinstance without inheritance."""
        stub = StubDataLayer()
        # Double-check it's not using inheritance
        assert DataLayer not in type(stub).__mro__
        assert isinstance(stub, DataLayer)

    def test_protocol_rejects_incomplete_impl(self):
        """A class missing methods fails the isinstance check."""

        class IncompleteDataLayer:
            def db_fetchone(self, sql, params=()):
                return None
            # Missing all other methods

        incomplete = IncompleteDataLayer()
        assert not isinstance(incomplete, DataLayer)


class TestAppStateDataLayer:
    """Tests for the concrete AppStateDataLayer."""

    def _make_layer(self, **overrides):
        """Create an AppStateDataLayer with mock infrastructure."""
        defaults = dict(
            db=None,
            model=None,
            dev_calc=None,
            rental_analyzer=None,
            geocoder=None,
            regulation_service=None,
            glossary_service=None,
            cache_get=lambda key: None,
            cache_set=lambda key, value: None,
        )
        defaults.update(overrides)
        return AppStateDataLayer(**defaults)

    def test_satisfies_protocol(self):
        """AppStateDataLayer satisfies the DataLayer Protocol."""
        layer = self._make_layer()
        assert isinstance(layer, DataLayer)

    def test_model_available_when_model_set(self):
        layer = self._make_layer(model=object())  # non-None
        assert layer.model_available is True

    def test_model_unavailable_when_none(self):
        layer = self._make_layer(model=None)
        assert layer.model_available is False

    def test_dev_calc_available_when_set(self):
        layer = self._make_layer(dev_calc=object())
        assert layer.dev_calc_available is True

    def test_dev_calc_unavailable_when_none(self):
        layer = self._make_layer(dev_calc=None)
        assert layer.dev_calc_available is False

    def test_cache_get_delegates(self):
        cache = {"key1": "value1"}
        layer = self._make_layer(cache_get=lambda k: cache.get(k))
        assert layer.cache_get("key1") == "value1"
        assert layer.cache_get("key2") is None

    def test_cache_set_delegates(self):
        cache = {}
        layer = self._make_layer(cache_set=lambda k, v: cache.__setitem__(k, v))
        layer.cache_set("key1", "value1")
        assert cache["key1"] == "value1"

    def test_stub_methods_raise_not_implemented(self):
        """Phase E stubs raise NotImplementedError with clear message."""
        layer = self._make_layer()

        with pytest.raises(NotImplementedError, match="Phase E"):
            layer.db_fetchone("SELECT 1")

        with pytest.raises(NotImplementedError, match="Phase E"):
            layer.predict_price({})

        with pytest.raises(NotImplementedError, match="Phase E"):
            layer.compute_development_potential(37.87, -122.27, None, None, None, None, None, None)

        with pytest.raises(NotImplementedError, match="Phase E"):
            layer.lookup_regulation("adu")

        with pytest.raises(NotImplementedError, match="Phase E"):
            layer.lookup_glossary_term("cap_rate")
