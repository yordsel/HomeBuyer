"""Competition assessment for a neighborhood/price-band.

Aggregates competitive dynamics from recent sales data:
  - Sale-to-list ratio (median, distribution)
  - Days on market (median, percentiles)
  - Percentage of sales above/below asking
  - Inventory trend and absorption rate
  - Synthesized competition score (0-100)

The compute function takes pre-aggregated stats as input; the executor
in api.py fetches raw data from the DB.

All computation is pure — no DB access, no I/O.

Phase F-5 (#58) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median, quantiles


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Competition score weights (sum to 1.0)
_WEIGHT_SALE_TO_LIST = 0.30
_WEIGHT_DOM = 0.25
_WEIGHT_ABOVE_ASKING = 0.25
_WEIGHT_ABSORPTION = 0.20

# Score normalization bounds
_SALE_TO_LIST_HOT = 1.05    # ≥105% → max score
_SALE_TO_LIST_COLD = 0.95   # ≤95% → min score
_DOM_HOT = 7                # ≤7 DOM → max score
_DOM_COLD = 60              # ≥60 DOM → min score
_ABOVE_ASKING_HOT = 0.80    # ≥80% above asking → max score
_ABOVE_ASKING_COLD = 0.10   # ≤10% above asking → min score
_ABSORPTION_HOT = 0.50      # ≥50% monthly absorption → max score
_ABSORPTION_COLD = 0.10     # ≤10% monthly absorption → min score

# Score labels
_SCORE_LABELS = [
    (80, "Very Competitive"),
    (60, "Competitive"),
    (40, "Moderate"),
    (20, "Buyer-Friendly"),
    (0, "Very Buyer-Friendly"),
]


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class CompetitionParams:
    """Pre-aggregated market data for competition assessment."""

    neighborhood: str = ""

    # Sale-to-list ratios from recent sales
    sale_to_list_ratios: list[float] = field(default_factory=list)

    # Days on market for recent sales
    dom_values: list[int] = field(default_factory=list)

    # Above/below asking flags (True = above asking)
    above_asking_flags: list[bool] = field(default_factory=list)

    # Inventory metrics
    active_listings: int = 0
    monthly_closed_sales: float = 0.0  # average over recent period

    # Optional price-band filter (for context in output)
    price_min: int | None = None
    price_max: int | None = None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _normalize_score(value: float, hot_bound: float, cold_bound: float) -> float:
    """Normalize a metric to 0-100 score.

    Hot bound = high competition (score 100), cold bound = low (score 0).
    """
    if hot_bound == cold_bound:
        return 50.0
    # Linear interpolation, clamped to [0, 100]
    score = (value - cold_bound) / (hot_bound - cold_bound) * 100
    return max(0.0, min(100.0, score))


def _score_label(score: float) -> str:
    """Return human-readable label for competition score."""
    for threshold, label in _SCORE_LABELS:
        if score >= threshold:
            return label
    return "Very Buyer-Friendly"


def _compute_dom_distribution(dom_values: list[int]) -> dict:
    """Compute DOM distribution with percentiles."""
    if not dom_values:
        return {
            "median": None,
            "p25": None,
            "p75": None,
            "min": None,
            "max": None,
            "under_7_days_pct": None,
            "under_14_days_pct": None,
            "over_30_days_pct": None,
        }

    sorted_dom = sorted(dom_values)
    n = len(sorted_dom)
    med = int(median(sorted_dom))

    if n >= 4:
        q = quantiles(sorted_dom, n=4)
        p25, p75 = int(q[0]), int(q[2])
    elif n >= 2:
        p25 = sorted_dom[0]
        p75 = sorted_dom[-1]
    else:
        p25 = p75 = sorted_dom[0]

    under_7 = sum(1 for d in sorted_dom if d <= 7)
    under_14 = sum(1 for d in sorted_dom if d <= 14)
    over_30 = sum(1 for d in sorted_dom if d > 30)

    return {
        "median": med,
        "p25": p25,
        "p75": p75,
        "min": sorted_dom[0],
        "max": sorted_dom[-1],
        "under_7_days_pct": round(under_7 / n * 100, 1),
        "under_14_days_pct": round(under_14 / n * 100, 1),
        "over_30_days_pct": round(over_30 / n * 100, 1),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_competition(params: CompetitionParams) -> dict:
    """Compute competition assessment for a neighborhood/price-band.

    Returns a dict with metrics, score, and interpretation.
    """
    n_sales = len(params.sale_to_list_ratios)

    # --- Sale-to-list ratio ---
    if params.sale_to_list_ratios:
        stl_median = round(median(params.sale_to_list_ratios), 3)
        stl_min = round(min(params.sale_to_list_ratios), 3)
        stl_max = round(max(params.sale_to_list_ratios), 3)
        stl_score = _normalize_score(stl_median, _SALE_TO_LIST_HOT, _SALE_TO_LIST_COLD)
    else:
        stl_median = stl_min = stl_max = None
        stl_score = 50.0  # neutral default

    # --- Days on market ---
    dom_dist = _compute_dom_distribution(params.dom_values)
    if dom_dist["median"] is not None:
        # Invert: lower DOM = higher competition score
        dom_score = _normalize_score(
            dom_dist["median"], _DOM_HOT, _DOM_COLD
        )
    else:
        dom_score = 50.0

    # --- Above/below asking ---
    if params.above_asking_flags:
        n_above = sum(1 for f in params.above_asking_flags if f)
        n_total = len(params.above_asking_flags)
        above_pct = round(n_above / n_total * 100, 1)
        below_pct = round((n_total - n_above) / n_total * 100, 1)
        above_score = _normalize_score(
            n_above / n_total, _ABOVE_ASKING_HOT, _ABOVE_ASKING_COLD
        )
    else:
        above_pct = below_pct = None
        n_above = 0
        above_score = 50.0

    # --- Absorption rate ---
    if params.monthly_closed_sales > 0 and params.active_listings > 0:
        absorption_rate = round(
            params.monthly_closed_sales / params.active_listings, 3
        )
        months_of_inventory = round(
            params.active_listings / params.monthly_closed_sales, 1
        )
        absorption_score = _normalize_score(
            absorption_rate, _ABSORPTION_HOT, _ABSORPTION_COLD
        )
    elif params.active_listings == 0 and params.monthly_closed_sales > 0:
        absorption_rate = 1.0  # everything sells immediately
        months_of_inventory = 0.0
        absorption_score = 100.0
    else:
        absorption_rate = None
        months_of_inventory = None
        absorption_score = 50.0

    # --- Composite score ---
    competition_score = round(
        stl_score * _WEIGHT_SALE_TO_LIST
        + dom_score * _WEIGHT_DOM
        + above_score * _WEIGHT_ABOVE_ASKING
        + absorption_score * _WEIGHT_ABSORPTION,
        1,
    )

    label = _score_label(competition_score)

    # --- Market interpretation ---
    interpretation_parts = []
    if stl_median is not None and stl_median >= 1.0:
        interpretation_parts.append(
            f"homes selling at {stl_median:.1%} of asking"
        )
    elif stl_median is not None:
        interpretation_parts.append(
            f"homes selling at {stl_median:.1%} of asking (below list)"
        )
    if dom_dist["median"] is not None:
        interpretation_parts.append(
            f"median {dom_dist['median']} days on market"
        )
    if above_pct is not None:
        interpretation_parts.append(
            f"{above_pct}% selling above asking"
        )
    if months_of_inventory is not None:
        interpretation_parts.append(
            f"{months_of_inventory} months of inventory"
        )

    interpretation = "; ".join(interpretation_parts) if interpretation_parts else None

    return {
        # Context
        "neighborhood": params.neighborhood,
        "price_min": params.price_min,
        "price_max": params.price_max,
        "sample_size": n_sales,
        # Sale-to-list
        "sale_to_list_median": stl_median,
        "sale_to_list_min": stl_min,
        "sale_to_list_max": stl_max,
        # DOM
        "dom_distribution": dom_dist,
        # Above/below asking
        "above_asking_pct": above_pct,
        "below_asking_pct": below_pct,
        "above_asking_count": n_above,
        # Inventory
        "active_listings": params.active_listings,
        "monthly_closed_sales": params.monthly_closed_sales,
        "absorption_rate": absorption_rate,
        "months_of_inventory": months_of_inventory,
        # Competition score
        "competition_score": competition_score,
        "competition_label": label,
        # Component scores (for transparency)
        "score_components": {
            "sale_to_list_score": round(stl_score, 1),
            "dom_score": round(dom_score, 1),
            "above_asking_score": round(above_score, 1),
            "absorption_score": round(absorption_score, 1),
        },
        # Interpretation
        "interpretation": interpretation,
    }
