"""Registration of all 18 built-in Faketor tools.

Each entry encodes what was previously spread across three parallel structures:
  - FAKETOR_TOOLS list          (tool schema dicts)
  - TOOL_TO_BLOCK_TYPE dict     (frontend block routing)
  - _FACT_COMPUTERS dict        (fact enrichment)
"""

from homebuyer.services.faketor.facts import (
    compute_comps_facts,
    compute_development_facts,
    compute_glossary_facts,
    compute_improvement_facts,
    compute_investment_facts,
    compute_neighborhood_facts,
    compute_prediction_facts,
    compute_query_facts,
    compute_regulation_facts,
    compute_rental_facts,
    compute_search_facts,
    compute_sell_vs_hold_facts,
    compute_undo_filter_facts,
)
from homebuyer.services.faketor.tools.registry import ToolDefinition


_TOOL_DEFINITIONS: list[ToolDefinition] = [
    {
        "name": "lookup_property",
        "description": (
            "Look up a Berkeley property by address. Returns property details from the "
            "citywide database including beds, baths, sqft, year built, lot size, zoning, "
            "neighborhood, and last sale info. Use this when the user mentions a specific "
            "address or asks about a property you don't already have context for."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "address": {
                                "type": "string",
                                "description": "Street address to search for (e.g. '1234 Cedar St')"
                        }
                },
                "required": [
                        "address"
                ]
        },
        "block_type": "property_detail",
        "fact_computer": None,
    },
    {
        "name": "get_development_potential",
        "description": (
            "Get zoning details, ADU feasibility, Middle Housing eligibility, SB 9 lot-split "
            "eligibility, and BESO energy status for a Berkeley property. Use this when the "
            "user asks about what can be built on the property, zoning rules, adding units, "
            "or development upside. IMPORTANT: When following up on search_properties "
            "results, always pass the property_id from the search results to ensure the "
            "correct property is looked up (not a nearby neighbor)."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "latitude": {
                                "type": "number",
                                "description": "Property latitude"
                        },
                        "longitude": {
                                "type": "number",
                                "description": "Property longitude"
                        },
                        "address": {
                                "type": "string",
                                "description": "Street address"
                        },
                        "property_id": {
                                "type": "integer",
                                "description": "Database property ID from search_properties results. When available, this ensures the exact property is looked up instead of relying on lat/lon proximity matching."
                        }
                },
                "required": [
                        "latitude",
                        "longitude"
                ]
        },
        "block_type": "development_potential",
        "fact_computer": compute_development_facts,
    },
    {
        "name": "get_improvement_simulation",
        "description": (
            "Simulate the effect of home improvements (kitchen, bathroom, ADU, solar, etc.) "
            "on predicted property value using the ML model. Returns per-category cost, "
            "predicted value delta, ROI, and market correlation data. Use this when the user "
            "asks about renovations, improvements, ROI on upgrades, or what improvements are "
            "worth doing."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "latitude": {
                                "type": "number"
                        },
                        "longitude": {
                                "type": "number"
                        },
                        "address": {
                                "type": "string"
                        },
                        "neighborhood": {
                                "type": "string"
                        },
                        "beds": {
                                "type": "number"
                        },
                        "baths": {
                                "type": "number"
                        },
                        "sqft": {
                                "type": "integer"
                        },
                        "year_built": {
                                "type": "integer"
                        }
                },
                "required": [
                        "latitude",
                        "longitude"
                ]
        },
        "block_type": "improvement_sim",
        "fact_computer": compute_improvement_facts,
    },
    {
        "name": "get_comparable_sales",
        "description": (
            "Find recent comparable property sales in the same neighborhood. Returns sale "
            "prices, dates, and property details for similar homes. Use this when the user "
            "asks about recent sales, what similar homes sold for, or market comps."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "neighborhood": {
                                "type": "string",
                                "description": "Berkeley neighborhood name"
                        },
                        "beds": {
                                "type": "number"
                        },
                        "baths": {
                                "type": "number"
                        },
                        "sqft": {
                                "type": "integer"
                        },
                        "year_built": {
                                "type": "integer"
                        }
                },
                "required": [
                        "neighborhood"
                ]
        },
        "block_type": "comps_table",
        "fact_computer": compute_comps_facts,
    },
    {
        "name": "get_neighborhood_stats",
        "description": (
            "Get neighborhood-level statistics: median/avg price, price per sqft, "
            "year-over-year price change, sale count, dominant zoning, property types. Use "
            "this when the user asks about a neighborhood's market, price trends, or how the "
            "area compares."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "neighborhood": {
                                "type": "string",
                                "description": "Berkeley neighborhood name"
                        },
                        "years": {
                                "type": "integer",
                                "description": "Lookback years (default 2)"
                        }
                },
                "required": [
                        "neighborhood"
                ]
        },
        "block_type": "neighborhood_stats",
        "fact_computer": compute_neighborhood_facts,
    },
    {
        "name": "get_market_summary",
        "description": (
            "Get Berkeley-wide market summary: current median prices, sale-to-list ratio, "
            "days on market, mortgage rates, inventory, price distribution, top neighborhoods "
            "by price. Use this when the user asks about the overall Berkeley market, trends, "
            "or timing."
        ),
        "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
        },
        "block_type": "market_summary",
        "fact_computer": None,
    },
    {
        "name": "get_price_prediction",
        "description": (
            "Get the ML model's predicted sale price for the property, including confidence "
            "interval and feature contributions. Use this when the user asks what the "
            "property is worth, its estimated value, or wants a price opinion."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "latitude": {
                                "type": "number"
                        },
                        "longitude": {
                                "type": "number"
                        },
                        "neighborhood": {
                                "type": "string"
                        },
                        "zip_code": {
                                "type": "string"
                        },
                        "beds": {
                                "type": "number"
                        },
                        "baths": {
                                "type": "number"
                        },
                        "sqft": {
                                "type": "integer"
                        },
                        "year_built": {
                                "type": "integer"
                        },
                        "lot_size_sqft": {
                                "type": "integer"
                        },
                        "property_type": {
                                "type": "string"
                        }
                },
                "required": [
                        "latitude",
                        "longitude",
                        "neighborhood"
                ]
        },
        "block_type": "prediction_card",
        "fact_computer": compute_prediction_facts,
    },
    {
        "name": "estimate_sell_vs_hold",
        "description": (
            "Estimate whether to sell now or hold the property for 1, 3, or 5 years. Uses the "
            "ML price prediction, neighborhood year-over-year appreciation, and market "
            "conditions to project future value. Also estimates rough rental yield based on "
            "Berkeley price-to-rent ratios. Use this when the user asks about selling vs "
            "renting, hold period, investment timeline, or whether to sell now. When the user "
            "says they OWN the property, pass purchase_price, purchase_date, and "
            "mortgage_rate so numbers reflect their actual financial position."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "latitude": {
                                "type": "number"
                        },
                        "longitude": {
                                "type": "number"
                        },
                        "neighborhood": {
                                "type": "string"
                        },
                        "zip_code": {
                                "type": "string"
                        },
                        "beds": {
                                "type": "number"
                        },
                        "baths": {
                                "type": "number"
                        },
                        "sqft": {
                                "type": "integer"
                        },
                        "year_built": {
                                "type": "integer"
                        },
                        "lot_size_sqft": {
                                "type": "integer"
                        },
                        "property_type": {
                                "type": "string"
                        },
                        "purchase_price": {
                                "type": "number",
                                "description": "Price the owner paid for the property (for mortgage/expense/ROI calculations)."
                        },
                        "purchase_date": {
                                "type": "string",
                                "description": "When the owner purchased, YYYY-MM-DD format (for holding period ROI)."
                        },
                        "mortgage_rate": {
                                "type": "number",
                                "description": "Owner's actual mortgage rate, e.g. 3.25 (overrides current market rate)."
                        },
                        "current_value_override": {
                                "type": "number",
                                "description": "Override ML prediction with user-stated or appraised current value."
                        }
                },
                "required": [
                        "latitude",
                        "longitude",
                        "neighborhood"
                ]
        },
        "block_type": "sell_vs_hold",
        "fact_computer": compute_sell_vs_hold_facts,
    },
    {
        "name": "estimate_rental_income",
        "description": (
            "Estimate rental income for a Berkeley property. Returns monthly/annual rent "
            "estimates, itemized operating expenses, mortgage analysis, cap rate, "
            "cash-on-cash return, and cash flow projections for a rent-as-is scenario. Use "
            "this when the user asks about rental income, what the property could rent for, "
            "monthly rent estimates, or landlord cash flow. When the user says they OWN the "
            "property, pass purchase_price, purchase_date, and mortgage_rate so expenses and "
            "mortgage reflect their actual costs."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "latitude": {
                                "type": "number"
                        },
                        "longitude": {
                                "type": "number"
                        },
                        "neighborhood": {
                                "type": "string"
                        },
                        "beds": {
                                "type": "number"
                        },
                        "baths": {
                                "type": "number"
                        },
                        "sqft": {
                                "type": "integer"
                        },
                        "year_built": {
                                "type": "integer"
                        },
                        "lot_size_sqft": {
                                "type": "integer"
                        },
                        "property_type": {
                                "type": "string"
                        },
                        "down_payment_pct": {
                                "type": "number",
                                "description": "Down payment percentage (default 20)"
                        },
                        "purchase_price": {
                                "type": "number",
                                "description": "Price the owner paid for the property (for mortgage/expense/ROI calculations)."
                        },
                        "purchase_date": {
                                "type": "string",
                                "description": "When the owner purchased, YYYY-MM-DD format."
                        },
                        "mortgage_rate": {
                                "type": "number",
                                "description": "Owner's actual mortgage rate, e.g. 3.25 (overrides current market rate)."
                        },
                        "current_value_override": {
                                "type": "number",
                                "description": "Override ML prediction with user-stated or appraised current value."
                        }
                },
                "required": [
                        "latitude",
                        "longitude"
                ]
        },
        "block_type": "rental_income",
        "fact_computer": compute_rental_facts,
    },
    {
        "name": "analyze_investment_scenarios",
        "description": (
            "Run comprehensive investment scenario analysis comparing multiple strategies: "
            "rent as-is, add ADU, SB9 lot split, and multi-unit development. For each "
            "applicable scenario, provides cash flow projections over 1-20 years, mortgage "
            "analysis, tax benefits (depreciation, interest deduction), and key metrics (cap "
            "rate, cash-on-cash return, equity buildup). Integrates with development "
            "potential data for ADU feasibility and SB9 eligibility. Use this when the user "
            "asks about investment analysis, best scenario, ROI of adding an ADU vs renting "
            "as-is, development returns, or long-term investment comparison. When the user "
            "says they OWN the property, pass purchase_price, purchase_date, and "
            "mortgage_rate so all scenarios reflect their actual financial position."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "latitude": {
                                "type": "number"
                        },
                        "longitude": {
                                "type": "number"
                        },
                        "neighborhood": {
                                "type": "string"
                        },
                        "beds": {
                                "type": "number"
                        },
                        "baths": {
                                "type": "number"
                        },
                        "sqft": {
                                "type": "integer"
                        },
                        "year_built": {
                                "type": "integer"
                        },
                        "lot_size_sqft": {
                                "type": "integer"
                        },
                        "property_type": {
                                "type": "string"
                        },
                        "down_payment_pct": {
                                "type": "number",
                                "description": "Down payment percentage (default 20)"
                        },
                        "self_managed": {
                                "type": "boolean",
                                "description": "Whether owner self-manages (no mgmt fee). Default true."
                        },
                        "purchase_price": {
                                "type": "number",
                                "description": "Price the owner paid for the property (for mortgage/expense/ROI calculations)."
                        },
                        "purchase_date": {
                                "type": "string",
                                "description": "When the owner purchased, YYYY-MM-DD format."
                        },
                        "mortgage_rate": {
                                "type": "number",
                                "description": "Owner's actual mortgage rate, e.g. 3.25 (overrides current market rate)."
                        },
                        "current_value_override": {
                                "type": "number",
                                "description": "Override ML prediction with user-stated or appraised current value."
                        }
                },
                "required": [
                        "latitude",
                        "longitude"
                ]
        },
        "block_type": "investment_scenarios",
        "fact_computer": compute_investment_facts,
    },
    {
        "name": "generate_investment_prospectus",
        "description": (
            "Generate a comprehensive investment prospectus for one or more Berkeley "
            "properties. Aggregates valuation, market context, development potential, "
            "rental/investment scenarios, comparable sales, and risk factors into a single "
            "professional document with charts, narratives, and detailed analysis. Supports "
            "three multi-property modes: - 'curated': 1-10 diverse properties as a portfolio "
            "with allocation charts - 'similar': 2-10 similar properties for side-by-side "
            "comparison - 'thesis': 10+ properties with an investment thesis, stats, and "
            "examples Mode is auto-detected if not specified. Can also use the session "
            "working set as the property source (set from_working_set=true). Use this when "
            "the user asks for a prospectus, investment summary, professional property "
            "report, or wants a comprehensive overview of a property's investment potential. "
            "Also use when the user wants to compare multiple properties side-by-side as "
            "investment opportunities."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "addresses": {
                                "type": "array",
                                "items": {
                                        "type": "string"
                                },
                                "description": "List of property addresses to generate prospectus for. For a single property, provide a one-element array. For portfolio analysis, provide multiple addresses. Not required if from_working_set is true."
                        },
                        "down_payment_pct": {
                                "type": "number",
                                "description": "Down payment percentage (default 20)"
                        },
                        "investment_horizon_years": {
                                "type": "integer",
                                "description": "Investment horizon in years (default 5)"
                        },
                        "mode": {
                                "type": "string",
                                "enum": [
                                        "curated",
                                        "similar",
                                        "thesis"
                                ],
                                "description": "Multi-property prospectus mode. Auto-detected if omitted:\n- 'curated': diverse portfolio overview with allocation charts\n- 'similar': side-by-side comparison highlighting shared traits and differences\n- 'thesis': investment thesis with statistics and representative examples\nIf you're unsure which mode the user wants, ask them."
                        },
                        "from_working_set": {
                                "type": "boolean",
                                "description": "If true, use properties from the current session working set instead of the addresses list. Useful for generating a prospectus from search results or filtered sets the user is discussing."
                        }
                },
                "required": []
        },
        "block_type": "investment_prospectus",
        "fact_computer": None,
    },
    {
        "name": "search_properties",
        "description": (
            "PREFER update_working_set for working set operations — it supports replace, "
            "narrow, and expand modes with proper working set management. Search Berkeley "
            "properties by criteria to find development opportunities. Returns multiple "
            "properties with development potential summaries (ADU eligibility, SB9 lot split "
            "eligibility, max units, zoning), data quality flags, and pre-computed "
            "building-to-lot ratios. Use this when the user wants to find properties matching "
            "criteria (e.g. 'find R-1 properties with large lots in North Berkeley'), compare "
            "development opportunities, or search for investment targets. Do NOT use this for "
            "looking up a single known address — use lookup_property instead. Results are "
            "capped at 25 properties. The response includes total_matching — the true count "
            "of all matching properties. The search results populate the session working set "
            "for follow-up queries."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "neighborhoods": {
                                "type": "array",
                                "items": {
                                        "type": "string"
                                },
                                "description": "Filter by neighborhood name(s). Examples: 'North Berkeley', 'Elmwood', 'Thousand Oaks', 'West Berkeley', 'Berkeley Hills', 'Claremont', 'Central Berkeley', 'Cragmont', 'Northbrae', etc."
                        },
                        "zoning_classes": {
                                "type": "array",
                                "items": {
                                        "type": "string"
                                },
                                "description": "Filter by exact zoning class(es). E.g. ['R-1', 'R-2']. Common residential: R-1, R-1H, R-2, R-2A, R-2AH, R-2H, R-3, R-3H, R-4, R-4H, ES-R, MU-R."
                        },
                        "zoning_pattern": {
                                "type": "string",
                                "description": "SQL LIKE pattern for zoning class. E.g. 'R-2%' matches R-2, R-2A, R-2AH, R-2H. Use instead of zoning_classes for category matching."
                        },
                        "property_type": {
                                "type": "string",
                                "description": "Filter by property type. E.g. 'Single Family Residential', 'Multi-Family (2-4 Unit)', 'Condo/Co-op'."
                        },
                        "property_category": {
                                "type": "string",
                                "description": "Filter by property category from use code reference. Values: 'sfr', 'duplex', 'triplex', 'fourplex', 'apartment', 'condo', 'townhouse', 'pud', 'coop', 'land', 'mixed_use'. More granular than property_type."
                        },
                        "record_type": {
                                "type": "string",
                                "description": "Filter by record type: 'lot' (physical lot \u2014 SFR, apartments, duplexes) or 'unit' (sellable unit within a lot \u2014 condos, co-ops). Use 'lot' to exclude individual condo units from development searches."
                        },
                        "ownership_type": {
                                "type": "string",
                                "description": "Filter by ownership type: 'fee_simple' (SFR, apartments), 'common_interest' (condos, PUDs), 'cooperative' (co-ops)."
                        },
                        "min_price": {
                                "type": "integer",
                                "description": "Minimum last sale price (e.g. 500000)"
                        },
                        "max_price": {
                                "type": "integer",
                                "description": "Maximum last sale price (e.g. 1500000)"
                        },
                        "min_beds": {
                                "type": "number",
                                "description": "Minimum bedrooms"
                        },
                        "max_beds": {
                                "type": "number",
                                "description": "Maximum bedrooms"
                        },
                        "min_baths": {
                                "type": "number",
                                "description": "Minimum bathrooms"
                        },
                        "max_baths": {
                                "type": "number",
                                "description": "Maximum bathrooms"
                        },
                        "min_lot_sqft": {
                                "type": "integer",
                                "description": "Minimum lot size in sqft (e.g. 5000)"
                        },
                        "max_lot_sqft": {
                                "type": "integer",
                                "description": "Maximum lot size in sqft"
                        },
                        "min_sqft": {
                                "type": "integer",
                                "description": "Minimum per-unit living area sqft (MLS/assessor). For building footprint filtering, use query_database with building_sqft."
                        },
                        "max_sqft": {
                                "type": "integer",
                                "description": "Maximum per-unit living area sqft"
                        },
                        "min_year_built": {
                                "type": "integer",
                                "description": "Minimum year built (e.g. 1950)"
                        },
                        "max_year_built": {
                                "type": "integer",
                                "description": "Maximum year built"
                        },
                        "adu_eligible": {
                                "type": "boolean",
                                "description": "If true, only include properties eligible for ADU construction"
                        },
                        "sb9_eligible": {
                                "type": "boolean",
                                "description": "If true, only include properties eligible for SB9 lot split"
                        },
                        "limit": {
                                "type": "integer",
                                "description": "Max results to return (default 10, max 25)"
                        }
                },
                "required": []
        },
        "block_type": "property_search_results",
        "fact_computer": compute_search_facts,
    },
    {
        "name": "lookup_permits",
        "description": (
            "Look up building permits filed for a specific Berkeley property address. Returns "
            "permit history including permit type, status, description, job value, filing "
            "date, and construction type. Use this when the user asks about permit history, "
            "renovations, construction activity, or improvements done on a property."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "address": {
                                "type": "string",
                                "description": "The property address to look up permits for. Should be the full street address as stored in the database (e.g. '2822 BENVENUE AVE BERKELEY 94705')."
                        },
                        "limit": {
                                "type": "integer",
                                "description": "Max permits to return (default 20)"
                        }
                },
                "required": [
                        "address"
                ]
        },
        "block_type": None,
        "fact_computer": None,
    },
    {
        "name": "undo_filter",
        "description": (
            "Undo the most recent filter applied to the session property working set, "
            "restoring the previous set of properties. Use this when the user says things "
            "like 'go back', 'undo that', 'remove the last filter', 'show me all of them "
            "again', or 'what were the results before I filtered?'. Only works when there is "
            "an active filter stack (i.e. the working set has been narrowed by a previous "
            "query)."
        ),
        "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
        },
        "block_type": None,
        "fact_computer": compute_undo_filter_facts,
    },
    {
        "name": "query_database",
        "description": (
            "Execute a read-only SQL query against the Berkeley property database for "
            "ANALYTICAL and AGGREGATE questions only — counts, averages, distributions, "
            "groupings, and other statistics. Do NOT use this to change which properties are "
            "in the working set; use update_working_set instead. Use this for questions like "
            "'how many properties have X?', 'what is the average Y?', 'which neighborhoods "
            "have the most Z?', or any counting/filtering/grouping question. AVAILABLE TABLES "
            "AND COLUMNS: properties — 17,000+ Berkeley parcels (primary table for most "
            "queries): id, apn, address, street_number, street_name, zip_code, latitude, "
            "longitude, lot_size_sqft, building_sqft, use_code, use_description, "
            "neighborhood, zoning_class, beds (REAL), baths (REAL), sqft, year_built, "
            "property_type, last_sale_date, last_sale_price, situs_unit, property_category, "
            "ownership_type, record_type, lot_group_key, parcel_lot_size_sqft DATA MODEL "
            "COLUMNS: - property_category: Granular type from use code reference — 'sfr', "
            "'duplex', 'triplex', 'fourplex', 'apartment', 'condo', 'townhouse', 'pud', "
            "'coop', 'land', 'mixed_use' - record_type: 'lot' (physical lot — SFR, "
            "apartments, duplexes) or 'unit' (sellable unit within a lot — condos, co-ops). "
            "Condos have individual APNs per unit. - ownership_type: 'fee_simple', "
            "'common_interest' (condos, PUDs), or 'cooperative' - lot_group_key: Grouping key "
            "for condo units sharing the same physical lot (format: "
            "STREETNUMBER_STREETNAME_ZIP). Use to aggregate condo units by lot. - situs_unit: "
            "Unit identifier (A, B, C, etc.) for condo units - parcel_lot_size_sqft: Raw lot "
            "size from assessor (before any corrections) use_codes — Reference table for "
            "Alameda County use codes: use_code, description, property_category, "
            "ownership_type, record_type, estimated_units, is_residential, lot_size_meaning, "
            "building_ar_meaning IMPORTANT COLUMN NOTES: - sqft: Per-unit living area from "
            "MLS/assessor. For condos and MF 5+, this is ONE unit's sqft. - building_sqft: "
            "Total building footprint from assessor (entire structure). - For single-family "
            "homes, sqft ≈ building_sqft. For multi-unit properties, building_sqft >> sqft. - "
            "When computing building density or building-to-lot ratios, ALWAYS use "
            "building_sqft, NOT sqft. - For condos (record_type='unit'), lot_size_sqft is the "
            "SHARED lot for all units — use lot_group_key to find sibling units and divide "
            "lot_size by unit count. - ~232 multi-family 5+ properties have per-unit "
            "sqft/beds/baths but whole-building lot_size_sqft and last_sale_price. Identify "
            "them with: building_sqft / NULLIF(sqft, 0) > 3 property_sales — historical sale "
            "transactions: id, mls_number, address, city, zip_code, sale_date, sale_price, "
            "sale_type, property_type, beds, baths, sqft, lot_size_sqft, year_built, "
            "price_per_sqft, hoa_per_month, latitude, longitude, neighborhood, zoning_class, "
            "days_on_market building_permits — permit history: id, record_number, "
            "permit_type, status, address, zip_code, parcel_id, description, job_value, "
            "construction_type, filed_date neighborhoods — neighborhood reference: id, name, "
            "aliases, centroid_lat, centroid_lon, area_sqmi market_metrics — market trends: "
            "period_begin, period_end, median_sale_price, median_list_price, median_ppsf, "
            "homes_sold, new_listings, inventory, months_of_supply, median_dom, "
            "avg_sale_to_list precomputed_scenarios — cached investment analysis per "
            "property: property_id (INTEGER → properties.id), scenario_type (TEXT, use "
            "'buyer'), prediction_json (TEXT — JSON with predicted_price, confidence_pct), "
            "rental_json (TEXT — JSON with investment scenarios, cap_rate, cash_on_cash), "
            "potential_json (TEXT — JSON with ADU/SB9 development feasibility, "
            "effective_max_units), computed_at (TEXT) Use json_extract() to query JSON "
            "fields, e.g.: json_extract(ps.prediction_json, '$.predicted_price') "
            "json_extract(ps.potential_json, '$.adu.eligible') "
            "json_extract(ps.potential_json, '$.effective_max_units') JOIN: LEFT JOIN "
            "precomputed_scenarios ps ON p.id = ps.property_id AND ps.scenario_type = 'buyer' "
            "Use this table to RANK properties by investment metrics across the entire "
            "working set in a single query — much faster than calling per-property tools. "
            "COMMON property_type VALUES: 'Single Family Residential', 'Multi-Family (2-4 "
            "Unit)', 'Condo/Co-op', 'Townhouse', 'Multi-Family (5+ Unit)', 'Land', "
            "'Manufactured' COMPUTED FIELDS — NOT database columns (do NOT use in SQL): "
            "adu_eligible, sb9_eligible, effective_max_units, middle_housing_eligible These "
            "are computed at runtime by the development calculator. → To filter by ADU/SB9 "
            "eligibility, use update_working_set with adu_eligible=true or sb9_eligible=true. "
            "RULES: - Only SELECT statements are allowed (no INSERT, UPDATE, DELETE, DROP, "
            "etc.) - Use LIMIT to cap results (max 100 rows returned) - For "
            "counting/aggregation queries, always use COUNT, SUM, AVG, MIN, MAX, GROUP BY - "
            "Column values are case-sensitive — use exact values from the list above - Use IS "
            "NOT NULL to filter out missing data when needed - NEVER reference adu_eligible, "
            "sb9_eligible, or other computed development fields in SQL queries — they are not "
            "database columns and will cause errors WORKING SET: When a session working set "
            "is active, a temporary table _working_set is available with column: property_id "
            "INTEGER Use JOIN _working_set ws ON p.id = ws.property_id to restrict queries to "
            "the current set. The working set contains property IDs from the most recent "
            "update_working_set or search_properties results."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "sql": {
                                "type": "string",
                                "description": "The SQL SELECT query to execute. Must be a single SELECT statement. Examples:\n- SELECT COUNT(*) as count FROM properties WHERE property_type = 'Single Family Residential' AND lot_size_sqft > 7000\n- SELECT neighborhood, COUNT(*) as count FROM properties GROUP BY neighborhood ORDER BY count DESC LIMIT 10\n- SELECT AVG(last_sale_price) as avg_price, neighborhood FROM properties WHERE last_sale_price IS NOT NULL GROUP BY neighborhood"
                        },
                        "explanation": {
                                "type": "string",
                                "description": "Brief explanation of what the query does (for logging/audit)"
                        }
                },
                "required": [
                        "sql"
                ]
        },
        "block_type": "query_result",
        "fact_computer": compute_query_facts,
    },
    {
        "name": "update_working_set",
        "description": (
            "Change the session property working set — the universe of properties under "
            "discussion. Use this tool ANY TIME the user's request changes which properties "
            "are in scope. THREE MODES: • replace — Start fresh. Use for a new topic or when "
            "the user's criteria are unrelated to the current set. Cues: 'show me ...', 'find "
            "...', 'what about ...', 'switch to ...'. • narrow — Sub-filter the current set. "
            "Use when the user refines within the current results. Cues: 'which of those "
            "...', 'of these, ...', 'filter to ...', 'only the ones that ...'. • expand — Add "
            "more properties to the current set. Use when the user wants to broaden scope. "
            "Cues: 'also include ...', 'add ... to the set', 'what about also looking at "
            "...'. You can provide EITHER structured filter parameters OR a sql query (not "
            "both). Structured parameters are preferred for standard filters; sql for complex "
            "conditions. For sql in narrow mode, a temporary table _working_set(property_id) "
            "is available containing the current working set IDs. Use: SELECT p.id, "
            "p.address, ... FROM properties p JOIN _working_set ws ON p.id = ws.property_id "
            "WHERE ... IMPORTANT: When using sql, ALWAYS include p.id in the SELECT list so "
            "the system can update the working set with the matching property IDs. After the "
            "working set is updated, the system automatically sends the updated sample and "
            "metadata to the frontend — no separate query needed."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "mode": {
                                "type": "string",
                                "enum": [
                                        "replace",
                                        "narrow",
                                        "expand"
                                ],
                                "description": "How to update the working set: 'replace' (new set), 'narrow' (sub-filter), 'expand' (add to set)"
                        },
                        "neighborhoods": {
                                "type": "array",
                                "items": {
                                        "type": "string"
                                },
                                "description": "Filter by neighborhood name(s). Examples: 'North Berkeley', 'Elmwood', 'Thousand Oaks', 'West Berkeley', 'Berkeley Hills', 'Claremont', 'Central Berkeley', 'Cragmont', 'Northbrae', etc."
                        },
                        "zoning_classes": {
                                "type": "array",
                                "items": {
                                        "type": "string"
                                },
                                "description": "Filter by exact zoning class(es). E.g. ['R-1', 'R-2']. Common residential: R-1, R-1H, R-2, R-2A, R-2AH, R-2H, R-3, R-3H, R-4, R-4H, ES-R, MU-R."
                        },
                        "zoning_pattern": {
                                "type": "string",
                                "description": "SQL LIKE pattern for zoning class. E.g. 'R-2%' matches R-2, R-2A, R-2AH, R-2H."
                        },
                        "property_type": {
                                "type": "string",
                                "description": "Filter by property type. E.g. 'Single Family Residential', 'Multi-Family (2-4 Unit)', 'Condo/Co-op'."
                        },
                        "property_category": {
                                "type": "string",
                                "description": "Filter by property category. Values: 'sfr', 'duplex', 'triplex', 'fourplex', 'apartment', 'condo', 'townhouse', 'pud', 'coop', 'land', 'mixed_use'."
                        },
                        "record_type": {
                                "type": "string",
                                "description": "Filter by record type: 'lot' (physical lot) or 'unit' (sellable unit within a lot \u2014 condos, co-ops)."
                        },
                        "ownership_type": {
                                "type": "string",
                                "description": "Filter by ownership type: 'fee_simple', 'common_interest', 'cooperative'."
                        },
                        "min_price": {
                                "type": "integer",
                                "description": "Minimum last sale price"
                        },
                        "max_price": {
                                "type": "integer",
                                "description": "Maximum last sale price"
                        },
                        "min_beds": {
                                "type": "number",
                                "description": "Minimum bedrooms"
                        },
                        "max_beds": {
                                "type": "number",
                                "description": "Maximum bedrooms"
                        },
                        "min_baths": {
                                "type": "number",
                                "description": "Minimum bathrooms"
                        },
                        "max_baths": {
                                "type": "number",
                                "description": "Maximum bathrooms"
                        },
                        "min_lot_sqft": {
                                "type": "integer",
                                "description": "Minimum lot size in sqft"
                        },
                        "max_lot_sqft": {
                                "type": "integer",
                                "description": "Maximum lot size in sqft"
                        },
                        "min_sqft": {
                                "type": "integer",
                                "description": "Minimum living area sqft"
                        },
                        "max_sqft": {
                                "type": "integer",
                                "description": "Maximum living area sqft"
                        },
                        "min_year_built": {
                                "type": "integer",
                                "description": "Minimum year built"
                        },
                        "max_year_built": {
                                "type": "integer",
                                "description": "Maximum year built"
                        },
                        "adu_eligible": {
                                "type": "boolean",
                                "description": "If true, only include ADU-eligible properties"
                        },
                        "sb9_eligible": {
                                "type": "boolean",
                                "description": "If true, only include SB9-eligible properties"
                        },
                        "sql": {
                                "type": "string",
                                "description": "SQL query for complex conditions. MUST include p.id in SELECT. In narrow mode, _working_set temp table is available. Example: SELECT p.id, p.address FROM properties p JOIN _working_set ws ON p.id = ws.property_id WHERE p.property_category = 'sfr'"
                        },
                        "explanation": {
                                "type": "string",
                                "description": "Human-readable description of the update (e.g. 'SFR properties in R-3 zoning')"
                        },
                        "limit": {
                                "type": "integer",
                                "description": "Max results to return in the response (default 10, max 25). Does NOT limit the working set size \u2014 all matching properties are tracked."
                        }
                },
                "required": [
                        "mode"
                ]
        },
        "block_type": "property_search_results",
        "fact_computer": None,
    },
    {
        "name": "lookup_regulation",
        "description": (
            "Look up Berkeley regulations, zoning definitions, or housing policies. Covers "
            "all 32+ zoning code definitions (R-1, R-1H, R-2, C-SA, MUR, etc.), ADU/JADU "
            "rules, SB 9 lot splitting, Middle Housing Ordinance, BESO energy requirements, "
            "transfer tax rates, rent control, permitting processes, and hillside overlay "
            "restrictions. Use this when the user asks about zoning definitions, regulatory "
            "requirements, or housing policy — BEFORE telling them to check the municipal "
            "code."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "topic": {
                                "type": "string",
                                "description": "The regulation topic to look up. Can be a category key (e.g. 'adu_rules', 'transfer_tax', 'rent_control'), a zone code (e.g. 'R-1H', 'C-SA', 'MUR'), or a natural language query (e.g. 'what does the H suffix mean', 'ADU size limits')."
                        },
                        "zone_code": {
                                "type": "string",
                                "description": "Optional specific zone code to look up (e.g. 'R-1H', 'C-DMU'). If provided, returns the definition for that zone code."
                        }
                },
                "required": [
                        "topic"
                ]
        },
        "block_type": "regulation_info",
        "fact_computer": compute_regulation_facts,
    },
    {
        "name": "lookup_glossary_term",
        "description": (
            "Look up financial or real estate terminology definitions. Covers 70+ terms "
            "across mortgage concepts (LTV, DTI, PITI, PMI, ARM vs fixed), investment metrics "
            "(cap rate, NOI, GRM, cash-on-cash, IRR, DSCR), tax concepts (Prop 13, 1031 "
            "exchange, Section 121, depreciation, capital gains), loan programs (FHA, VA, "
            "conventional, CalHFA, conforming vs jumbo), closing costs (title insurance, "
            "escrow, transfer tax), property types (SFR, condo, TIC, PUD, duplex), "
            "transaction terms (contingency, earnest money, due diligence, disclosures), "
            "valuation (CMA, comps, price per sqft, appraisal gap), construction (setback, "
            "FAR, lot coverage, easement), and market terms (DOM, months of supply, "
            "absorption rate). All terms include Berkeley-specific context. Use this when a "
            "user asks 'what is X' for any financial or real estate concept, or when you need "
            "to explain jargon in your own tool results."
        ),
        "input_schema": {
                "type": "object",
                "properties": {
                        "topic": {
                                "type": "string",
                                "description": "The term to look up. Can be a term key (e.g. 'cap_rate', 'ltv', 'contingency'), a category (e.g. 'mortgage', 'investment_metrics', 'transaction'), or natural language (e.g. 'what is a cap rate', 'explain debt to income ratio')."
                        },
                        "category": {
                                "type": "string",
                                "description": "Optional category filter: 'mortgage', 'investment_metrics', 'tax', 'loan_programs', 'closing_costs', 'berkeley_specific', 'property_types', 'transaction', 'valuation', 'construction', 'market'."
                        }
                },
                "required": [
                        "topic"
                ]
        },
        "block_type": "glossary_info",
        "fact_computer": compute_glossary_facts,
    },
]
