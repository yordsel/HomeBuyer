"""Deterministic fact computation for Faketor tool results.

Each function takes a tool result dict and returns a ``_facts`` dict with
pre-computed, verified statistics.  These facts are injected into the
``tool_result`` message sent back to Claude so it can cite verified numbers
instead of re-parsing raw JSON.

All functions are pure, fast (microseconds), and defensively coded against
missing or ``None`` fields.
"""

from __future__ import annotations

import logging
from statistics import median
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-tool fact computers
# ---------------------------------------------------------------------------

def compute_search_facts(data: dict) -> dict:
    """Facts for ``search_properties`` results."""
    results = data.get("results") or []
    n = len(results)

    adu_eligible = [
        r for r in results
        if (r.get("development") or {}).get("adu_eligible")
    ]
    sb9_eligible = [
        r for r in results
        if (r.get("development") or {}).get("sb9_eligible")
    ]
    prices = [r["last_sale_price"] for r in results if r.get("last_sale_price")]
    predicted = [r["predicted_price"] for r in results if r.get("predicted_price")]
    lot_sizes = [r["lot_size_sqft"] for r in results if r.get("lot_size_sqft")]
    building_sqfts = [r["building_sqft"] for r in results if r.get("building_sqft")]
    zones = sorted(set(r.get("zoning_class") for r in results if r.get("zoning_class")))
    neighborhoods = sorted(set(r.get("neighborhood") for r in results if r.get("neighborhood")))

    # Data quality metrics
    per_unit_mismatch = [
        r for r in results if r.get("data_quality") == "per_unit_mismatch"
    ]
    clean_results = [
        r for r in results if r.get("data_quality") == "normal"
    ]
    data_quality_warnings = [
        r.get("address") for r in results
        if r.get("data_quality") not in (None, "normal")
    ]

    # Building-to-lot ratio metrics
    bld_ratios = [
        r["building_to_lot_ratio"] for r in results
        if r.get("building_to_lot_ratio") is not None
    ]
    low_density = [
        r for r in results
        if r.get("building_to_lot_ratio") is not None
        and r["building_to_lot_ratio"] < 0.25
    ]

    return {
        "total_results": n,
        "total_matching": data.get("total_matching"),
        "adu_eligible_count": len(adu_eligible),
        "adu_eligible_addresses": [r.get("address") for r in adu_eligible],
        "sb9_eligible_count": len(sb9_eligible),
        "sb9_eligible_addresses": [r.get("address") for r in sb9_eligible],
        "price_range": [min(prices), max(prices)] if prices else None,
        "median_price": int(median(prices)) if prices else None,
        "predicted_price_range": [min(predicted), max(predicted)] if predicted else None,
        "lot_size_range": [min(lot_sizes), max(lot_sizes)] if lot_sizes else None,
        "building_sqft_range": [min(building_sqfts), max(building_sqfts)] if building_sqfts else None,
        "building_to_lot_ratio_range": [min(bld_ratios), max(bld_ratios)] if bld_ratios else None,
        "low_density_count": len(low_density),
        "per_unit_mismatch_count": len(per_unit_mismatch),
        "clean_results_count": len(clean_results),
        "data_quality_warnings": data_quality_warnings,
        "zoning_classes": zones,
        "neighborhoods": neighborhoods,
        "property_ids": {r["id"]: r.get("address") for r in results if r.get("id")},
    }


def compute_development_facts(data: dict) -> dict:
    """Facts for ``get_development_potential`` results."""
    adu = data.get("adu") or {}
    sb9 = data.get("sb9") or {}
    units = data.get("units") or {}
    zoning = data.get("zoning") or {}

    return {
        "zone_class": zoning.get("zone_class"),
        "zone_desc": zoning.get("zone_desc"),
        "adu_eligible": bool(adu.get("eligible")),
        "adu_max_sqft": adu.get("max_adu_sqft"),
        "sb9_eligible": bool(sb9.get("eligible")),
        "sb9_can_split": bool(sb9.get("can_split")),
        "sb9_max_units": sb9.get("max_total_units"),
        "effective_max_units": units.get("effective_max_units"),
        "middle_housing_eligible": bool(units.get("middle_housing_eligible")),
    }


def compute_prediction_facts(data: dict) -> dict:
    """Facts for ``get_price_prediction`` results."""
    return {
        "predicted_price": data.get("predicted_price"),
        "price_lower": data.get("price_lower"),
        "price_upper": data.get("price_upper"),
        "confidence_pct": data.get("confidence_pct"),
        "neighborhood": data.get("neighborhood"),
    }


def compute_comps_facts(data: dict | list) -> dict:
    """Facts for ``get_comparable_sales`` results.

    The tool returns a list of comp dicts (or a dict with ``comps`` key from
    precomputed cache).
    """
    comps = data if isinstance(data, list) else (data.get("comps") or [])
    n = len(comps)
    prices = [c["sale_price"] for c in comps if c.get("sale_price")]
    sqfts = [c["price_per_sqft"] for c in comps if c.get("price_per_sqft")]

    return {
        "comp_count": n,
        "price_range": [min(prices), max(prices)] if prices else None,
        "median_price": int(median(prices)) if prices else None,
        "median_price_per_sqft": int(median(sqfts)) if sqfts else None,
    }


def compute_neighborhood_facts(data: dict) -> dict:
    """Facts for ``get_neighborhood_stats`` results."""
    return {
        "neighborhood": data.get("neighborhood"),
        "median_price": data.get("median_price"),
        "total_sales": data.get("total_sales"),
        "yoy_price_change_pct": data.get("yoy_price_change_pct"),
        "avg_dom": data.get("avg_dom"),
        "active_listings": data.get("active_listings"),
    }


def compute_sell_vs_hold_facts(data: dict) -> dict:
    """Facts for ``estimate_sell_vs_hold`` results."""
    rental = data.get("rental_estimate") or {}
    scenarios = data.get("hold_scenarios") or {}

    facts: dict = {
        "current_value": data.get("current_predicted_value"),
        "yoy_appreciation_pct": data.get("yoy_appreciation_pct"),
        "monthly_rent": rental.get("monthly_rent"),
        "cap_rate_pct": rental.get("cap_rate_pct"),
        "price_to_rent_ratio": rental.get("price_to_rent_ratio"),
    }
    # Summarise hold horizons
    for horizon, s in scenarios.items():
        facts[f"{horizon}_projected"] = s.get("projected_value")
        facts[f"{horizon}_net_gain"] = s.get("net_gain")

    return facts


def compute_rental_facts(data: dict) -> dict:
    """Facts for ``estimate_rental_income`` results."""
    return {
        "scenario_name": data.get("scenario_name"),
        "monthly_rent": data.get("monthly_rent"),
        "annual_gross_rent": data.get("annual_gross_rent"),
        "annual_noi": data.get("annual_noi"),
        "cap_rate_pct": data.get("cap_rate_pct"),
        "cash_on_cash_pct": data.get("cash_on_cash_pct"),
        "monthly_cash_flow": data.get("monthly_cash_flow"),
    }


def compute_investment_facts(data: dict) -> dict:
    """Facts for ``analyze_investment_scenarios`` results."""
    scenarios = data.get("scenarios") or []

    summaries = []
    best_roi = None
    for s in scenarios:
        summary = {
            "name": s.get("scenario_name"),
            "cap_rate_pct": s.get("cap_rate_pct"),
            "cash_on_cash_pct": s.get("cash_on_cash_pct"),
            "monthly_cash_flow": s.get("monthly_cash_flow"),
        }
        summaries.append(summary)
        coc = s.get("cash_on_cash_pct") or 0
        if best_roi is None or coc > best_roi.get("cash_on_cash_pct", 0):
            best_roi = summary

    return {
        "scenario_count": len(scenarios),
        "scenarios": summaries,
        "best_cash_on_cash": best_roi,
    }


def compute_improvement_facts(data: dict) -> dict:
    """Facts for ``get_improvement_simulation`` results."""
    categories = data.get("categories") or []
    top_by_roi = sorted(
        [c for c in categories if c.get("roi") is not None],
        key=lambda c: c["roi"],
        reverse=True,
    )

    return {
        "current_price": data.get("current_price"),
        "improved_price": data.get("improved_price"),
        "total_delta": data.get("total_delta"),
        "total_cost": data.get("total_cost"),
        "overall_roi": data.get("roi"),
        "top_improvements": [
            {"category": c["category"], "cost": c.get("avg_cost"), "roi": c["roi"]}
            for c in top_by_roi[:3]
        ],
    }


def compute_undo_filter_facts(data: dict) -> dict:
    """Facts for ``undo_filter`` results."""
    return {
        "working_set_count": data.get("working_set_count"),
        "removed_filter": data.get("removed_filter"),
        "remaining_filters": data.get("remaining_filters"),
    }


def compute_query_facts(data: dict) -> dict:
    """Facts for ``query_database`` results."""
    rows = data.get("rows") or []
    columns = data.get("columns") or []

    facts: dict = {
        "row_count": len(rows),
        "columns": columns,
    }

    # For single-row aggregate results, surface the values directly
    if len(rows) == 1 and len(columns) <= 5:
        facts["result"] = rows[0]

    return facts


def compute_regulation_facts(data: dict) -> dict:
    """Facts for ``lookup_regulation`` results."""
    found = data.get("category") is not None
    facts: dict = {
        "found": found,
        "category": data.get("category", ""),
        "title": data.get("title", ""),
    }
    if data.get("source"):
        facts["source"] = data["source"]
    if data.get("zone"):
        # Extract zone code from zone dict (single key)
        zone_codes = list(data["zone"].keys())
        if zone_codes:
            facts["zone_code"] = zone_codes[0]
    if data.get("key_numbers"):
        facts["key_numbers"] = data["key_numbers"]
    if data.get("related"):
        facts["related_categories"] = data["related"]
    if not found and data.get("available_categories"):
        facts["available_categories"] = data["available_categories"]
    return facts


def compute_glossary_facts(data: dict) -> dict:
    """Facts for ``lookup_glossary_term`` results."""
    found = data.get("term_key") is not None
    facts: dict = {
        "found": found,
        "term_key": data.get("term_key", ""),
        "term": data.get("term", ""),
        "category": data.get("category", ""),
    }
    if data.get("formula"):
        facts["has_formula"] = True
        facts["formula"] = data["formula"]
    if data.get("key_numbers"):
        facts["key_numbers"] = data["key_numbers"]
    if data.get("related"):
        facts["related_terms"] = data["related"]
    if data.get("source"):
        facts["source"] = data["source"]
    # Category browsing result
    if data.get("terms"):
        facts["total_in_category"] = data.get("total", len(data["terms"]))
        facts["term_keys"] = [t["term_key"] for t in data["terms"]]
    # Not found hints
    if not found and data.get("available_categories"):
        facts["available_categories"] = data["available_categories"]
    return facts


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_FACT_COMPUTERS: dict[str, callable] = {
    "search_properties": compute_search_facts,
    "get_development_potential": compute_development_facts,
    "get_price_prediction": compute_prediction_facts,
    "get_comparable_sales": compute_comps_facts,
    "get_neighborhood_stats": compute_neighborhood_facts,
    "estimate_sell_vs_hold": compute_sell_vs_hold_facts,
    "estimate_rental_income": compute_rental_facts,
    "analyze_investment_scenarios": compute_investment_facts,
    "get_improvement_simulation": compute_improvement_facts,
    "query_database": compute_query_facts,
    "undo_filter": compute_undo_filter_facts,
    "lookup_regulation": compute_regulation_facts,
    "lookup_glossary_term": compute_glossary_facts,
}


def compute_facts_for_tool(tool_name: str, result_data: dict | list) -> Optional[dict]:
    """Compute verified facts for a tool result.

    Returns ``None`` for tools that don't need fact enrichment
    (``lookup_property``, ``lookup_permits``, ``get_market_summary``).
    """
    computer = _FACT_COMPUTERS.get(tool_name)
    if not computer:
        return None
    try:
        return computer(result_data)
    except Exception:
        logger.warning("Fact computation failed for %s", tool_name, exc_info=True)
        return None
