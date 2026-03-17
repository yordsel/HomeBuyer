"""Adjacent market comparison tool.

Compares what a buyer's budget gets in Berkeley vs. adjacent markets
(Oakland, El Cerrito, Albany, Richmond, etc.). Uses curated price-tier
data for initial implementation.

All computation is pure — no DB access, no I/O.

Phase F-10 (#63) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Market data — curated East Bay comparisons
# ---------------------------------------------------------------------------

# Median home prices and typical property attributes by market
_MARKET_DATA: dict[str, dict] = {
    "Berkeley": {
        "median_price": 1_350_000,
        "price_per_sqft": 850,
        "typical_sqft": 1_600,
        "typical_lot_sqft": 5_000,
        "typical_beds": 3,
        "typical_baths": 2.0,
        "school_rating": 7,
        "bart_access": True,
        "commute_sf_minutes": 30,
        "property_tax_rate": 1.18,
        "character": "Academic, diverse, progressive, excellent dining",
    },
    "Oakland - Rockridge": {
        "median_price": 1_400_000,
        "price_per_sqft": 800,
        "typical_sqft": 1_750,
        "typical_lot_sqft": 5_500,
        "typical_beds": 3,
        "typical_baths": 2.0,
        "school_rating": 7,
        "bart_access": True,
        "commute_sf_minutes": 25,
        "property_tax_rate": 1.37,
        "character": "Upscale, walkable, top restaurants, boutiques",
    },
    "Oakland - Temescal": {
        "median_price": 950_000,
        "price_per_sqft": 650,
        "typical_sqft": 1_450,
        "typical_lot_sqft": 4_000,
        "typical_beds": 3,
        "typical_baths": 1.5,
        "school_rating": 5,
        "bart_access": True,
        "commute_sf_minutes": 25,
        "property_tax_rate": 1.37,
        "character": "Hip, diverse, great food scene, rapidly gentrifying",
    },
    "Oakland - Montclair": {
        "median_price": 1_200_000,
        "price_per_sqft": 700,
        "typical_sqft": 1_700,
        "typical_lot_sqft": 7_000,
        "typical_beds": 3,
        "typical_baths": 2.0,
        "school_rating": 8,
        "bart_access": False,
        "commute_sf_minutes": 35,
        "property_tax_rate": 1.37,
        "character": "Hillside village, family-oriented, great schools",
    },
    "Albany": {
        "median_price": 1_100_000,
        "price_per_sqft": 750,
        "typical_sqft": 1_450,
        "typical_lot_sqft": 4_500,
        "typical_beds": 3,
        "typical_baths": 1.5,
        "school_rating": 8,
        "bart_access": False,
        "commute_sf_minutes": 35,
        "property_tax_rate": 1.15,
        "character": "Small-town feel, excellent schools, Solano Ave shops",
    },
    "El Cerrito": {
        "median_price": 950_000,
        "price_per_sqft": 650,
        "typical_sqft": 1_450,
        "typical_lot_sqft": 5_500,
        "typical_beds": 3,
        "typical_baths": 2.0,
        "school_rating": 7,
        "bart_access": True,
        "commute_sf_minutes": 35,
        "property_tax_rate": 1.20,
        "character": "Quiet suburban, bay views, BART-accessible",
    },
    "Richmond - Point Richmond": {
        "median_price": 750_000,
        "price_per_sqft": 500,
        "typical_sqft": 1_500,
        "typical_lot_sqft": 5_000,
        "typical_beds": 3,
        "typical_baths": 2.0,
        "school_rating": 5,
        "bart_access": False,
        "commute_sf_minutes": 40,
        "property_tax_rate": 1.25,
        "character": "Charming village, waterfront, up-and-coming",
    },
    "Kensington": {
        "median_price": 1_250_000,
        "price_per_sqft": 700,
        "typical_sqft": 1_800,
        "typical_lot_sqft": 6_500,
        "typical_beds": 3,
        "typical_baths": 2.0,
        "school_rating": 8,
        "bart_access": False,
        "commute_sf_minutes": 40,
        "property_tax_rate": 1.10,
        "character": "Hilltop village, bay views, quiet, unincorporated",
    },
}


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class AdjacentMarketParams:
    """Inputs for adjacent market comparison."""

    budget: int                     # buyer's total budget
    min_beds: int = 3
    min_baths: float = 1.5
    min_sqft: int = 0
    must_have_bart: bool = False
    max_commute_minutes: int = 60
    markets: list[str] = field(default_factory=list)  # empty = all


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_adjacent_market(params: AdjacentMarketParams) -> dict:
    """Compare what the buyer's budget gets across adjacent markets."""
    markets_to_check = params.markets or list(_MARKET_DATA.keys())

    comparisons: list[dict] = []
    for market_name in markets_to_check:
        data = _MARKET_DATA.get(market_name)
        if data is None:
            continue

        median = data["median_price"]
        price_per_sqft = data["price_per_sqft"]

        # What can the budget buy here?
        if price_per_sqft > 0:
            affordable_sqft = int(round(params.budget / price_per_sqft))
        else:
            affordable_sqft = 0

        budget_ratio = round(params.budget / median, 2) if median > 0 else 0.0
        budget_delta = params.budget - median

        # Meets minimum requirements?
        meets_beds = data["typical_beds"] >= params.min_beds
        meets_baths = data["typical_baths"] >= params.min_baths
        meets_sqft = data["typical_sqft"] >= params.min_sqft or params.min_sqft == 0
        meets_bart = data["bart_access"] if params.must_have_bart else True
        meets_commute = data["commute_sf_minutes"] <= params.max_commute_minutes
        meets_requirements = all([
            meets_beds, meets_baths, meets_sqft, meets_bart, meets_commute
        ])

        # Affordability tier
        if budget_ratio >= 1.3:
            affordability = "Very Affordable"
        elif budget_ratio >= 1.0:
            affordability = "Affordable"
        elif budget_ratio >= 0.8:
            affordability = "Stretch"
        else:
            affordability = "Out of Range"

        comparisons.append({
            "market": market_name,
            "median_price": median,
            "price_per_sqft": price_per_sqft,
            "budget_ratio": budget_ratio,
            "budget_delta": budget_delta,
            "affordability": affordability,
            "affordable_sqft": affordable_sqft,
            "typical_sqft": data["typical_sqft"],
            "sqft_bonus": affordable_sqft - data["typical_sqft"],
            "typical_beds": data["typical_beds"],
            "typical_baths": data["typical_baths"],
            "typical_lot_sqft": data["typical_lot_sqft"],
            "school_rating": data["school_rating"],
            "bart_access": data["bart_access"],
            "commute_sf_minutes": data["commute_sf_minutes"],
            "property_tax_rate": data["property_tax_rate"],
            "character": data["character"],
            "meets_requirements": meets_requirements,
        })

    # Sort by budget ratio (most affordable first)
    comparisons.sort(key=lambda c: c["budget_ratio"], reverse=True)

    # Summary
    affordable = [c for c in comparisons if c["affordability"] in ("Very Affordable", "Affordable")]
    meets_reqs = [c for c in comparisons if c["meets_requirements"]]

    # Berkeley baseline
    berkeley = next((c for c in comparisons if c["market"] == "Berkeley"), None)

    return {
        "budget": params.budget,
        "markets_compared": len(comparisons),
        "comparisons": comparisons,
        "affordable_markets": [c["market"] for c in affordable],
        "affordable_count": len(affordable),
        "meets_requirements_count": len(meets_reqs),
        "berkeley_baseline": berkeley,
        "best_value": comparisons[0]["market"] if comparisons else None,
        "available_markets": sorted(_MARKET_DATA.keys()),
    }
