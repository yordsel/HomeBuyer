"""Neighborhood lifestyle comparison for occupy segments.

Provides structured comparison of Berkeley neighborhoods across
lifestyle factors: commute, walkability, schools, character, dining,
parks, safety. Initial implementation uses curated local data.

All computation is pure — no DB access, no I/O.

Phase F-9 (#62) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Neighborhood data — curated Berkeley-specific
# ---------------------------------------------------------------------------

# Scores are 1-10 (10 = best)
_NEIGHBORHOOD_DATA: dict[str, dict] = {
    "North Berkeley": {
        "walkability": 8, "transit": 7, "schools": 9, "dining": 7,
        "parks": 8, "safety": 8, "character": "Leafy streets, craftsman homes, Gourmet Ghetto",
        "bart_station": "North Berkeley", "bart_minutes": 5,
        "median_price_tier": "high",
    },
    "South Berkeley": {
        "walkability": 7, "transit": 7, "schools": 6, "dining": 6,
        "parks": 6, "safety": 6, "character": "Diverse, activist roots, eclectic mix",
        "bart_station": "Ashby", "bart_minutes": 5,
        "median_price_tier": "moderate",
    },
    "West Berkeley": {
        "walkability": 6, "transit": 6, "schools": 6, "dining": 7,
        "parks": 5, "safety": 6, "character": "Industrial-to-artisan, breweries, maker spaces",
        "bart_station": "North Berkeley", "bart_minutes": 15,
        "median_price_tier": "moderate",
    },
    "Central Berkeley": {
        "walkability": 9, "transit": 9, "schools": 7, "dining": 8,
        "parks": 7, "safety": 7, "character": "Urban core, UC Berkeley adjacent, vibrant",
        "bart_station": "Downtown Berkeley", "bart_minutes": 3,
        "median_price_tier": "moderate",
    },
    "Elmwood": {
        "walkability": 8, "transit": 6, "schools": 8, "dining": 8,
        "parks": 7, "safety": 8, "character": "Village feel, College Ave shops, family-friendly",
        "bart_station": "Ashby", "bart_minutes": 10,
        "median_price_tier": "high",
    },
    "Rockridge": {
        "walkability": 8, "transit": 8, "schools": 8, "dining": 9,
        "parks": 7, "safety": 8, "character": "Premier shopping, restaurants, tree-lined streets",
        "bart_station": "Rockridge", "bart_minutes": 3,
        "median_price_tier": "very_high",
    },
    "Claremont": {
        "walkability": 5, "transit": 4, "schools": 9, "dining": 5,
        "parks": 8, "safety": 9, "character": "Hillside estates, panoramic views, exclusive",
        "bart_station": "Rockridge", "bart_minutes": 15,
        "median_price_tier": "very_high",
    },
    "Thousand Oaks": {
        "walkability": 6, "transit": 5, "schools": 7, "dining": 5,
        "parks": 7, "safety": 7, "character": "Quiet residential, family-oriented, hilly",
        "bart_station": "Ashby", "bart_minutes": 15,
        "median_price_tier": "high",
    },
    "Berkeley Hills": {
        "walkability": 3, "transit": 3, "schools": 8, "dining": 3,
        "parks": 9, "safety": 9, "character": "Hilltop views, Tilden Park access, secluded",
        "bart_station": "North Berkeley", "bart_minutes": 20,
        "median_price_tier": "very_high",
    },
    "Westbrae": {
        "walkability": 6, "transit": 5, "schools": 8, "dining": 5,
        "parks": 6, "safety": 8, "character": "Hidden gem, family-oriented, near Gilman corridor",
        "bart_station": "North Berkeley", "bart_minutes": 15,
        "median_price_tier": "high",
    },
}

_LIFESTYLE_FACTORS = [
    "walkability", "transit", "schools", "dining", "parks", "safety",
]


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class NeighborhoodLifestyleParams:
    """Inputs for neighborhood lifestyle comparison."""

    neighborhoods: list[str] = field(default_factory=list)
    # Priority weights (optional, default equal)
    priority_walkability: float = 1.0
    priority_transit: float = 1.0
    priority_schools: float = 1.0
    priority_dining: float = 1.0
    priority_parks: float = 1.0
    priority_safety: float = 1.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_neighborhood_lifestyle(params: NeighborhoodLifestyleParams) -> dict:
    """Compare neighborhoods across lifestyle factors."""
    # If no neighborhoods specified, compare all
    neighborhoods = params.neighborhoods or list(_NEIGHBORHOOD_DATA.keys())

    # Build weights
    weights = {
        "walkability": params.priority_walkability,
        "transit": params.priority_transit,
        "schools": params.priority_schools,
        "dining": params.priority_dining,
        "parks": params.priority_parks,
        "safety": params.priority_safety,
    }
    total_weight = sum(weights.values()) or 1.0

    comparisons: list[dict] = []
    for name in neighborhoods:
        data = _NEIGHBORHOOD_DATA.get(name)
        if data is None:
            continue

        # Weighted composite score
        weighted_sum = sum(
            data.get(factor, 5) * weights[factor]
            for factor in _LIFESTYLE_FACTORS
        )
        composite = round(weighted_sum / total_weight, 1)

        comparisons.append({
            "neighborhood": name,
            "scores": {f: data.get(f, 5) for f in _LIFESTYLE_FACTORS},
            "composite_score": composite,
            "character": data.get("character", ""),
            "bart_station": data.get("bart_station"),
            "bart_minutes": data.get("bart_minutes"),
            "median_price_tier": data.get("median_price_tier"),
        })

    # Sort by composite score
    comparisons.sort(key=lambda c: c["composite_score"], reverse=True)

    # Find best per factor
    best_per_factor = {}
    for factor in _LIFESTYLE_FACTORS:
        best = max(
            comparisons, key=lambda c: c["scores"].get(factor, 0)
        ) if comparisons else None
        if best:
            best_per_factor[factor] = best["neighborhood"]

    return {
        "neighborhoods_compared": len(comparisons),
        "comparisons": comparisons,
        "best_overall": comparisons[0]["neighborhood"] if comparisons else None,
        "best_per_factor": best_per_factor,
        "available_neighborhoods": sorted(_NEIGHBORHOOD_DATA.keys()),
        "weights_used": weights,
    }
