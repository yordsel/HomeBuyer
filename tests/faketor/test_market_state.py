"""Tests for MarketSnapshot, MarketDelta, BerkeleyWideMetrics, NeighborhoodMetrics.

Covers:
- Staleness detection
- Delta computation with materiality flags
- Serialization roundtrips
- Edge cases (zero prior values)
"""

import time

from homebuyer.services.faketor.state.market import (
    BerkeleyWideMetrics,
    MarketDelta,
    MarketSnapshot,
    NeighborhoodMetrics,
    _RATE_MATERIAL_BPS,
)


# ---------------------------------------------------------------------------
# BerkeleyWideMetrics
# ---------------------------------------------------------------------------


class TestBerkeleyWideMetrics:
    def test_defaults(self):
        m = BerkeleyWideMetrics()
        assert m.median_sale_price == 0
        assert m.inventory == 0

    def test_serialization_roundtrip(self):
        m = BerkeleyWideMetrics(
            median_sale_price=1_200_000,
            median_ppsf=850.0,
            inventory=45,
            months_of_supply=1.8,
        )
        restored = BerkeleyWideMetrics.from_dict(m.to_dict())
        assert restored.median_sale_price == 1_200_000
        assert restored.median_ppsf == 850.0
        assert restored.inventory == 45


# ---------------------------------------------------------------------------
# NeighborhoodMetrics
# ---------------------------------------------------------------------------


class TestNeighborhoodMetrics:
    def test_serialization_roundtrip(self):
        m = NeighborhoodMetrics(
            median_price=1_400_000,
            yoy_price_change_pct=5.2,
            sale_count=35,
        )
        restored = NeighborhoodMetrics.from_dict(m.to_dict())
        assert restored.median_price == 1_400_000
        assert restored.yoy_price_change_pct == 5.2


# ---------------------------------------------------------------------------
# MarketDelta
# ---------------------------------------------------------------------------


class TestMarketDelta:
    def test_any_material_false_when_all_below_threshold(self):
        d = MarketDelta(rate_material=False, price_material=False, inventory_material=False)
        assert d.any_material is False

    def test_any_material_true_rate(self):
        d = MarketDelta(rate_material=True, price_material=False, inventory_material=False)
        assert d.any_material is True

    def test_any_material_true_price(self):
        d = MarketDelta(rate_material=False, price_material=True, inventory_material=False)
        assert d.any_material is True

    def test_any_material_true_inventory(self):
        d = MarketDelta(rate_material=False, price_material=False, inventory_material=True)
        assert d.any_material is True

    def test_serialization_roundtrip(self):
        d = MarketDelta(
            rate_change=-0.25,
            rate_change_pct=-3.57,
            median_price_change=30_000,
            median_price_change_pct=2.5,
            rate_material=True,
            price_material=True,
        )
        restored = MarketDelta.from_dict(d.to_dict())
        assert restored.rate_change == -0.25
        assert restored.rate_material is True
        assert restored.price_material is True
        assert restored.inventory_material is False


# ---------------------------------------------------------------------------
# MarketSnapshot — staleness
# ---------------------------------------------------------------------------


class TestMarketSnapshotStaleness:
    def test_zero_snapshot_is_stale(self):
        ms = MarketSnapshot()
        assert ms.is_stale is True

    def test_fresh_snapshot_not_stale(self):
        ms = MarketSnapshot(snapshot_at=time.time())
        assert ms.is_stale is False

    def test_old_snapshot_is_stale(self):
        ms = MarketSnapshot(snapshot_at=time.time() - 5 * 3600)  # 5 hours ago
        assert ms.is_stale is True


# ---------------------------------------------------------------------------
# MarketSnapshot — compute_delta
# ---------------------------------------------------------------------------


class TestMarketSnapshotDelta:
    def _make_snapshot(
        self,
        rate: float = 6.5,
        median_price: int = 1_200_000,
        inventory: int = 50,
        median_dom: int = 20,
        avg_stl: float = 1.02,
    ) -> MarketSnapshot:
        return MarketSnapshot(
            snapshot_at=time.time(),
            mortgage_rate_30yr=rate,
            berkeley_wide=BerkeleyWideMetrics(
                median_sale_price=median_price,
                inventory=inventory,
                median_dom=median_dom,
                avg_sale_to_list=avg_stl,
            ),
        )

    def test_no_change_yields_immaterial_delta(self):
        prior = self._make_snapshot()
        current = self._make_snapshot()
        delta = current.compute_delta(prior)
        assert delta.any_material is False
        assert delta.rate_change == 0.0
        assert delta.median_price_change == 0

    def test_material_rate_change(self):
        prior = self._make_snapshot(rate=6.5)
        current = self._make_snapshot(rate=6.5 + _RATE_MATERIAL_BPS)  # Exactly at threshold
        delta = current.compute_delta(prior)
        assert delta.rate_material is True
        assert delta.rate_change >= _RATE_MATERIAL_BPS

    def test_sub_material_rate_change(self):
        prior = self._make_snapshot(rate=6.5)
        current = self._make_snapshot(rate=6.5 + 0.05)  # Below 12.5bps
        delta = current.compute_delta(prior)
        assert delta.rate_material is False

    def test_material_price_change(self):
        prior = self._make_snapshot(median_price=1_000_000)
        # 2% change = $20,000
        current = self._make_snapshot(median_price=1_020_000)
        delta = current.compute_delta(prior)
        assert delta.price_material is True
        assert delta.median_price_change == 20_000

    def test_material_inventory_change(self):
        prior = self._make_snapshot(inventory=100)
        current = self._make_snapshot(inventory=111)  # 11% change
        delta = current.compute_delta(prior)
        assert delta.inventory_material is True

    def test_sub_material_inventory_change(self):
        prior = self._make_snapshot(inventory=100)
        current = self._make_snapshot(inventory=105)  # 5% change
        delta = current.compute_delta(prior)
        assert delta.inventory_material is False

    def test_zero_prior_values_no_division_error(self):
        """Zero prior values should not cause ZeroDivisionError."""
        prior = self._make_snapshot(rate=0.0, median_price=0, inventory=0)
        current = self._make_snapshot(rate=6.5, median_price=1_200_000, inventory=50)
        delta = current.compute_delta(prior)
        # Percentage changes should be 0 when prior is 0
        assert delta.rate_change_pct == 0.0
        assert delta.median_price_change_pct == 0.0
        assert delta.inventory_change_pct == 0.0

    def test_dom_and_stl_changes_computed(self):
        prior = self._make_snapshot(median_dom=20, avg_stl=1.02)
        current = self._make_snapshot(median_dom=25, avg_stl=1.05)
        delta = current.compute_delta(prior)
        assert delta.dom_change == 5
        assert abs(delta.sale_to_list_change - 0.03) < 0.001


# ---------------------------------------------------------------------------
# MarketSnapshot — serialization
# ---------------------------------------------------------------------------


class TestMarketSnapshotSerialization:
    def test_empty_roundtrip(self):
        ms = MarketSnapshot()
        restored = MarketSnapshot.from_dict(ms.to_dict())
        assert restored.snapshot_at == 0.0
        assert restored.mortgage_rate_30yr == 0.0

    def test_populated_roundtrip(self):
        ms = MarketSnapshot(
            snapshot_at=1000.0,
            mortgage_rate_30yr=6.75,
            conforming_limit=1_149_825,
            berkeley_wide=BerkeleyWideMetrics(
                median_sale_price=1_350_000,
                inventory=42,
            ),
            neighborhoods={
                "N Berkeley": NeighborhoodMetrics(median_price=1_500_000, sale_count=20),
                "Elmwood": NeighborhoodMetrics(median_price=1_800_000, sale_count=15),
            },
        )
        d = ms.to_dict()
        restored = MarketSnapshot.from_dict(d)
        assert restored.mortgage_rate_30yr == 6.75
        assert restored.conforming_limit == 1_149_825
        assert restored.berkeley_wide.median_sale_price == 1_350_000
        assert len(restored.neighborhoods) == 2
        assert restored.neighborhoods["N Berkeley"].median_price == 1_500_000
