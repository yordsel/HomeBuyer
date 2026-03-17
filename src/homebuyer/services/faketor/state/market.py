"""Market state containers for the segment-driven Faketor redesign.

Provides a frozen market snapshot that ensures consistency within a
conversation, with delta computation for returning users to surface
material market changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Staleness threshold: 4 hours
_STALE_SECONDS = 4 * 3600

# Materiality thresholds for delta flags
_RATE_MATERIAL_PP = 0.125  # 0.125 percentage points (= 12.5 basis points)
_PRICE_MATERIAL_PCT = 2.0  # 2% median price change
_INVENTORY_MATERIAL_PCT = 10.0  # 10% inventory change


# ---------------------------------------------------------------------------
# BerkeleyWideMetrics — citywide market stats
# ---------------------------------------------------------------------------


@dataclass
class BerkeleyWideMetrics:
    """Berkeley-wide market metrics."""

    median_sale_price: int = 0
    median_list_price: int = 0
    median_ppsf: float = 0.0
    median_dom: int = 0
    avg_sale_to_list: float = 0.0
    inventory: int = 0
    months_of_supply: float = 0.0
    homes_sold: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "median_sale_price": self.median_sale_price,
            "median_list_price": self.median_list_price,
            "median_ppsf": self.median_ppsf,
            "median_dom": self.median_dom,
            "avg_sale_to_list": self.avg_sale_to_list,
            "inventory": self.inventory,
            "months_of_supply": self.months_of_supply,
            "homes_sold": self.homes_sold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BerkeleyWideMetrics:
        return cls(
            median_sale_price=data.get("median_sale_price", 0),
            median_list_price=data.get("median_list_price", 0),
            median_ppsf=data.get("median_ppsf", 0.0),
            median_dom=data.get("median_dom", 0),
            avg_sale_to_list=data.get("avg_sale_to_list", 0.0),
            inventory=data.get("inventory", 0),
            months_of_supply=data.get("months_of_supply", 0.0),
            homes_sold=data.get("homes_sold", 0),
        )


# ---------------------------------------------------------------------------
# NeighborhoodMetrics — per-neighborhood stats
# ---------------------------------------------------------------------------


@dataclass
class NeighborhoodMetrics:
    """Market metrics for a single Berkeley neighborhood."""

    median_price: int = 0
    yoy_price_change_pct: float = 0.0
    sale_count: int = 0
    median_ppsf: float = 0.0
    avg_sale_to_list: float = 0.0
    median_dom: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "median_price": self.median_price,
            "yoy_price_change_pct": self.yoy_price_change_pct,
            "sale_count": self.sale_count,
            "median_ppsf": self.median_ppsf,
            "avg_sale_to_list": self.avg_sale_to_list,
            "median_dom": self.median_dom,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NeighborhoodMetrics:
        return cls(
            median_price=data.get("median_price", 0),
            yoy_price_change_pct=data.get("yoy_price_change_pct", 0.0),
            sale_count=data.get("sale_count", 0),
            median_ppsf=data.get("median_ppsf", 0.0),
            avg_sale_to_list=data.get("avg_sale_to_list", 0.0),
            median_dom=data.get("median_dom", 0),
        )


# ---------------------------------------------------------------------------
# MarketDelta — changes between snapshots
# ---------------------------------------------------------------------------


@dataclass
class MarketDelta:
    """Market changes between two snapshots, with materiality flags.

    Materiality flags determine whether the return briefing surfaces
    a change to the user.
    """

    rate_change: float = 0.0  # Absolute change (e.g. -0.25)
    rate_change_pct: float = 0.0  # Percentage change
    median_price_change: int = 0
    median_price_change_pct: float = 0.0
    inventory_change: int = 0
    inventory_change_pct: float = 0.0
    dom_change: int = 0
    sale_to_list_change: float = 0.0

    # Materiality flags
    rate_material: bool = False
    price_material: bool = False
    inventory_material: bool = False

    @property
    def any_material(self) -> bool:
        """True if any delta is material enough to surface to the user."""
        return self.rate_material or self.price_material or self.inventory_material

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate_change": self.rate_change,
            "rate_change_pct": self.rate_change_pct,
            "median_price_change": self.median_price_change,
            "median_price_change_pct": self.median_price_change_pct,
            "inventory_change": self.inventory_change,
            "inventory_change_pct": self.inventory_change_pct,
            "dom_change": self.dom_change,
            "sale_to_list_change": self.sale_to_list_change,
            "rate_material": self.rate_material,
            "price_material": self.price_material,
            "inventory_material": self.inventory_material,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketDelta:
        return cls(
            rate_change=data.get("rate_change", 0.0),
            rate_change_pct=data.get("rate_change_pct", 0.0),
            median_price_change=data.get("median_price_change", 0),
            median_price_change_pct=data.get("median_price_change_pct", 0.0),
            inventory_change=data.get("inventory_change", 0),
            inventory_change_pct=data.get("inventory_change_pct", 0.0),
            dom_change=data.get("dom_change", 0),
            sale_to_list_change=data.get("sale_to_list_change", 0.0),
            rate_material=data.get("rate_material", False),
            price_material=data.get("price_material", False),
            inventory_material=data.get("inventory_material", False),
        )


# ---------------------------------------------------------------------------
# MarketSnapshot — frozen market state for a conversation
# ---------------------------------------------------------------------------


@dataclass
class MarketSnapshot:
    """Frozen market state captured at a point in time.

    Ensures consistency within a conversation. Returning user flow
    detects staleness (>4 hours) and refreshes.
    """

    snapshot_at: float = 0.0  # Timestamp when captured
    mortgage_rate_30yr: float = 0.0
    conforming_limit: int = 0  # Alameda County conforming loan limit
    berkeley_wide: BerkeleyWideMetrics = field(default_factory=BerkeleyWideMetrics)
    neighborhoods: dict[str, NeighborhoodMetrics] = field(default_factory=dict)

    @property
    def is_stale(self) -> bool:
        """True if the snapshot is older than the staleness threshold."""
        if self.snapshot_at == 0.0:
            return True
        return (time.time() - self.snapshot_at) > _STALE_SECONDS

    def compute_delta(self, prior: MarketSnapshot) -> MarketDelta:
        """Compute the delta from a prior snapshot to this one.

        Materiality flags are set based on threshold constants.
        """
        # Rate change
        rate_change = self.mortgage_rate_30yr - prior.mortgage_rate_30yr
        rate_change_pct = (
            (rate_change / prior.mortgage_rate_30yr * 100)
            if prior.mortgage_rate_30yr
            else 0.0
        )

        # Price change
        price_change = self.berkeley_wide.median_sale_price - prior.berkeley_wide.median_sale_price
        price_change_pct = (
            (price_change / prior.berkeley_wide.median_sale_price * 100)
            if prior.berkeley_wide.median_sale_price
            else 0.0
        )

        # Inventory change
        inv_change = self.berkeley_wide.inventory - prior.berkeley_wide.inventory
        inv_change_pct = (
            (inv_change / prior.berkeley_wide.inventory * 100)
            if prior.berkeley_wide.inventory
            else 0.0
        )

        # DOM change
        dom_change = self.berkeley_wide.median_dom - prior.berkeley_wide.median_dom

        # Sale-to-list change
        stl_change = self.berkeley_wide.avg_sale_to_list - prior.berkeley_wide.avg_sale_to_list

        return MarketDelta(
            rate_change=round(rate_change, 4),
            rate_change_pct=round(rate_change_pct, 2),
            median_price_change=price_change,
            median_price_change_pct=round(price_change_pct, 2),
            inventory_change=inv_change,
            inventory_change_pct=round(inv_change_pct, 2),
            dom_change=dom_change,
            sale_to_list_change=round(stl_change, 4),
            rate_material=abs(rate_change) >= _RATE_MATERIAL_PP,
            price_material=abs(price_change_pct) >= _PRICE_MATERIAL_PCT,
            inventory_material=abs(inv_change_pct) >= _INVENTORY_MATERIAL_PCT,
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "mortgage_rate_30yr": self.mortgage_rate_30yr,
            "conforming_limit": self.conforming_limit,
            "berkeley_wide": self.berkeley_wide.to_dict(),
            "neighborhoods": {
                name: metrics.to_dict()
                for name, metrics in self.neighborhoods.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketSnapshot:
        return cls(
            snapshot_at=data.get("snapshot_at", 0.0),
            mortgage_rate_30yr=data.get("mortgage_rate_30yr", 0.0),
            conforming_limit=data.get("conforming_limit", 0),
            berkeley_wide=BerkeleyWideMetrics.from_dict(
                data.get("berkeley_wide", {})
            ),
            neighborhoods={
                name: NeighborhoodMetrics.from_dict(metrics)
                for name, metrics in data.get("neighborhoods", {}).items()
            },
        )
