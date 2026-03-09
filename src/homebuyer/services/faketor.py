"""Faketor — AI real estate advisor chat powered by Claude with tool use.

Faketor uses Claude's tool-use capability to call existing HomeBuyer APIs
(development potential, improvement simulation, comps, market data, neighborhood
stats) and synthesize property-specific recommendations including sell-vs-hold
analysis.
"""

import json
import logging
from typing import Optional

from homebuyer.config import ANTHROPIC_API_KEY
from homebuyer.services.accumulator import AnalysisAccumulator
from homebuyer.services.facts import compute_facts_for_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions for Claude
# ---------------------------------------------------------------------------

FAKETOR_TOOLS = [
    {
        "name": "lookup_property",
        "description": (
            "Look up a Berkeley property by address. Returns property details "
            "from the citywide database including beds, baths, sqft, year built, "
            "lot size, zoning, neighborhood, and last sale info. Use this when "
            "the user mentions a specific address or asks about a property you "
            "don't already have context for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Street address to search for (e.g. '1234 Cedar St')",
                },
            },
            "required": ["address"],
        },
    },
    {
        "name": "get_development_potential",
        "description": (
            "Get zoning details, ADU feasibility, Middle Housing eligibility, "
            "SB 9 lot-split eligibility, and BESO energy status for a Berkeley property. "
            "Use this when the user asks about what can be built on the property, "
            "zoning rules, adding units, or development upside. "
            "IMPORTANT: When following up on search_properties results, always pass "
            "the property_id from the search results to ensure the correct property "
            "is looked up (not a nearby neighbor)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Property latitude"},
                "longitude": {"type": "number", "description": "Property longitude"},
                "address": {"type": "string", "description": "Street address"},
                "property_id": {
                    "type": "integer",
                    "description": (
                        "Database property ID from search_properties results. "
                        "When available, this ensures the exact property is looked up "
                        "instead of relying on lat/lon proximity matching."
                    ),
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_improvement_simulation",
        "description": (
            "Simulate the effect of home improvements (kitchen, bathroom, ADU, solar, etc.) "
            "on predicted property value using the ML model. Returns per-category cost, "
            "predicted value delta, ROI, and market correlation data. "
            "Use this when the user asks about renovations, improvements, ROI on upgrades, "
            "or what improvements are worth doing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "address": {"type": "string"},
                "neighborhood": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_comparable_sales",
        "description": (
            "Find recent comparable property sales in the same neighborhood. "
            "Returns sale prices, dates, and property details for similar homes. "
            "Use this when the user asks about recent sales, what similar homes sold for, "
            "or market comps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "neighborhood": {"type": "string", "description": "Berkeley neighborhood name"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
            },
            "required": ["neighborhood"],
        },
    },
    {
        "name": "get_neighborhood_stats",
        "description": (
            "Get neighborhood-level statistics: median/avg price, price per sqft, "
            "year-over-year price change, sale count, dominant zoning, property types. "
            "Use this when the user asks about a neighborhood's market, price trends, "
            "or how the area compares."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "neighborhood": {"type": "string", "description": "Berkeley neighborhood name"},
                "years": {"type": "integer", "description": "Lookback years (default 2)"},
            },
            "required": ["neighborhood"],
        },
    },
    {
        "name": "get_market_summary",
        "description": (
            "Get Berkeley-wide market summary: current median prices, sale-to-list ratio, "
            "days on market, mortgage rates, inventory, price distribution, "
            "top neighborhoods by price. Use this when the user asks about the "
            "overall Berkeley market, trends, or timing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_price_prediction",
        "description": (
            "Get the ML model's predicted sale price for the property, including "
            "confidence interval and feature contributions. Use this when the user "
            "asks what the property is worth, its estimated value, or wants a price opinion."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "neighborhood": {"type": "string"},
                "zip_code": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
                "lot_size_sqft": {"type": "integer"},
                "property_type": {"type": "string"},
            },
            "required": ["latitude", "longitude", "neighborhood"],
        },
    },
    {
        "name": "estimate_sell_vs_hold",
        "description": (
            "Estimate whether to sell now or hold the property for 1, 3, or 5 years. "
            "Uses the ML price prediction, neighborhood year-over-year appreciation, "
            "and market conditions to project future value. Also estimates rough rental "
            "yield based on Berkeley price-to-rent ratios. "
            "Use this when the user asks about selling vs renting, hold period, "
            "investment timeline, or whether to sell now. "
            "When the user says they OWN the property, pass purchase_price, purchase_date, "
            "and mortgage_rate so numbers reflect their actual financial position."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "neighborhood": {"type": "string"},
                "zip_code": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
                "lot_size_sqft": {"type": "integer"},
                "property_type": {"type": "string"},
                "purchase_price": {
                    "type": "number",
                    "description": "Price the owner paid for the property (for mortgage/expense/ROI calculations).",
                },
                "purchase_date": {
                    "type": "string",
                    "description": "When the owner purchased, YYYY-MM-DD format (for holding period ROI).",
                },
                "mortgage_rate": {
                    "type": "number",
                    "description": "Owner's actual mortgage rate, e.g. 3.25 (overrides current market rate).",
                },
                "current_value_override": {
                    "type": "number",
                    "description": "Override ML prediction with user-stated or appraised current value.",
                },
            },
            "required": ["latitude", "longitude", "neighborhood"],
        },
    },
    {
        "name": "estimate_rental_income",
        "description": (
            "Estimate rental income for a Berkeley property. Returns monthly/annual "
            "rent estimates, itemized operating expenses, mortgage analysis, cap rate, "
            "cash-on-cash return, and cash flow projections for a rent-as-is scenario. "
            "Use this when the user asks about rental income, what the property could "
            "rent for, monthly rent estimates, or landlord cash flow. "
            "When the user says they OWN the property, pass purchase_price, purchase_date, "
            "and mortgage_rate so expenses and mortgage reflect their actual costs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "neighborhood": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
                "lot_size_sqft": {"type": "integer"},
                "property_type": {"type": "string"},
                "down_payment_pct": {
                    "type": "number",
                    "description": "Down payment percentage (default 20)",
                },
                "purchase_price": {
                    "type": "number",
                    "description": "Price the owner paid for the property (for mortgage/expense/ROI calculations).",
                },
                "purchase_date": {
                    "type": "string",
                    "description": "When the owner purchased, YYYY-MM-DD format.",
                },
                "mortgage_rate": {
                    "type": "number",
                    "description": "Owner's actual mortgage rate, e.g. 3.25 (overrides current market rate).",
                },
                "current_value_override": {
                    "type": "number",
                    "description": "Override ML prediction with user-stated or appraised current value.",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "analyze_investment_scenarios",
        "description": (
            "Run comprehensive investment scenario analysis comparing multiple "
            "strategies: rent as-is, add ADU, SB9 lot split, and multi-unit "
            "development. For each applicable scenario, provides cash flow "
            "projections over 1-20 years, mortgage analysis, tax benefits "
            "(depreciation, interest deduction), and key metrics (cap rate, "
            "cash-on-cash return, equity buildup). Integrates with development "
            "potential data for ADU feasibility and SB9 eligibility. "
            "Use this when the user asks about investment analysis, best scenario, "
            "ROI of adding an ADU vs renting as-is, development returns, or "
            "long-term investment comparison. "
            "When the user says they OWN the property, pass purchase_price, purchase_date, "
            "and mortgage_rate so all scenarios reflect their actual financial position."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "neighborhood": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
                "lot_size_sqft": {"type": "integer"},
                "property_type": {"type": "string"},
                "down_payment_pct": {
                    "type": "number",
                    "description": "Down payment percentage (default 20)",
                },
                "self_managed": {
                    "type": "boolean",
                    "description": "Whether owner self-manages (no mgmt fee). Default true.",
                },
                "purchase_price": {
                    "type": "number",
                    "description": "Price the owner paid for the property (for mortgage/expense/ROI calculations).",
                },
                "purchase_date": {
                    "type": "string",
                    "description": "When the owner purchased, YYYY-MM-DD format.",
                },
                "mortgage_rate": {
                    "type": "number",
                    "description": "Owner's actual mortgage rate, e.g. 3.25 (overrides current market rate).",
                },
                "current_value_override": {
                    "type": "number",
                    "description": "Override ML prediction with user-stated or appraised current value.",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "search_properties",
        "description": (
            "Search Berkeley properties by criteria to find development opportunities. "
            "Returns multiple properties with development potential summaries (ADU eligibility, "
            "SB9 lot split eligibility, max units, zoning), data quality flags, and pre-computed "
            "building-to-lot ratios. Use this when the user wants to find properties matching "
            "criteria (e.g. 'find R-1 properties with large lots in North Berkeley'), compare "
            "development opportunities, or search for investment targets. Do NOT use this for "
            "looking up a single known address — use lookup_property instead.\n\n"
            "Results are capped at 25 properties. The response includes total_matching — the "
            "true count of all matching properties. When total_matching > results returned, use "
            "query_database to run aggregate analysis (counts, averages, distributions) across "
            "ALL matching properties, or to retrieve additional properties with custom SQL. "
            "The search results populate the session working set for follow-up queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "neighborhoods": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Filter by neighborhood name(s). Examples: 'North Berkeley', "
                        "'Elmwood', 'Thousand Oaks', 'West Berkeley', 'Berkeley Hills', "
                        "'Claremont', 'Central Berkeley', 'Cragmont', 'Northbrae', etc."
                    ),
                },
                "zoning_classes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Filter by exact zoning class(es). E.g. ['R-1', 'R-2']. "
                        "Common residential: R-1, R-1H, R-2, R-2A, R-2AH, R-2H, "
                        "R-3, R-3H, R-4, R-4H, ES-R, MU-R."
                    ),
                },
                "zoning_pattern": {
                    "type": "string",
                    "description": (
                        "SQL LIKE pattern for zoning class. E.g. 'R-2%' matches "
                        "R-2, R-2A, R-2AH, R-2H. Use instead of zoning_classes "
                        "for category matching."
                    ),
                },
                "property_type": {
                    "type": "string",
                    "description": (
                        "Filter by property type. E.g. 'Single Family Residential', "
                        "'Multi-Family (2-4 Unit)', 'Condo/Co-op'."
                    ),
                },
                "property_category": {
                    "type": "string",
                    "description": (
                        "Filter by property category from use code reference. "
                        "Values: 'sfr', 'duplex', 'triplex', 'fourplex', 'apartment', "
                        "'condo', 'townhouse', 'pud', 'coop', 'land', 'mixed_use'. "
                        "More granular than property_type."
                    ),
                },
                "record_type": {
                    "type": "string",
                    "description": (
                        "Filter by record type: 'lot' (physical lot — SFR, apartments, "
                        "duplexes) or 'unit' (sellable unit within a lot — condos, co-ops). "
                        "Use 'lot' to exclude individual condo units from development searches."
                    ),
                },
                "ownership_type": {
                    "type": "string",
                    "description": (
                        "Filter by ownership type: 'fee_simple' (SFR, apartments), "
                        "'common_interest' (condos, PUDs), 'cooperative' (co-ops)."
                    ),
                },
                "min_price": {
                    "type": "integer",
                    "description": "Minimum last sale price (e.g. 500000)",
                },
                "max_price": {
                    "type": "integer",
                    "description": "Maximum last sale price (e.g. 1500000)",
                },
                "min_beds": {"type": "number", "description": "Minimum bedrooms"},
                "max_beds": {"type": "number", "description": "Maximum bedrooms"},
                "min_baths": {"type": "number", "description": "Minimum bathrooms"},
                "max_baths": {"type": "number", "description": "Maximum bathrooms"},
                "min_lot_sqft": {
                    "type": "integer",
                    "description": "Minimum lot size in sqft (e.g. 5000)",
                },
                "max_lot_sqft": {
                    "type": "integer",
                    "description": "Maximum lot size in sqft",
                },
                "min_sqft": {
                    "type": "integer",
                    "description": (
                        "Minimum per-unit living area sqft (MLS/assessor). "
                        "For building footprint filtering, use query_database with building_sqft."
                    ),
                },
                "max_sqft": {
                    "type": "integer",
                    "description": "Maximum per-unit living area sqft",
                },
                "min_year_built": {
                    "type": "integer",
                    "description": "Minimum year built (e.g. 1950)",
                },
                "max_year_built": {
                    "type": "integer",
                    "description": "Maximum year built",
                },
                "adu_eligible": {
                    "type": "boolean",
                    "description": "If true, only include properties eligible for ADU construction",
                },
                "sb9_eligible": {
                    "type": "boolean",
                    "description": "If true, only include properties eligible for SB9 lot split",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 10, max 25)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "lookup_permits",
        "description": (
            "Look up building permits filed for a specific Berkeley property address. "
            "Returns permit history including permit type, status, description, job value, "
            "filing date, and construction type. Use this when the user asks about permit "
            "history, renovations, construction activity, or improvements done on a property."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": (
                        "The property address to look up permits for. "
                        "Should be the full street address as stored in the database "
                        "(e.g. '2822 BENVENUE AVE BERKELEY 94705')."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max permits to return (default 20)",
                },
            },
            "required": ["address"],
        },
    },
    {
        "name": "undo_filter",
        "description": (
            "Undo the most recent filter applied to the session property working set, "
            "restoring the previous set of properties. Use this when the user says things "
            "like 'go back', 'undo that', 'remove the last filter', 'show me all of them again', "
            "or 'what were the results before I filtered?'. Only works when there is an active "
            "filter stack (i.e. the working set has been narrowed by a previous query)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "query_database",
        "description": (
            "Execute a read-only SQL query against the Berkeley property database to answer "
            "analytical, aggregate, or ad-hoc questions that the other tools can't handle. "
            "Use this for questions like 'how many properties have X?', 'what is the average Y?', "
            "'which neighborhoods have the most Z?', or any counting/filtering/grouping question.\n\n"
            "AVAILABLE TABLES AND COLUMNS:\n\n"
            "properties — 17,000+ Berkeley parcels (primary table for most queries):\n"
            "  id, apn, address, street_number, street_name, zip_code, latitude, longitude,\n"
            "  lot_size_sqft, building_sqft, use_code, use_description, neighborhood, zoning_class,\n"
            "  beds (REAL), baths (REAL), sqft, year_built, property_type, last_sale_date, last_sale_price,\n"
            "  situs_unit, property_category, ownership_type, record_type, lot_group_key, parcel_lot_size_sqft\n\n"
            "DATA MODEL COLUMNS:\n"
            "- property_category: Granular type from use code reference — 'sfr', 'duplex', 'triplex', "
            "'fourplex', 'apartment', 'condo', 'townhouse', 'pud', 'coop', 'land', 'mixed_use'\n"
            "- record_type: 'lot' (physical lot — SFR, apartments, duplexes) or 'unit' "
            "(sellable unit within a lot — condos, co-ops). Condos have individual APNs per unit.\n"
            "- ownership_type: 'fee_simple', 'common_interest' (condos, PUDs), or 'cooperative'\n"
            "- lot_group_key: Grouping key for condo units sharing the same physical lot "
            "(format: STREETNUMBER_STREETNAME_ZIP). Use to aggregate condo units by lot.\n"
            "- situs_unit: Unit identifier (A, B, C, etc.) for condo units\n"
            "- parcel_lot_size_sqft: Raw lot size from assessor (before any corrections)\n\n"
            "use_codes — Reference table for Alameda County use codes:\n"
            "  use_code, description, property_category, ownership_type, record_type,\n"
            "  estimated_units, is_residential, lot_size_meaning, building_ar_meaning\n\n"
            "IMPORTANT COLUMN NOTES:\n"
            "- sqft: Per-unit living area from MLS/assessor. For condos and MF 5+, this is ONE unit's sqft.\n"
            "- building_sqft: Total building footprint from assessor (entire structure).\n"
            "- For single-family homes, sqft ≈ building_sqft. For multi-unit properties, building_sqft >> sqft.\n"
            "- When computing building density or building-to-lot ratios, ALWAYS use building_sqft, NOT sqft.\n"
            "- For condos (record_type='unit'), lot_size_sqft is the SHARED lot for all units — "
            "use lot_group_key to find sibling units and divide lot_size by unit count.\n"
            "- ~232 multi-family 5+ properties have per-unit sqft/beds/baths but whole-building lot_size_sqft "
            "and last_sale_price. Identify them with: building_sqft / NULLIF(sqft, 0) > 3\n\n"
            "property_sales — historical sale transactions:\n"
            "  id, mls_number, address, city, zip_code, sale_date, sale_price, sale_type,\n"
            "  property_type, beds, baths, sqft, lot_size_sqft, year_built, price_per_sqft,\n"
            "  hoa_per_month, latitude, longitude, neighborhood, zoning_class, days_on_market\n\n"
            "building_permits — permit history:\n"
            "  id, record_number, permit_type, status, address, zip_code, parcel_id,\n"
            "  description, job_value, construction_type, filed_date\n\n"
            "neighborhoods — neighborhood reference:\n"
            "  id, name, aliases, centroid_lat, centroid_lon, area_sqmi\n\n"
            "market_metrics — market trends:\n"
            "  period_begin, period_end, median_sale_price, median_list_price, median_ppsf,\n"
            "  homes_sold, new_listings, inventory, months_of_supply, median_dom, avg_sale_to_list\n\n"
            "COMMON property_type VALUES: 'Single Family Residential', 'Multi-Family (2-4 Unit)', "
            "'Condo/Co-op', 'Townhouse', 'Multi-Family (5+ Unit)', 'Land', 'Manufactured'\n\n"
            "RULES:\n"
            "- Only SELECT statements are allowed (no INSERT, UPDATE, DELETE, DROP, etc.)\n"
            "- Use LIMIT to cap results (max 100 rows returned)\n"
            "- For counting/aggregation queries, always use COUNT, SUM, AVG, MIN, MAX, GROUP BY\n"
            "- Column values are case-sensitive — use exact values from the list above\n"
            "- Use IS NOT NULL to filter out missing data when needed\n\n"
            "WORKING SET:\n"
            "When a session working set is active, a temporary table _working_set is available with column:\n"
            "  property_id INTEGER\n"
            "Use JOIN _working_set ws ON p.id = ws.property_id to restrict queries to the current set.\n"
            "The working set contains property IDs from the most recent search_properties or filtered results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": (
                        "The SQL SELECT query to execute. Must be a single SELECT statement. "
                        "Examples:\n"
                        "- SELECT COUNT(*) as count FROM properties WHERE property_type = 'Single Family Residential' AND lot_size_sqft > 7000\n"
                        "- SELECT neighborhood, COUNT(*) as count FROM properties GROUP BY neighborhood ORDER BY count DESC LIMIT 10\n"
                        "- SELECT AVG(last_sale_price) as avg_price, neighborhood FROM properties WHERE last_sale_price IS NOT NULL GROUP BY neighborhood"
                    ),
                },
                "explanation": {
                    "type": "string",
                    "description": "Brief explanation of what the query does (for logging/audit)",
                },
            },
            "required": ["sql"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool name → block type mapping for structured response blocks
# ---------------------------------------------------------------------------

TOOL_TO_BLOCK_TYPE: dict[str, str] = {
    "lookup_property": "property_detail",
    "get_price_prediction": "prediction_card",
    "get_comparable_sales": "comps_table",
    "get_neighborhood_stats": "neighborhood_stats",
    "get_development_potential": "development_potential",
    "get_improvement_simulation": "improvement_sim",
    "estimate_sell_vs_hold": "sell_vs_hold",
    "estimate_rental_income": "rental_income",
    "analyze_investment_scenarios": "investment_scenarios",
    "get_market_summary": "market_summary",
    "search_properties": "property_search_results",
    "query_database": "query_result",
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Faketor, a witty and knowledgeable Berkeley real estate advisor AI. \
You help home buyers evaluate properties in Berkeley, California by pulling real data from \
the HomeBuyer analysis platform.

PERSONALITY:
- Friendly but direct — give clear opinions backed by data
- Sprinkle in light humor when appropriate (you're a "Faketor" after all)
- Use plain language, not jargon
- When you don't have data, say so honestly

CAPABILITIES (use your tools!):
- Property lookup: search any Berkeley property by address (17,000+ parcels in our database)
- Property search: find properties by neighborhood, zoning, lot size, price, beds/baths, \
  year built, ADU eligibility, or SB9 eligibility — compare development opportunities across \
  multiple properties at once
- Development potential: zoning, ADU, Middle Housing, SB 9 lot splitting
- Improvement ROI: ML-simulated value impact of renovations
- Comparable sales and neighborhood statistics
- Market-wide trends, mortgage rates, inventory
- Price prediction from the ML model
- Sell-vs-hold analysis with appreciation projections and rental yield estimates
- Rental income estimation with data-driven rent estimates and expense modeling
- Investment scenario comparison (as-is, ADU, SB9, multi-unit) with cash flow projections, \
mortgage analysis, and tax benefits
- Permit history: look up building permits filed for any property — see renovations, \
  construction work, job values, and filing dates
- Database queries: answer ad-hoc analytical questions by querying the database directly — \
  counts, averages, distributions, filtering, grouping across 17,000+ properties

RULES:
- Always ground your advice in data from the tools — call them before answering
- If the user asks something you can answer with a tool, use it
- When the user mentions a specific address, use lookup_property first to get property details, \
then use those details when calling other tools
- You can call multiple tools in sequence — e.g. lookup_property → get_development_potential
- Do NOT provide specific investment advice or guaranteed returns
- Mention that your projections are estimates based on historical data
- When the user asks to find or search for properties matching criteria (e.g. "find large lots \
  in North Berkeley zoned R-1"), use search_properties — do NOT use lookup_property for that
- When comparing development opportunities across properties, use search_properties first to \
  find candidates, then optionally drill into specific properties with get_development_potential \
  or analyze_investment_scenarios
- IMPORTANT: When following up on search_properties results with get_development_potential, \
  ALWAYS pass the property_id from the search results. This ensures the exact correct property \
  is looked up. Without property_id, lat/lon proximity matching may return data from a \
  neighboring property in a different zone, causing incorrect results.
- When the user asks about permit history, renovations, or construction work on a property, \
  use lookup_permits with the property address
- When the user asks aggregate or analytical questions (counts, averages, distributions, \
  "how many", "what percentage", "which neighborhoods have the most"), use query_database \
  to write and execute a SQL query. This is much better than trying to use search_properties \
  with filters and counting the results manually
- Keep responses concise — 2-4 paragraphs max unless asked for detail
- Use dollar amounts and percentages to make your points concrete
- When discussing rental income, note that estimates use local price-to-rent ratios \
  and neighborhood data, but actual rents depend on condition, exact location, \
  and current market conditions
- For investment scenarios, compare the as-is scenario with the best development option \
  and highlight the trade-offs (capital required, timeline, risk)

DATA MODEL:
The properties table distinguishes between physical lots and sellable units:
- record_type='lot': Physical lots — SFR, duplexes, triplexes, fourplexes, apartments. \
  lot_size_sqft is the actual lot. Development potential analysis applies to these.
- record_type='unit': Sellable units within a larger lot — condos, co-ops. \
  lot_size_sqft is the SHARED lot size for all units on the lot. Use lot_group_key \
  to find all units sharing the same physical lot.
- property_category provides granular classification: sfr, duplex, triplex, fourplex, \
  apartment, condo, townhouse, pud, coop, land, mixed_use.
- When a user asks about development potential for a condo unit, explain that it's a unit \
  within a larger lot and analyze the lot as a whole (the system does this automatically).
- For development opportunity searches, filter to record_type='lot' to exclude individual \
  condo units that can't be independently developed.

DATA ACCURACY RULES:
- Every tool result includes a "_facts" section with pre-computed, verified statistics. \
  ALWAYS use _facts for counts, ranges, and eligibility flags instead of computing your own.
- When stating how many properties match a criterion (e.g. "6 of 10 are ADU eligible"), \
  use the exact count from _facts. NEVER say "all N properties" unless _facts confirms \
  the count equals N.
- A VERIFIED DATA SUMMARY may appear in your context with cross-tool facts. \
  Reference it for any claim that spans multiple tool calls.
- Never invent appreciation rates, market percentages, or price trends not in tool results. \
  If data isn't available, say "I don't have data on that."
- Reference properties by address, never by list position ("the first property").
- When comparing properties across tool calls, use the VERIFIED DATA SUMMARY rather than \
  trying to recall earlier tool results from memory.

WORKING SET RULES:
When a session working set is active (shown in "PROPERTY WORKING SET" above), it contains the \
current set of properties the user is discussing. Follow these rules:
- "these", "those", "the current set", "the results" refer to the properties in the working set
- When the user asks to narrow or filter the working set (e.g. "which of those are in North \
  Berkeley?"), use query_database with a JOIN against the _working_set temp table: \
  SELECT ... FROM properties p JOIN _working_set ws ON p.id = ws.property_id WHERE ...
- When the user asks aggregate questions about the current set (e.g. "what's the average lot \
  size of these?"), use query_database with the _working_set JOIN
- When the user says "go back", "undo that", "remove the last filter", or wants to restore \
  the previous set, use undo_filter
- The working set is automatically populated when you use search_properties or query_database \
  queries that return property IDs — you don't need to manage it manually
- The working set descriptor shows distributions and ranges — use these for quick summaries \
  without needing to re-query
- If the user asks about a specific property from the working set, you can still use \
  lookup_property or other per-property tools with that property's details

DATA QUALITY AWARENESS:
- About 232 Multi-Family 5+ properties have PER-UNIT assessor features (sqft, beds, baths \
  reflect one unit) but WHOLE-BUILDING sale prices and lot sizes. This creates misleading \
  metrics like extremely low building-to-lot ratios or extremely high price-per-sqft.
- When searching for development opportunities, underdeveloped properties, or density analysis, \
  EXCLUDE per-unit mismatch records using: WHERE building_sqft / NULLIF(sqft, 0) <= 3 \
  OR building_sqft IS NULL
- search_properties results include a data_quality field. When presenting results, note any \
  properties flagged with data quality issues (per_unit_mismatch or mf5_limited_data).
- For building density or building-to-lot ratio calculations, ALWAYS use building_sqft (total \
  building footprint), never sqft (per-unit living area).
- The building_to_lot_ratio field in search results is pre-computed using the correct \
  building_sqft column — use it directly instead of computing your own ratio.

SEARCH RESULT PRESENTATION:
- When search_properties returns results, ALWAYS state how many you're showing vs how many \
  total match. Say "Here are 25 of 88 matching properties" NOT "Here are all 25 properties".
- The _facts.total_matching field tells you the true count. If total_matching > the number \
  of results returned, mention that more exist and the user can refine or you can query_database \
  for the full set.
- Never say "all X properties" unless the returned count equals total_matching.

OWNER CONTEXT RULES:
When a user says they OWN a property, BOUGHT it, or refers to it as "my property/house":
1. Use lookup_property to get the property's last_sale_price and last_sale_date
2. Pass purchase_price from the user's stated price OR from last_sale_price if they didn't specify
3. Pass purchase_date from the user's stated date OR from last_sale_date
4. Pass mortgage_rate if the user mentions their actual rate (e.g., "I got a 3.25% rate")
5. These owner-context values ensure that investment cards show ACTUAL mortgage payments \
   (based on what they paid), not hypothetical numbers based on today's market value
6. Property tax under CA Prop 13 is assessed on purchase price, so this is important for accuracy
7. If the user gives a current value estimate, pass it as current_value_override

PROPERTY TYPE ANALYSIS RULES:
When analyzing a property, always consider its property_category (shown in the CURRENT PROPERTY \
CONTEXT) before recommending or running analyses. The backend enforces guardrails, but you should \
also frame your responses appropriately:

**Single-Family Residential (sfr):**
- Full analysis suite: price prediction, comps, development potential (ADU, SB9, lot split), \
  improvement ROI, rental income, all investment scenarios.

**Duplex / Triplex / Fourplex:**
- All analyses EXCEPT SB9 lot splitting (SB9 only applies to single-family in R-1/R-1H zones).
- ADU may apply depending on lot size and zoning.
- When discussing investment scenarios, note that SB9 is excluded and explain why.

**Condo / Co-op / Townhouse:**
- Price prediction, comparable sales, sell vs hold, improvement simulation, as-is rental income.
- Do NOT suggest or run development potential tools (the owner does not control the lot).
- Do NOT suggest lot-split, ADU, or SB9 scenarios.
- Investment analysis is limited to as-is rental scenario only.
- Frame analysis around: unit value, HOA considerations, comparable unit sales, rental yield.

**Apartment (5+ units):**
- Price prediction, comparable sales, sell vs hold, improvement simulation, as-is rental income.
- Do NOT suggest ADU/SB9/lot-split (irrelevant at this scale).
- Investment analysis is limited to as-is existing unit rental analysis.
- Frame analysis around: per-unit economics, cap rate, gross rent multiplier, building-level value.

**Land / Vacant:**
- Price prediction, comparable land sales, sell vs hold, zoning-based development analysis.
- Do NOT suggest improvement simulation (no structure to improve).
- Do NOT suggest rental income (no units to rent).
- Focus on: zoning capacity, what CAN be built, new construction feasibility, permitted uses.

**Mixed-Use:**
- Price prediction, comparable sales, sell vs hold, improvement simulation.
- Development potential is limited to the residential portion.
- Rental income analysis covers existing residential units only.

**Commercial:**
- Price prediction, comparable sales, sell vs hold.
- Do NOT suggest residential-focused analyses (ADU, SB9, improvement ROI, residential rental).

CONTEXT:
You are the primary interface for the HomeBuyer app. Users may ask about any Berkeley property \
by address, or about the overall market. If property details (address, coordinates, etc.) are \
provided in the conversation context, use them when calling tools. If the user asks about a \
different property, use lookup_property to find it first."""


class FaketorService:
    """Chat service that wraps Claude with real estate analysis tools."""

    def __init__(self) -> None:
        self._client = None
        self._enabled = bool(ANTHROPIC_API_KEY)

        if self._enabled:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except Exception as e:
                logger.warning("Failed to initialize Anthropic client for Faketor: %s", e)
                self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def chat(
        self,
        message: str,
        history: list[dict],
        property_context: dict,
        tool_executor,
        working_set_descriptor: str = "",
    ) -> dict:
        """Run a single chat turn with tool use.

        Args:
            message: The user's new message.
            history: Previous messages [{role, content}, ...].
            property_context: Property details (lat, lon, address, neighborhood, etc.).
            tool_executor: Callable(tool_name, tool_input) -> str that executes tools.
            working_set_descriptor: Session working set summary for system prompt.

        Returns:
            {"reply": str, "tool_calls": list, "blocks": list} or {"error": str}
        """
        if not self._enabled or not self._client:
            return {"error": "Faketor is unavailable (no API key configured)"}

        # Build system prompt with property context and working set
        base_system = SYSTEM_PROMPT + f"\n\nCURRENT PROPERTY CONTEXT:\n{json.dumps(property_context, indent=2)}"
        if working_set_descriptor:
            base_system += f"\n\n{working_set_descriptor}"

        # Build messages: history + new user message
        messages = list(history) + [{"role": "user", "content": message}]

        tool_calls_log = []
        blocks = []  # Structured response blocks for frontend rendering
        accumulator = AnalysisAccumulator()

        try:
            # Agentic loop: keep going until Claude stops calling tools
            max_iterations = 12
            for _ in range(max_iterations):
                # Inject accumulated facts summary into system prompt
                system = base_system
                if accumulator.tool_sequence:
                    system = base_system + "\n\n" + accumulator.get_summary()

                response = self._client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=system,
                    tools=FAKETOR_TOOLS,
                    messages=messages,
                )

                # If Claude is done, extract text
                if response.stop_reason == "end_turn":
                    text_parts = [
                        b.text for b in response.content if b.type == "text"
                    ]
                    return {
                        "reply": "\n".join(text_parts),
                        "tool_calls": tool_calls_log,
                        "blocks": blocks,
                    }

                # Extract tool use blocks
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                if not tool_use_blocks:
                    # No tools and not end_turn — extract whatever text we have
                    text_parts = [
                        b.text for b in response.content if b.type == "text"
                    ]
                    return {
                        "reply": "\n".join(text_parts) if text_parts else "I'm not sure how to help with that.",
                        "tool_calls": tool_calls_log,
                        "blocks": blocks,
                    }

                # Append assistant response (with tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})

                # Execute tools, enrich with facts, collect results
                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_calls_log.append({
                        "name": tool_block.name,
                        "input": tool_block.input,
                    })
                    try:
                        result_str = tool_executor(tool_block.name, tool_block.input)
                    except Exception as e:
                        logger.warning("Tool %s failed: %s", tool_block.name, e)
                        result_str = json.dumps({"error": str(e)})

                    # Parse result for fact enrichment and block creation
                    result_data = None
                    try:
                        result_data = json.loads(result_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

                    # Enrich tool result with _facts for Claude
                    if isinstance(result_data, (dict, list)):
                        is_error = isinstance(result_data, dict) and result_data.get("error")
                        if not is_error:
                            facts = compute_facts_for_tool(tool_block.name, result_data)
                            if facts:
                                accumulator.record(tool_block.name, tool_block.input, facts)
                                if isinstance(result_data, dict):
                                    result_data["_facts"] = facts
                                    result_str = json.dumps(result_data, default=str)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": result_str,
                    })

                    # Build frontend block (strip _facts — frontend doesn't need it)
                    block_type = TOOL_TO_BLOCK_TYPE.get(tool_block.name)
                    if block_type and result_data is not None:
                        is_error = isinstance(result_data, dict) and result_data.get("error")
                        if not is_error:
                            if isinstance(result_data, dict):
                                block_data = {k: v for k, v in result_data.items() if k != "_facts"}
                            else:
                                block_data = result_data
                            blocks.append({
                                "type": block_type,
                                "tool_name": tool_block.name,
                                "data": block_data,
                            })

                messages.append({"role": "user", "content": tool_results})

            # If we hit max iterations, return what we have with a graceful message
            fallback_reply = (
                "Here's what I found based on my analysis so far."
                if blocks
                else "I gathered a lot of data but ran out of room to summarize it. Could you ask a more specific question?"
            )
            return {
                "reply": fallback_reply,
                "tool_calls": tool_calls_log,
                "blocks": blocks,
            }

        except Exception as e:
            error_str = str(e).lower()
            logger.warning("Faketor chat failed: %s", e, exc_info=True)
            if "rate_limit" in error_str or "429" in str(e):
                return {"error": "Faketor is temporarily busy (rate limited). Try again in a moment."}
            elif "authentication" in error_str or "401" in str(e):
                return {"error": "Faketor is unavailable (invalid API key)"}
            else:
                return {"error": f"Faketor encountered an error: {type(e).__name__}"}

    # ------------------------------------------------------------------
    # Streaming version
    # ------------------------------------------------------------------

    _TOOL_LABELS: dict[str, str] = {
        "lookup_property": "Looking up property...",
        "get_price_prediction": "Running price prediction...",
        "get_comparable_sales": "Finding comparable sales...",
        "get_development_potential": "Checking development potential...",
        "get_neighborhood_stats": "Getting neighborhood stats...",
        "get_market_summary": "Loading market data...",
        "estimate_rental_income": "Estimating rental income...",
        "analyze_investment_scenarios": "Comparing investment scenarios...",
        "estimate_sell_vs_hold": "Analyzing sell vs hold...",
        "get_improvement_simulation": "Simulating improvements...",
        "search_properties": "Searching properties...",
        "lookup_permits": "Looking up permits...",
        "query_database": "Querying database...",
        "undo_filter": "Undoing last filter...",
    }

    def chat_stream(
        self,
        message: str,
        history: list[dict],
        property_context: dict,
        tool_executor,
        working_set_descriptor: str = "",
    ):
        """Streaming version of chat(). Yields SSE event dicts.

        Event types:
          {"event": "text_delta", "data": {"text": "..."}}
          {"event": "tool_start", "data": {"name": "...", "label": "..."}}
          {"event": "tool_result", "data": {"name": "...", "block": {...} or None}}
          {"event": "done", "data": {"reply": "...", "tool_calls": [...], "blocks": [...]}}
          {"event": "error", "data": {"message": "..."}}
        """
        if not self._enabled or not self._client:
            yield {"event": "error", "data": {"message": "Faketor is unavailable (no API key configured)"}}
            return

        base_system = SYSTEM_PROMPT + f"\n\nCURRENT PROPERTY CONTEXT:\n{json.dumps(property_context, indent=2)}"
        if working_set_descriptor:
            base_system += f"\n\n{working_set_descriptor}"
        messages = list(history) + [{"role": "user", "content": message}]

        tool_calls_log: list[dict] = []
        blocks: list[dict] = []
        all_text_parts: list[str] = []
        accumulator = AnalysisAccumulator()

        try:
            max_iterations = 12
            for _ in range(max_iterations):
                # Inject accumulated facts summary into system prompt
                system = base_system
                if accumulator.tool_sequence:
                    system = base_system + "\n\n" + accumulator.get_summary()

                # Stream this iteration's response
                with self._client.messages.stream(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=system,
                    tools=FAKETOR_TOOLS,
                    messages=messages,
                ) as stream:
                    iteration_text: list[str] = []
                    for text_chunk in stream.text_stream:
                        yield {"event": "text_delta", "data": {"text": text_chunk}}
                        iteration_text.append(text_chunk)

                    response = stream.get_final_message()

                # If Claude is done, break out
                if response.stop_reason == "end_turn":
                    all_text_parts.extend(iteration_text)
                    break

                # Extract tool use blocks
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                if not tool_use_blocks:
                    all_text_parts.extend(iteration_text)
                    break

                # Add paragraph break between pre-tool text and post-tool text
                # so they don't jam together in the rendered message
                if iteration_text:
                    all_text_parts.extend(iteration_text)
                    all_text_parts.append("\n\n")
                    yield {"event": "text_delta", "data": {"text": "\n\n"}}

                # Append assistant content to messages for next iteration
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool, enrich with facts
                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_calls_log.append({
                        "name": tool_block.name,
                        "input": tool_block.input,
                    })

                    yield {
                        "event": "tool_start",
                        "data": {
                            "name": tool_block.name,
                            "label": self._TOOL_LABELS.get(tool_block.name, f"Using {tool_block.name}..."),
                        },
                    }

                    try:
                        result_str = tool_executor(tool_block.name, tool_block.input)
                    except Exception as e:
                        logger.warning("Tool %s failed: %s", tool_block.name, e)
                        result_str = json.dumps({"error": str(e)})

                    # Parse result for fact enrichment and block creation
                    result_data = None
                    try:
                        result_data = json.loads(result_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

                    # Enrich tool result with _facts for Claude
                    if isinstance(result_data, (dict, list)):
                        is_error = isinstance(result_data, dict) and result_data.get("error")
                        if not is_error:
                            facts = compute_facts_for_tool(tool_block.name, result_data)
                            if facts:
                                accumulator.record(tool_block.name, tool_block.input, facts)
                                if isinstance(result_data, dict):
                                    result_data["_facts"] = facts
                                    result_str = json.dumps(result_data, default=str)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": result_str,
                    })

                    # Build frontend block (strip _facts)
                    block_type = TOOL_TO_BLOCK_TYPE.get(tool_block.name)
                    block = None
                    if block_type and result_data is not None:
                        is_error = isinstance(result_data, dict) and result_data.get("error")
                        if not is_error:
                            if isinstance(result_data, dict):
                                block_data = {k: v for k, v in result_data.items() if k != "_facts"}
                            else:
                                block_data = result_data
                            block = {
                                "type": block_type,
                                "tool_name": tool_block.name,
                                "data": block_data,
                            }
                            blocks.append(block)

                    yield {
                        "event": "tool_result",
                        "data": {
                            "name": tool_block.name,
                            "block": block,
                        },
                    }

                messages.append({"role": "user", "content": tool_results})

            # Yield done event with complete response
            full_reply = "".join(all_text_parts)
            if not full_reply:
                full_reply = (
                    "Here's what I found based on my analysis so far."
                    if blocks
                    else "I gathered a lot of data but ran out of room to summarize it. Could you ask a more specific question?"
                )
            yield {
                "event": "done",
                "data": {
                    "reply": full_reply,
                    "tool_calls": tool_calls_log,
                    "blocks": blocks,
                },
            }

        except Exception as e:
            error_str = str(e).lower()
            logger.warning("Faketor streaming chat failed: %s", e, exc_info=True)
            if "rate_limit" in error_str or "429" in str(e):
                yield {"event": "error", "data": {"message": "Faketor is temporarily busy (rate limited). Try again in a moment."}}
            elif "authentication" in error_str or "401" in str(e):
                yield {"event": "error", "data": {"message": "Faketor is unavailable (invalid API key)"}}
            else:
                yield {"event": "error", "data": {"message": f"Faketor encountered an error: {type(e).__name__}"}}
