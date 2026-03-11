"""Berkeley real estate regulations knowledge base.

Structured reference data for zoning codes, housing policies, and
development regulations specific to Berkeley, California.  Used by the
Faketor AI chat service via the ``lookup_regulation`` tool.

Sources:
    - Berkeley Municipal Code Title 23 (Zoning Ordinance)
      https://berkeley.municipal.codes/BMC/23
    - City of Berkeley Planning & Development
      https://berkeleyca.gov/construction-development/
    - California Government Code (ADU, SB 9, Middle Housing)
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Zone code definitions
# ---------------------------------------------------------------------------

ZONE_DEFINITIONS: dict[str, dict] = {
    # ---- Residential ----
    "R-1": {
        "name": "Single Family Residential",
        "description": (
            "Allows one single-family home per lot. This is the most common "
            "residential zone in Berkeley, covering roughly 49% of the city's "
            "residential land. ADUs and JADUs are permitted. SB 9 lot splitting "
            "is eligible. Middle Housing allows up to 5 units."
        ),
        "max_units_base": 1,
        "lot_coverage_pct": 45,
        "max_height_ft": 35,
        "adu_eligible": True,
        "sb9_eligible": True,
        "middle_housing_max_units": 5,
        "hillside": False,
    },
    "R-1H": {
        "name": "Single Family Residential — Hillside Overlay",
        "description": (
            "Same permitted uses as R-1 (single-family home), but within the "
            "Hillside Overlay Zone. The 'H' suffix means stricter height limits, "
            "fire safety requirements, vegetation management rules, and view "
            "protection. ADUs are allowed (max 16 ft height). SB 9 lot splitting "
            "is eligible, but Middle Housing is NOT eligible due to hillside "
            "fire hazard concerns."
        ),
        "max_units_base": 1,
        "lot_coverage_pct": 45,
        "max_height_ft": 35,
        "adu_eligible": True,
        "adu_max_height_ft": 16,
        "sb9_eligible": True,
        "middle_housing_max_units": None,
        "hillside": True,
    },
    "R-2": {
        "name": "Restricted Two-Family Residential",
        "description": (
            "Allows one dwelling unit per 2,500 sqft of lot area. Permits "
            "duplexes and single-family homes. ADUs are eligible. Middle Housing "
            "allows up to 6 units. Not eligible for SB 9 (only R-1 zones qualify)."
        ),
        "max_units_base": "1 per 2,500 sqft",
        "lot_coverage_pct": 45,
        "max_height_ft": 35,
        "adu_eligible": True,
        "sb9_eligible": False,
        "middle_housing_max_units": 6,
        "hillside": False,
    },
    "R-2H": {
        "name": "Restricted Two-Family Residential — Hillside Overlay",
        "description": (
            "Same uses as R-2 (1 unit per 2,500 sqft) with Hillside Overlay "
            "restrictions. Stricter height limits and fire safety rules apply. "
            "Middle Housing is NOT eligible in hillside zones."
        ),
        "max_units_base": "1 per 2,500 sqft",
        "lot_coverage_pct": 45,
        "max_height_ft": 35,
        "adu_eligible": True,
        "adu_max_height_ft": 16,
        "sb9_eligible": False,
        "middle_housing_max_units": None,
        "hillside": True,
    },
    "R-2A": {
        "name": "Restricted Multiple-Family Residential",
        "description": (
            "Higher density than R-2: allows one dwelling unit per 1,650 sqft "
            "of lot area. Common in transitional areas between single-family "
            "and multi-family neighborhoods. Middle Housing allows up to 7 units."
        ),
        "max_units_base": "1 per 1,650 sqft",
        "lot_coverage_pct": 45,
        "max_height_ft": 35,
        "adu_eligible": True,
        "sb9_eligible": False,
        "middle_housing_max_units": 7,
        "hillside": False,
    },
    "R-2AH": {
        "name": "Restricted Multiple-Family Residential — Hillside Overlay",
        "description": (
            "Same uses as R-2A (1 unit per 1,650 sqft) with Hillside Overlay "
            "restrictions. Middle Housing is NOT eligible."
        ),
        "max_units_base": "1 per 1,650 sqft",
        "lot_coverage_pct": 45,
        "max_height_ft": 35,
        "adu_eligible": True,
        "adu_max_height_ft": 16,
        "sb9_eligible": False,
        "middle_housing_max_units": None,
        "hillside": True,
    },
    "R-3": {
        "name": "Multiple-Family Residential",
        "description": (
            "Medium-density multi-family zone allowing one unit per 1,500 sqft. "
            "Minimum 3 units. Permits apartments, condos, townhouses. NOT "
            "eligible for Middle Housing (already allows multi-family by right)."
        ),
        "max_units_base": "1 per 1,500 sqft (min 3)",
        "lot_coverage_pct": 50,
        "max_height_ft": 35,
        "adu_eligible": True,
        "sb9_eligible": False,
        "middle_housing_max_units": None,
        "hillside": False,
    },
    "R-3H": {
        "name": "Multiple-Family Residential — Hillside Overlay",
        "description": (
            "Same uses as R-3 with Hillside Overlay restrictions. Multi-family "
            "development with stricter height and fire safety rules."
        ),
        "max_units_base": "1 per 1,500 sqft (min 3)",
        "lot_coverage_pct": 50,
        "max_height_ft": 35,
        "adu_eligible": True,
        "adu_max_height_ft": 16,
        "sb9_eligible": False,
        "middle_housing_max_units": None,
        "hillside": True,
    },
    "R-4": {
        "name": "Multi-Family Residential High Density",
        "description": (
            "High-density residential zone allowing one unit per 1,000 sqft. "
            "Minimum 4 units. Found near transit corridors and commercial areas. "
            "NOT eligible for Middle Housing."
        ),
        "max_units_base": "1 per 1,000 sqft (min 4)",
        "lot_coverage_pct": 55,
        "max_height_ft": 35,
        "adu_eligible": True,
        "sb9_eligible": False,
        "middle_housing_max_units": None,
        "hillside": False,
    },
    "R-4H": {
        "name": "Multi-Family Residential High Density — Hillside Overlay",
        "description": (
            "Same uses as R-4 with Hillside Overlay restrictions."
        ),
        "max_units_base": "1 per 1,000 sqft (min 4)",
        "lot_coverage_pct": 55,
        "max_height_ft": 35,
        "adu_eligible": True,
        "adu_max_height_ft": 16,
        "sb9_eligible": False,
        "middle_housing_max_units": None,
        "hillside": True,
    },
    "R-S": {
        "name": "Residential Southside",
        "description": (
            "Special residential district for the Southside area near UC Berkeley. "
            "Allows a mix of residential uses including single-family, multi-family, "
            "and student housing. Higher density than standard R-1."
        ),
        "hillside": False,
    },
    "R-SH": {
        "name": "Residential Southside — Hillside Overlay",
        "description": "Same uses as R-S with Hillside Overlay restrictions.",
        "hillside": True,
    },
    "R-SMU": {
        "name": "Residential Small-Scale Mixed Use",
        "description": (
            "Allows small-scale mixed-use development in residential areas. "
            "Permits ground-floor commercial with residential above. Typically "
            "found along neighborhood commercial corridors."
        ),
        "hillside": False,
    },
    # ---- Mixed Use / Environmental ----
    "MUR": {
        "name": "Mixed Use Residential",
        "description": (
            "Mixed-use zone allowing residential and compatible commercial uses. "
            "One unit per 1,500 sqft. Up to 60% lot coverage. Middle Housing "
            "allows up to 7 units."
        ),
        "max_units_base": "1 per 1,500 sqft",
        "lot_coverage_pct": 60,
        "middle_housing_max_units": 7,
        "hillside": False,
    },
    "MULI": {
        "name": "Mixed Use Light Industrial",
        "description": (
            "Allows a mix of light industrial, commercial, and residential uses. "
            "Found in West Berkeley's industrial transition areas."
        ),
        "hillside": False,
    },
    "ES-R": {
        "name": "Environmental Safety — Residential",
        "description": (
            "Restrictive hillside zone for areas with significant environmental "
            "constraints (steep slopes, fire risk, landslide hazard). Very low "
            "density: max 20% lot coverage, limited to 1 unit. ADUs limited to "
            "500 sqft max."
        ),
        "max_units_base": 1,
        "lot_coverage_pct": 20,
        "adu_eligible": True,
        "adu_max_sqft": 500,
        "adu_max_height_ft": 16,
        "sb9_eligible": False,
        "middle_housing_max_units": None,
        "hillside": True,
    },
    # ---- Commercial ----
    "C-W": {
        "name": "West Berkeley Commercial",
        "description": (
            "Commercial district for West Berkeley. Allows retail, office, "
            "light manufacturing, and mixed-use residential. Reflects the area's "
            "historic industrial-to-commercial transition."
        ),
        "hillside": False,
    },
    "C-SA": {
        "name": "South Area Commercial",
        "description": (
            "Commercial district implementing the South Berkeley Area Plan. "
            "Allows retail, services, and mixed-use residential. Vehicle service "
            "stations not permitted; vehicle sales must be indoor only."
        ),
        "hillside": False,
    },
    "C-AC": {
        "name": "Ashby BART Commercial",
        "description": (
            "Commercial district around the Ashby BART station. Oriented toward "
            "transit-accessible mixed-use development."
        ),
        "hillside": False,
    },
    "C-N": {
        "name": "Neighborhood Commercial",
        "description": (
            "Small-scale commercial zone serving immediate neighborhood needs. "
            "Allows retail shops, restaurants, personal services, with "
            "residential uses above ground floor."
        ),
        "hillside": False,
    },
    "C-NS": {
        "name": "North Shattuck Commercial",
        "description": (
            "Commercial district for the North Shattuck corridor (Gourmet Ghetto "
            "area). Restaurants, specialty retail, and mixed-use development."
        ),
        "hillside": False,
    },
    "C-C": {
        "name": "City Center Commercial",
        "description": (
            "Intense commercial zone in downtown Berkeley. Allows offices, retail, "
            "restaurants, entertainment, and high-density residential."
        ),
        "hillside": False,
    },
    "C-T": {
        "name": "Telegraph Avenue Commercial",
        "description": (
            "Commercial district along Telegraph Avenue near UC Berkeley. "
            "Student-oriented retail, restaurants, and mixed-use."
        ),
        "hillside": False,
    },
    "C-U": {
        "name": "University Avenue Commercial",
        "description": (
            "Commercial district along University Avenue. Mixed-use corridor "
            "connecting downtown to the waterfront."
        ),
        "hillside": False,
    },
    "C-SO": {
        "name": "Solano Avenue Commercial",
        "description": (
            "Commercial district along Solano Avenue. Neighborhood retail, "
            "restaurants, and services with a small-town character."
        ),
        "hillside": False,
    },
    "C-DMU Buffer": {
        "name": "Downtown Mixed Use — Buffer",
        "description": (
            "Transition zone between downtown core and surrounding residential. "
            "Lower intensity mixed-use than the core DMU zones."
        ),
        "hillside": False,
    },
    "C-DMU Core": {
        "name": "Downtown Mixed Use — Core",
        "description": (
            "Highest intensity downtown zone. Allows tall mixed-use buildings, "
            "offices, residential towers, and major commercial uses."
        ),
        "hillside": False,
    },
    "C-DMU Outer Core": {
        "name": "Downtown Mixed Use — Outer Core",
        "description": (
            "Mid-intensity downtown zone between the core and buffer. Mixed-use "
            "with moderate height allowances."
        ),
        "hillside": False,
    },
    "C-E": {
        "name": "Elmwood Commercial",
        "description": (
            "Small commercial district in the Elmwood neighborhood. Local retail "
            "and services with residential above."
        ),
        "hillside": False,
    },
    "M": {
        "name": "Manufacturing",
        "description": (
            "Industrial/manufacturing zone. Allows factories, warehouses, and "
            "heavy commercial uses. Limited residential."
        ),
        "hillside": False,
    },
}

# H suffix commercial variants share the same description pattern
for _code in ["C-N(H)", "C-NS(H)"]:
    _base = _code.replace("(H)", "")
    if _base in ZONE_DEFINITIONS:
        ZONE_DEFINITIONS[_code] = {
            **ZONE_DEFINITIONS[_base],
            "name": ZONE_DEFINITIONS[_base]["name"] + " — Hillside Overlay",
            "description": (
                ZONE_DEFINITIONS[_base]["description"]
                + " Hillside Overlay restrictions apply."
            ),
            "hillside": True,
        }


# ---------------------------------------------------------------------------
# Regulation categories
# ---------------------------------------------------------------------------

REGULATIONS: dict[str, dict] = {
    "zoning_codes": {
        "title": "Berkeley Zoning Code Definitions",
        "summary": (
            "Berkeley has 30+ zoning districts organized into Residential (R-), "
            "Commercial (C-), Mixed Use (MU-/MULI), Environmental Safety (ES-R), "
            "and Manufacturing (M) categories. The 'H' suffix denotes the "
            "Hillside Overlay Zone with stricter height, fire safety, and view "
            "protection rules."
        ),
        "details": (
            "Berkeley's zoning code (Title 23 of the Municipal Code) was "
            "comprehensively updated in December 2021 — the first major revision "
            "since 1999.\n\n"
            "ZONE CODE SUFFIXES:\n"
            "- 'H' = Hillside Overlay — applies additional height restrictions, "
            "fire safety requirements, vegetation management, and view protection "
            "rules. Hillside zones are generally NOT eligible for Middle Housing "
            "due to fire hazard concerns.\n"
            "- 'A' in R-2A/R-2AH = higher density variant (1 unit per 1,650 sqft "
            "vs 2,500 sqft in R-2).\n\n"
            "Use lookup_regulation with a specific zone_code (e.g., 'R-1H') "
            "for details on individual zones."
        ),
        "source": "Berkeley Municipal Code Title 23 — https://berkeley.municipal.codes/BMC/23",
    },
    "hillside_overlay": {
        "title": "Hillside Overlay Zone (H Suffix)",
        "summary": (
            "The 'H' suffix in Berkeley zoning codes designates the Hillside "
            "Overlay Zone — a regulatory overlay that adds restrictions on top "
            "of the base zoning district for fire safety, slope stability, and "
            "neighborhood character."
        ),
        "details": (
            "WHAT THE H SUFFIX MEANS:\n"
            "The 'H' in zones like R-1H, R-2H, R-2AH, R-3H, and R-4H stands "
            "for Hillside Overlay Zone (BMC 23.210.020). It is NOT a height "
            "designation — it is a geographic overlay applied to properties in "
            "Berkeley's hillside areas.\n\n"
            "KEY RESTRICTIONS:\n"
            "- Stricter height limits than flatland equivalents\n"
            "- Fire safety requirements (vegetation management, fire-resistant "
            "materials, emergency access)\n"
            "- View protection rules — new construction must not unreasonably "
            "obstruct views from neighboring properties\n"
            "- Slope-based development standards — steeper slopes face more "
            "restrictions\n"
            "- When overlay standards conflict with the base district, the "
            "overlay rules prevail\n\n"
            "IMPACT ON DEVELOPMENT:\n"
            "- Middle Housing Ordinance does NOT apply to hillside zones\n"
            "- ADUs are permitted but limited to 16 ft height (1 story)\n"
            "- SB 9 lot splitting is eligible in R-1H\n"
            "- ES-R (Environmental Safety — Residential) is the most restrictive "
            "hillside zone: only 20% lot coverage, ADUs limited to 500 sqft\n\n"
            "GEOGRAPHIC CONTEXT:\n"
            "Hillside zones primarily cover the Berkeley Hills east of the "
            "Hayward Fault, including areas affected by the 1923 fire and within "
            "active fire hazard severity zones."
        ),
        "key_numbers": {
            "adu_max_height_hillside": "16 ft (1 story)",
            "es_r_lot_coverage": "20%",
            "es_r_adu_max_sqft": "500 sqft",
        },
        "source": "BMC 23.210.020 — https://berkeley.municipal.codes/BMC/23.210.020",
    },
    "adu_rules": {
        "title": "Accessory Dwelling Unit (ADU) & JADU Regulations",
        "summary": (
            "Berkeley permits ADUs up to 850 sqft (1BR) or 1,000 sqft (2BR), "
            "plus Junior ADUs up to 500 sqft within the existing home. One story "
            "max, 16 ft height. Ministerial approval (no public hearing)."
        ),
        "details": (
            "SIZE LIMITS:\n"
            "- ADU (1 bedroom): up to 850 sqft\n"
            "- ADU (2 bedrooms): up to 1,000 sqft\n"
            "- Junior ADU (JADU): up to 500 sqft, must be entirely within the "
            "existing or proposed single-family residence\n"
            "- In ES-R zones: ADU limited to 500 sqft\n\n"
            "HEIGHT & STORIES:\n"
            "- Maximum 1 story\n"
            "- 16 ft height limit (all zones including hillside)\n"
            "- Detached ADU: must comply with lot coverage limits\n\n"
            "APPROVAL PROCESS:\n"
            "- Ministerial review — no public hearing or discretionary approval\n"
            "- Building permit required\n"
            "- State law (CA Gov Code 65852.2) preempts most local barriers\n\n"
            "RESTRICTIONS:\n"
            "- Short-term rental prohibited (deed restriction)\n"
            "- Cannot be sold separately from primary residence (except condos "
            "under AB 1033)\n"
            "- Parking: max 1 space per ADU bedroom; no parking required if "
            "within 1/2 mile of transit\n\n"
            "ELIGIBILITY:\n"
            "- Allowed in all residential zones (R-1 through R-4, MU-R, ES-R)\n"
            "- One ADU + one JADU per single-family lot\n"
            "- Multi-family properties: up to 2 detached ADUs + conversion of "
            "non-livable space (laundry rooms, storage, etc.)"
        ),
        "key_numbers": {
            "max_adu_1br_sqft": 850,
            "max_adu_2br_sqft": 1000,
            "max_jadu_sqft": 500,
            "max_height_ft": 16,
            "max_stories": 1,
            "parking_per_bedroom": 1,
        },
        "source": "BMC Ch. 23.306 — https://berkeley.municipal.codes/BMC/23.306",
    },
    "sb9_lot_splitting": {
        "title": "SB 9 Urban Lot Splitting",
        "summary": (
            "SB 9 allows splitting a single-family lot into two parcels and "
            "building a duplex on each, for up to 4 total units. Only eligible "
            "in R-1 and R-1H zones with a minimum 2,400 sqft lot."
        ),
        "details": (
            "ELIGIBLE ZONES:\n"
            "- R-1 (Single Family Residential)\n"
            "- R-1H (Single Family Residential — Hillside Overlay)\n"
            "- NOT eligible in R-2, R-3, R-4, or commercial zones\n\n"
            "LOT REQUIREMENTS:\n"
            "- Minimum existing lot size: 2,400 sqft\n"
            "- Each resulting lot must be at least 1,200 sqft\n"
            "- No flag lots or lots without street frontage\n\n"
            "WHAT YOU CAN BUILD:\n"
            "- Up to 2 units per resulting lot (duplex)\n"
            "- Maximum 4 total units (2 lots x 2 units each)\n"
            "- 800 sqft minimum per unit\n\n"
            "APPROVAL PROCESS:\n"
            "- Ministerial approval — no public hearing\n"
            "- No discretionary review\n"
            "- Cannot be denied if all objective standards are met\n\n"
            "RESTRICTIONS:\n"
            "- Owner must occupy one unit for 3 years after split\n"
            "- Cannot be used on properties withdrawn from rent control "
            "within past 15 years (Ellis Act)\n"
            "- Cannot demolish rent-stabilized housing\n"
            "- Not available for historic landmarks\n"
            "- Units cannot be used for short-term rentals"
        ),
        "key_numbers": {
            "min_lot_sqft": 2400,
            "min_resulting_lot_sqft": 1200,
            "max_total_units": 4,
            "min_unit_sqft": 800,
            "owner_occupancy_years": 3,
        },
        "source": "CA Government Code 65852.21, 66411.7",
    },
    "middle_housing": {
        "title": "Middle Housing Ordinance",
        "summary": (
            "Effective November 1, 2025, Berkeley's Middle Housing Ordinance "
            "allows duplexes through 8-plexes in most residential zones. "
            "Projects with 2-6 units meeting objective standards get 30-day "
            "ministerial approval."
        ),
        "details": (
            "EFFECTIVE DATE: November 1, 2025\n\n"
            "ELIGIBLE ZONES AND UNIT CAPS:\n"
            "- R-1: up to 5 units\n"
            "- R-2: up to 6 units\n"
            "- R-2A: up to 7 units\n"
            "- MU-R/MUR: up to 7 units\n"
            "- Maximum 3 stories and 8 units in any zone\n\n"
            "NOT ELIGIBLE:\n"
            "- Hillside Overlay zones (R-1H, R-2H, R-2AH, R-3H, R-4H)\n"
            "- High fire hazard severity zones in Berkeley Hills\n"
            "- R-3, R-4 zones (already allow multi-family by right)\n\n"
            "APPROVAL PROCESS:\n"
            "- 2-6 units meeting objective development standards: 30-day "
            "ministerial approval (no public hearing)\n"
            "- 7-8 units or projects not meeting standards: standard "
            "discretionary review\n\n"
            "LOT COVERAGE:\n"
            "- Increased to 60% for Middle Housing projects (vs 45% standard)\n\n"
            "AFFORDABILITY BONUS:\n"
            "- Additional units allowed if affordable units are included\n\n"
            "EXPECTED IMPACT:\n"
            "- Estimated ~1,700 new units over 8 years (conservative)\n"
            "- Applies to Downtown, Elmwood, Fourth St., North Shattuck, "
            "Solano Ave., Telegraph Ave., Lorin, West Berkeley, San Pablo Ave., "
            "University Ave."
        ),
        "key_numbers": {
            "effective_date": "November 1, 2025",
            "r1_max_units": 5,
            "r2_max_units": 6,
            "r2a_max_units": 7,
            "max_stories": 3,
            "max_units_any_zone": 8,
            "lot_coverage_pct": 60,
            "fast_track_max_units": 6,
            "fast_track_days": 30,
        },
        "source": (
            "Berkeley Middle Housing Zoning Changes — "
            "https://berkeleyca.gov/construction-development/land-use-development/"
            "general-plan-and-area-plans/middle-housing-zoning"
        ),
    },
    "beso": {
        "title": "Building Emissions Saving Ordinance (BESO)",
        "summary": (
            "At the point of sale, Berkeley requires an energy assessment for "
            "buildings over 600 sqft. Sellers must obtain an energy audit; if "
            "upgrades are needed, a $5,000 escrow deposit may be required."
        ),
        "details": (
            "WHEN TRIGGERED:\n"
            "- At point of sale for residential buildings over 600 sqft\n"
            "- Applies to both single-family and multi-family properties\n\n"
            "REQUIREMENTS:\n"
            "- Seller must obtain a Home Energy Score or energy audit\n"
            "- Energy audit cost: typically $300-$750\n"
            "- If upgrades are recommended, a $5,000 escrow deposit may be "
            "required to ensure compliance\n\n"
            "POTENTIAL UPGRADE COSTS:\n"
            "- Minor (insulation, weatherstripping): $2,000-$5,000\n"
            "- Moderate (water heater, windows): $5,000-$15,000\n"
            "- Major (HVAC replacement, extensive insulation): $15,000-$25,000+\n\n"
            "EXEMPTIONS:\n"
            "- New construction (already meets current energy code)\n"
            "- Recent major renovations with updated energy systems\n\n"
            "BUYER IMPACT:\n"
            "- Factor BESO costs into your offer price\n"
            "- Request the energy audit report during due diligence\n"
            "- Negotiate who pays for required upgrades"
        ),
        "key_numbers": {
            "min_building_sqft": 600,
            "audit_cost_range": "$300-$750",
            "escrow_deposit": "$5,000",
            "upgrade_cost_range": "$2,000-$25,000+",
        },
        "source": "Berkeley BESO — https://berkeleyca.gov/construction-development/green-building/beso",
    },
    "transfer_tax": {
        "title": "City of Berkeley Transfer Tax",
        "summary": (
            "Berkeley charges a transfer tax on property sales: 1.5% for "
            "properties up to $1.8M and 2.5% for properties above $1.8M. "
            "A partial rebate is available for seismic retrofitting."
        ),
        "details": (
            "TAX RATES (as of Measure P, 2024):\n"
            "- Up to $1,800,000: 1.5% of sale price\n"
            "- Above $1,800,000: 2.5% of sale price\n\n"
            "NOTE: The rate applies to the ENTIRE sale price based on which "
            "tier it falls into, not incrementally.\n\n"
            "EXAMPLES:\n"
            "- $1,200,000 sale: $18,000 tax (1.5%)\n"
            "- $2,000,000 sale: $50,000 tax (2.5%)\n"
            "- $3,000,000 sale: $75,000 tax (2.5%)\n\n"
            "SEISMIC REBATE:\n"
            "- Up to 1/3 of the city portion (~0.5% of sale price up to $1.8M "
            "tier) may be rebated for qualified seismic strengthening work\n"
            "- Must complete seismic retrofit within specified timeframe\n\n"
            "WHO PAYS:\n"
            "- Traditionally split between buyer and seller, but negotiable\n"
            "- Often the seller pays in Berkeley's market\n\n"
            "COMPARISON:\n"
            "- Alameda County also charges a separate transfer tax\n"
            "- Berkeley's rates are among the highest in the East Bay"
        ),
        "key_numbers": {
            "rate_up_to_1_8m": "1.5%",
            "rate_above_1_8m": "2.5%",
            "threshold": "$1,800,000",
            "seismic_rebate": "Up to 1/3 of city portion",
        },
        "source": (
            "City of Berkeley Transfer Tax — "
            "https://berkeleyca.gov/city-services/report-pay/property-transfer-tax"
        ),
    },
    "rent_control": {
        "title": "Berkeley Rent Control & Tenant Protections",
        "summary": (
            "Berkeley has one of the strongest rent control laws in California, "
            "covering approximately 29,000 rental units. Vacancy decontrol has "
            "been in effect since 1999."
        ),
        "details": (
            "COVERAGE:\n"
            "- Approximately 29,000 rental units covered\n"
            "- Over 20,000 units have regulated rents\n"
            "- Governed by the Rent Stabilization and Eviction for Good Cause "
            "Ordinance (BMC Ch. 13.76)\n\n"
            "EXEMPT PROPERTIES:\n"
            "- Units built after June 1980 (Costa-Hawkins)\n"
            "- Single-family homes and condos (if separately owned)\n"
            "- Owner-occupied duplexes and triplexes (owner in one unit)\n"
            "- Government-subsidized housing\n"
            "- Newly constructed ADUs (for 15 years per AB 1482)\n\n"
            "VACANCY DECONTROL:\n"
            "- Since January 1999 (Costa-Hawkins Act)\n"
            "- Landlords can set rent at market rate for new tenancies\n"
            "- Once tenant moves in, rent increases are regulated\n\n"
            "RENT INCREASE LIMITS:\n"
            "- Annual adjustment set by Rent Board (typically 2-5%)\n"
            "- Based on Consumer Price Index (CPI)\n"
            "- Capital improvement pass-throughs allowed with Board approval\n\n"
            "JUST CAUSE EVICTION:\n"
            "- Landlords must have legally specified cause to evict\n"
            "- Includes non-payment, lease violation, owner move-in, "
            "Ellis Act withdrawal\n"
            "- Relocation payments required for no-fault evictions\n\n"
            "INVESTOR RELEVANCE:\n"
            "- Rent control affects cash flow projections for investment properties\n"
            "- Vacancy decontrol means turnover is financially significant\n"
            "- New ADUs are exempt for 15 years — attractive for investors"
        ),
        "key_numbers": {
            "units_covered": "~29,000",
            "units_regulated_rents": "~20,000",
            "vacancy_decontrol_since": "January 1999",
            "adu_exemption_years": 15,
        },
        "source": (
            "Berkeley Rent Board — "
            "https://rentboard.berkeleyca.gov/rights-responsibilities/rent-control-101"
        ),
    },
    "permitting": {
        "title": "Berkeley Permitting Process Overview",
        "summary": (
            "Berkeley permits fall into two categories: ministerial (staff-level, "
            "no hearing) and discretionary (requires public hearing). ADUs and "
            "SB 9 projects get ministerial approval."
        ),
        "details": (
            "PERMIT TYPES:\n"
            "- Building Permit: required for all construction/renovation\n"
            "- Use Permit (UP): for uses not permitted by right\n"
            "- Administrative Use Permit (AUP): simplified discretionary review\n"
            "- Zoning Certificate: confirms permitted use\n\n"
            "MINISTERIAL (NO HEARING):\n"
            "- ADUs and JADUs\n"
            "- SB 9 lot splits and duplexes\n"
            "- Middle Housing projects (2-6 units meeting objective standards)\n"
            "- Interior renovations\n"
            "- Like-for-like replacements\n\n"
            "DISCRETIONARY (PUBLIC HEARING):\n"
            "- New multi-family construction (7+ units)\n"
            "- Commercial projects\n"
            "- Variance requests\n"
            "- Projects not meeting objective development standards\n\n"
            "TYPICAL TIMELINES:\n"
            "- ADU permit: 60 days (state-mandated)\n"
            "- SB 9: 60 days\n"
            "- Middle Housing (2-6 units): 30 days\n"
            "- Standard building permit: 4-8 weeks for plan check\n"
            "- Use Permit/discretionary: 3-6 months or longer\n\n"
            "FEES:\n"
            "- Vary by project scope and valuation\n"
            "- Building permit fees based on construction valuation\n"
            "- Plan check fees (typically 65-80% of permit fee)\n"
            "- Traffic engineering review: minimum $90\n"
            "- School impact fees, park fees may apply for new units"
        ),
        "key_numbers": {
            "adu_permit_days": 60,
            "sb9_permit_days": 60,
            "middle_housing_fast_track_days": 30,
            "standard_plan_check_weeks": "4-8",
            "discretionary_months": "3-6+",
        },
        "source": (
            "City of Berkeley Permit Process — "
            "https://berkeleyca.gov/construction-development/permits-design-parameters/permit-process"
        ),
    },
}


# ---------------------------------------------------------------------------
# Lookup function
# ---------------------------------------------------------------------------

# Pre-compiled pattern for extracting zone codes from free text
_ZONE_CODE_RE = re.compile(
    r"\b(R-[1-5][AH]*|ES-R|MU-?R|MULI|C-[A-Z]{1,3}(?:\s*\(H\))?|M)\b",
    re.IGNORECASE,
)

# Keyword → category mapping for fuzzy matching
_KEYWORD_MAP: dict[str, str] = {
    "adu": "adu_rules",
    "accessory dwelling": "adu_rules",
    "jadu": "adu_rules",
    "junior adu": "adu_rules",
    "granny flat": "adu_rules",
    "in-law": "adu_rules",
    "sb9": "sb9_lot_splitting",
    "sb 9": "sb9_lot_splitting",
    "lot split": "sb9_lot_splitting",
    "lot splitting": "sb9_lot_splitting",
    "middle housing": "middle_housing",
    "duplex": "middle_housing",
    "triplex": "middle_housing",
    "fourplex": "middle_housing",
    "cottage court": "middle_housing",
    "beso": "beso",
    "energy audit": "beso",
    "energy assessment": "beso",
    "emissions": "beso",
    "transfer tax": "transfer_tax",
    "city tax": "transfer_tax",
    "real estate tax": "transfer_tax",
    "rent control": "rent_control",
    "rent stabilization": "rent_control",
    "tenant": "rent_control",
    "eviction": "rent_control",
    "vacancy decontrol": "rent_control",
    "permit": "permitting",
    "permitting": "permitting",
    "building permit": "permitting",
    "plan check": "permitting",
    "hillside": "hillside_overlay",
    "h suffix": "hillside_overlay",
    "hill overlay": "hillside_overlay",
    "fire hazard": "hillside_overlay",
    "zoning": "zoning_codes",
    "zone code": "zoning_codes",
    "zoning code": "zoning_codes",
}


def lookup_regulation(
    topic: str,
    zone_code: Optional[str] = None,
) -> dict:
    """Look up Berkeley regulation by topic and optional zone code.

    Args:
        topic: Regulation topic — a category key (e.g., ``"adu_rules"``) or
            natural language (e.g., ``"what is R-1H"``).
        zone_code: Optional zone code for zone-specific lookups.

    Returns:
        Dict with matched regulation content including ``title``,
        ``summary``, ``details``, ``source``, and optionally ``zone``.
    """
    topic_lower = topic.strip().lower()

    # 1. Exact category key match
    if topic_lower in REGULATIONS:
        result = dict(REGULATIONS[topic_lower])
        result["category"] = topic_lower
        # If zone_code provided with zoning_codes, add specific zone info
        if zone_code and topic_lower == "zoning_codes":
            zone_upper = zone_code.strip().upper()
            if zone_upper in ZONE_DEFINITIONS:
                result["zone"] = {zone_upper: ZONE_DEFINITIONS[zone_upper]}
        return result

    # 2. Zone code extraction — from explicit parameter or from topic text
    target_zone = None
    if zone_code:
        target_zone = zone_code.strip().upper()
    else:
        match = _ZONE_CODE_RE.search(topic)
        if match:
            target_zone = match.group(1).upper()

    if target_zone and target_zone in ZONE_DEFINITIONS:
        zone_info = ZONE_DEFINITIONS[target_zone]
        return {
            "category": "zoning_codes",
            "title": f"Zone {target_zone}: {zone_info['name']}",
            "summary": zone_info["description"],
            "details": zone_info["description"],
            "zone": {target_zone: zone_info},
            "hillside_overlay": zone_info.get("hillside", False),
            "source": "Berkeley Municipal Code Title 23",
            "related": (
                ["hillside_overlay"] if zone_info.get("hillside") else []
            ),
        }

    # 3. Keyword matching
    for keyword, category_key in _KEYWORD_MAP.items():
        if keyword in topic_lower:
            result = dict(REGULATIONS[category_key])
            result["category"] = category_key
            return result

    # 4. Not found — return available categories
    return {
        "category": None,
        "title": "Topic Not Found",
        "summary": f"No regulation found matching '{topic}'.",
        "available_categories": list(REGULATIONS.keys()),
        "available_zones": sorted(ZONE_DEFINITIONS.keys()),
        "hint": (
            "Try a category key like 'adu_rules', 'transfer_tax', "
            "'hillside_overlay', or a zone code like 'R-1H', 'C-SA'."
        ),
    }
