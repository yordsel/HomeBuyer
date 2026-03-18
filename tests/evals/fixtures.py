"""Realistic tool result fixtures for orchestrator evals.

Returns plausible Berkeley market data so Sonnet can produce data-grounded
responses instead of hallucinating around ``{"result": "mock data"}``.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Per-tool realistic results
# ---------------------------------------------------------------------------

_MARKET_SUMMARY = {
    "current_market": {
        "median_sale_price": 1300000,
        "avg_price": 1425000,
        "median_ppsf": 892,
        "sale_count_recent": 23,
        "monthly_sales_rate": 23,
        "median_dom": 18,
        "percent_above_asking": 61,
        "median_above_asking_pct": 18.4,
        "mortgage_rate_30yr": 6.15,
        "inventory_months": 0.9,
    },
    "neighborhood_rankings": [
        {"name": "Elmwood", "rank": 1, "median_price": 1750000, "yoy_change_pct": 4.2, "sale_count": 15},
        {"name": "North Berkeley", "rank": 2, "median_price": 1500000, "yoy_change_pct": 0.7, "sale_count": 45},
        {"name": "Thousand Oaks", "rank": 3, "median_price": 1400000, "yoy_change_pct": 3.1, "sale_count": 18},
        {"name": "South Berkeley", "rank": 4, "median_price": 950000, "yoy_change_pct": -1.5, "sale_count": 32},
        {"name": "West Berkeley", "rank": 5, "median_price": 875000, "yoy_change_pct": 2.0, "sale_count": 20},
    ],
    "rate_sensitivity": {
        "median_price": 1300000,
        "mortgage_rate_30yr": 6.15,
        "scenarios": [
            {"down_payment_pct": 20.0, "down_payment_amount": 260000, "loan_amount": 1040000, "monthly_pi": 6282, "monthly_piti_estimate": 7853, "income_required_28pct_dti": 336464},
            {"down_payment_pct": 10.0, "down_payment_amount": 130000, "loan_amount": 1170000, "monthly_pi": 7068, "monthly_piti_estimate": 8835, "income_required_28pct_dti": 379071},
            {"down_payment_pct": 5.0, "down_payment_amount": 65000, "loan_amount": 1235000, "monthly_pi": 7461, "monthly_piti_estimate": 9326, "income_required_28pct_dti": 399514},
        ],
    },
}

_LOOKUP_PROPERTY = {
    "id": 4521,
    "address": "1234 Cedar St",
    "neighborhood": "Live Oak Park",
    "zip_code": "94705",
    "zoning_class": "R-1",
    "lot_size_sqft": 4200,
    "building_sqft": 2868,
    "beds": 4,
    "baths": 3,
    "sqft": 2868,
    "year_built": 1896,
    "property_type": "Single Family Residential",
    "last_sale_price": 1150000,
    "last_sale_date": "2022-05-15",
    "latitude": 37.8715,
    "longitude": -122.2738,
}

_PRICE_PREDICTION = {
    "predicted_price": 1180000,
    "price_lower": 950000,
    "price_upper": 1450000,
    "neighborhood": "Live Oak Park",
    "predicted_premium_pct": 2.6,
    "base_value": 1100000,
    "feature_contributions": {
        "sqft": 85000, "beds": 42000, "baths": 28000, "year_built": -15000,
        "lot_size_sqft": 12000, "neighborhood": 52000,
    },
    "top_value_drivers": [
        {"feature": "sqft", "label": "Living area", "impact": 85000, "direction": "increases"},
        {"feature": "neighborhood", "label": "Neighborhood", "impact": 52000, "direction": "increases"},
    ],
}

_COMPARABLE_SALES = [
    {"address": "1247 Cedar St", "sale_date": "2024-11-20", "sale_price": 1195000, "beds": 4, "baths": 3, "sqft": 2850, "neighborhood": "Live Oak Park", "price_per_sqft": 419, "similarity_score": 0.94},
    {"address": "1523 Spruce St", "sale_date": "2024-10-15", "sale_price": 1225000, "beds": 4, "baths": 2.5, "sqft": 2920, "neighborhood": "Live Oak Park", "price_per_sqft": 420, "similarity_score": 0.87},
    {"address": "1180 Euclid Ave", "sale_date": "2024-09-08", "sale_price": 1140000, "beds": 3, "baths": 2, "sqft": 2400, "neighborhood": "North Berkeley", "price_per_sqft": 475, "similarity_score": 0.82},
]

_NEIGHBORHOOD_STATS = {
    "name": "North Berkeley",
    "sale_count": 45,
    "median_price": 1500000,
    "avg_price": 1523000,
    "min_price": 850000,
    "max_price": 2850000,
    "median_ppsf": 958,
    "median_sqft": 1564,
    "avg_year_built": 1952,
    "yoy_price_change_pct": 0.7,
    "median_lot_size": 5200,
    "property_type_breakdown": {"Single Family Residential": 0.87, "Condo": 0.10, "Townhouse": 0.03},
}

_RENTAL_INCOME = {
    "scenario_name": "Rent As-Is",
    "property_address": "1234 Cedar St",
    "property_value": 1180000,
    "monthly_rent": 4250,
    "annual_rent": 51000,
    "monthly_expenses": {"property_tax": 1229, "insurance": 450, "maintenance": 1475, "property_management": 425, "vacancy_allowance": 425},
    "total_monthly_expenses": 4004,
    "annual_expenses": 48048,
    "annual_net_income": 2952,
    "cap_rate_pct": 0.25,
    "price_to_rent_ratio": 23.1,
    "estimation_method": "comparable_analysis",
}

_SEARCH_PROPERTIES = {
    "results": [
        {"id": 4521, "address": "2736 Webster St", "neighborhood": "Elmwood", "beds": 3, "baths": 2.5, "sqft": 2207, "lot_size_sqft": 6075, "year_built": 1958, "last_sale_price": 1850000, "predicted_price": 1921000, "estimated_monthly_cost": 13245, "development": {"adu_eligible": True, "sb9_eligible": True}},
        {"id": 4522, "address": "1890 Arch St", "neighborhood": "North Berkeley", "beds": 4, "baths": 2, "sqft": 1850, "lot_size_sqft": 5400, "year_built": 1942, "last_sale_price": 1350000, "predicted_price": 1410000, "estimated_monthly_cost": 9720, "development": {"adu_eligible": True, "sb9_eligible": True}},
    ],
    "total_found": 2,
    "total_matching": 18,
}

_TRUE_COST = {
    "purchase_price": 1100000,
    "down_payment_pct": 20.0,
    "down_payment_amount": 220000,
    "loan_amount": 880000,
    "mortgage_rate": 6.15,
    "monthly_principal_and_interest": 5346,
    "monthly_property_tax": 1146,
    "monthly_hoi": 322,
    "monthly_earthquake_insurance": 183,
    "monthly_maintenance_reserve": 1375,
    "monthly_pmi": 0,
    "monthly_hoa": 0,
    "total_monthly_cost": 8372,
    "current_rent": 3500,
    "monthly_delta_vs_rent": 4872,
    "delta_direction": "more_than_rent",
}

_PMI_MODEL = {
    "purchase_price": 1200000,
    "down_payment_pct": 10.0,
    "down_payment_amount": 120000,
    "loan_amount": 1080000,
    "mortgage_rate": 6.15,
    "initial_ltv_pct": 90.0,
    "pmi_applicable": True,
    "current_pmi_rate_pct": 1.1,
    "monthly_pmi": 990,
    "annual_pmi": 11880,
    "pmi_dropoff_month": 34,
    "pmi_dropoff_years": 2.8,
    "pmi_dropoff_description": "PMI drops after 2y 10m",
    "total_pmi_cost": 26874,
}

_DEVELOPMENT_POTENTIAL = {
    "address": "2736 Webster St",
    "zoning_class": "R-2",
    "zoning_description": "Residential - Low Density",
    "adu_eligible": True,
    "adu_max_sqft": 1093,
    "sb9_eligible": True,
    "sb9_can_split": True,
    "sb9_max_units": 2,
    "lot_size_sqft": 6075,
    "building_sqft": 2207,
    "far_used": 0.363,
    "remaining_buildable_sqft": 3868,
}

_APPRECIATION_STRESS = {
    "purchase_price": 1400000,
    "down_payment_pct": 20.0,
    "scenarios": [
        {"label": "Bear (-15%)", "price_change_pct": -15, "new_value": 1190000, "equity": 70000, "ltv": 0.93, "underwater": False},
        {"label": "Flat (0%)", "price_change_pct": 0, "new_value": 1400000, "equity": 280000, "ltv": 0.80, "underwater": False},
        {"label": "Bull (+10%)", "price_change_pct": 10, "new_value": 1540000, "equity": 420000, "ltv": 0.73, "underwater": False},
    ],
}

_QUERY_DATABASE = {
    "columns": ["address", "sale_price", "beds", "baths", "sqft", "neighborhood"],
    "rows": [
        ["1234 Cedar St", 1150000, 4, 3, 2868, "Live Oak Park"],
        ["456 Elm St", 980000, 3, 2, 1800, "South Berkeley"],
    ],
    "row_count": 2,
}

# ---------------------------------------------------------------------------
# Lookup: tool name → realistic result
# ---------------------------------------------------------------------------

TOOL_RESULTS: dict[str, dict | list] = {
    "get_market_summary": _MARKET_SUMMARY,
    "lookup_property": _LOOKUP_PROPERTY,
    "get_price_prediction": _PRICE_PREDICTION,
    "get_comparable_sales": _COMPARABLE_SALES,
    "get_neighborhood_stats": _NEIGHBORHOOD_STATS,
    "estimate_rental_income": _RENTAL_INCOME,
    "search_properties": _SEARCH_PROPERTIES,
    "compute_true_cost": _TRUE_COST,
    "pmi_model": _PMI_MODEL,
    "get_development_potential": _DEVELOPMENT_POTENTIAL,
    "appreciation_stress_test": _APPRECIATION_STRESS,
    "query_database": _QUERY_DATABASE,
}


def realistic_tool_result(tool_name: str, tool_input: dict | None = None) -> str:
    """Return a realistic JSON string result for the given tool name.

    Falls back to a generic success result for unknown tools.
    """
    data = TOOL_RESULTS.get(tool_name, {"result": "ok", "tool": tool_name})
    return json.dumps(data)
