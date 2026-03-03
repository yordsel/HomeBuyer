"""Neighborhood name normalization.

Handles the messy MLS LOCATION field by mapping known spellings/abbreviations
to canonical neighborhood names. Uses a 2-layer approach:
1. Exact alias lookup (case-insensitive)
2. Fuzzy string matching for close typos
"""

import difflib
import logging
import re
from typing import Optional

from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical neighborhood names and their known aliases
# Keys are canonical names; values are lists of known alternative spellings
# that appear in Redfin's LOCATION field.
# ---------------------------------------------------------------------------
NEIGHBORHOOD_ALIASES: dict[str, list[str]] = {
    "North Berkeley": [
        "N Berkeley", "N. Berkeley", "N BERKELEY", "NOBE", "North Berk",
        "NORTH BERK", "NORTHSIDE", "NORTH SIDE", "Indian Rock Area",
        "INDIAN ROCK", "Indian Rock", "NORTH CAMPUS", "NORTH/WEST",
    ],
    "South Berkeley": [
        "S Berkeley", "S. Berkeley", "S BERKELEY", "So Berkeley",
        "SO BERKELEY", "SOUTH BERK",
    ],
    "West Berkeley": [
        "W Berkeley", "W. Berkeley", "W BERKELEY", "WEST BERK",
    ],
    "Central Berkeley": [
        "CENTRAL BERK", "CENTRAL", "BERKELEY CENTRAL",
    ],
    "Downtown Berkeley": [
        "Downtown", "DOWNTOWN", "Downtown Berk", "BERKELEY DOWNTOWN",
    ],
    "Berkeley Hills": [
        "Berk Hills", "BERK HILLS", "The Hills", "THE HILLS",
        "BERKELEY HLS", "BERKELEY HILL", "GRIZZLY PEAK", "BERKELEY VIEW TE",
        "BERKELEY VIEW", "BERKELEY VIEWTE",
    ],
    "Claremont": [
        "CLAREMONT HILLS", "CLAREMONT HGHTS", "CLAREMONT HEIGHT",
        "CLAREMONT HTS", "CLAREMNT HGHTS", "CLAREMONT COURT",
        "CLAREMONT KNOLLS", "Claremont Hills", "Claremont Elmwood",
    ],
    "Elmwood": [
        "ELMWOOD DISTRICT", "Elmwood District", "LOWER ELMWOOD", "BAJA ELMWOOD",
        "UPPER ELMWOOD",
    ],
    "Thousand Oaks": [
        "1000 Oaks", "1000  0AKS", "1000 OAK", "THOUSAND OAK",
        "THOUSAND  OAKS", "1000OAKS", "1000  OAKS", "1000 OAKS HEIGHT",
        "1000 OAKS HEIGHTS",
    ],
    "Rockridge": [
        "Rock Ridge", "ROCK RIDGE", "ROCKRIDGE/UPPER",
    ],
    "Northbrae": [
        "NORTH BRAE", "North Brae",
    ],
    "Westbrae": [
        "WEST BRAE", "West Brae",
    ],
    "Cragmont": [
        "CRAG MONT", "Crag Mont", "NORTH CRAGMONT",
    ],
    "Poets Corner": [
        "POET'S CORNER", "POETS' CORNER", "Poet's Corner", "Poets' Corner",
        "POETS CORNER",
    ],
    "San Pablo Park": [
        "SAN PABLO PK", "San Pablo Pk",
    ],
    "Lorin": [
        "LORIN DISTRICT", "Lorin District",
    ],
    "Gourmet Ghetto": [
        "NORTH SHATTUCK", "North Shattuck", "GOURMET DISTRICT",
        "Gourmet District",
    ],
    "Solano Avenue": [
        "SOLANO AVE", "Solano Ave", "SOLANO",
    ],
    "Gilman District": [
        "GILMAN", "Gilman",
    ],
    "Le Conte": [
        "LE CONTE", "LECONTE",
    ],
    "Monterey Market": [
        "MONTEREY MKT", "Monterey Mkt", "MONTEREY/HOPKINS",
    ],
    "Southside": [
        "SOUTH SIDE", "South Side", "SOUTH CAMPUS",
        "State University Homestead Association", "Stanyan Park",
        "UNIVERSITY CMPUS",
    ],
    "Fourth Street": [
        "4TH STREET", "4th Street", "4TH ST",
    ],
    "Panoramic Hill": [
        "PANORAMIC", "Panoramic",
    ],
    "Cedar-Rose": [
        "CEDAR ROSE", "Cedar Rose",
    ],
    "Bateman": [
        "BATEMAN NEIGHBORHOOD", "ELMWOOD/BATEMAN",
    ],
    "Ocean View": [
        "OCEANVIEW", "Ocean View", "OCEAN VW",
    ],
    "Bushrod": [
        "BUSHROD PARK",
    ],
    "Southwest Berkeley": [
        "SW BERKELEY", "SW Berkeley",
    ],
    # --- Additional micro-neighborhoods and MLS variants ---
    "Tilden Park": [
        "TILDEN PARK AREA", "TILDEN VIEWS",
    ],
    "Strawberry Creek": [
        "STRAWBERRY CREEK",
    ],
    "Live Oak Park": [
        "LIVE OAK PARK",
    ],
    "Willard": [
        "ELMWOOD/WILLARD",
    ],
    "University Gardens": [
        "UNIVERSITY GDNS", "UNIV. GARDENS",
    ],
    "Peralta Park": [
        "PERALTA PARK",
    ],
    "Marin Circle": [
        "MARIN CIRCLE",
    ],
    "Curtis Tract": [
        "CURTIS TRACT",
    ],
    "Arch Street": [
        "ARCH ST",
    ],
    "Dwight-Derby": [
        "DWIGHT PLACE",
    ],
    "Regents Park": [
        "REGENTS PARK",
    ],
    "Woodmont": [
        "WOODMONT",
    ],
    "Twain-Harte": [
        "Twichell",
    ],
    "Tamalpais": [
        "TAMALPAIS ROAD",
    ],
    "McGee-Spaulding": [
        "MCGEE'S FARM",
    ],
    "Hiller Highlands": [
        "HILLER HIGHLANDS",
    ],
    "Arlington": [
        "ARLINGTON HEIGHT",
    ],
    "Chestnut": [
        "CHESTNUT",
    ],
    "West End": [
        "WEST END",
    ],
    "Berkeley Marina": [
        "Berkeley Marina",
    ],
}

# Pre-build the case-insensitive lookup
_ALIAS_LOOKUP: dict[str, str] = {}


def _build_alias_lookup() -> dict[str, str]:
    """Build a case-insensitive mapping from every alias to canonical name."""
    global _ALIAS_LOOKUP
    if _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP

    for canonical, aliases in NEIGHBORHOOD_ALIASES.items():
        # Map the canonical name itself
        _ALIAS_LOOKUP[canonical.lower().strip()] = canonical
        for alias in aliases:
            _ALIAS_LOOKUP[alias.lower().strip()] = canonical

    return _ALIAS_LOOKUP


def normalize_neighborhood(raw_name: str) -> Optional[str]:
    """Normalize a raw neighborhood name to its canonical form.

    Tries exact alias match first, then fuzzy matching.
    Returns None if no match found (will need geocoding).

    Args:
        raw_name: The raw LOCATION value from Redfin.

    Returns:
        The canonical neighborhood name, or None.
    """
    if not raw_name or not raw_name.strip():
        return None

    lookup = _build_alias_lookup()
    cleaned = raw_name.strip().lower()

    # Layer 1: Exact alias match
    if cleaned in lookup:
        return lookup[cleaned]

    # Also try title-cased version (some entries are already canonical)
    title_cleaned = raw_name.strip().title()
    if title_cleaned.lower() in lookup:
        return lookup[title_cleaned.lower()]

    # Skip fuzzy matching for generic/numeric values that should go to geocoding
    # "Berkeley Map Area N", pure numbers, "Not Listed", county names, etc.
    if _should_skip_fuzzy(cleaned):
        return None

    # Layer 2: Fuzzy matching
    canonical_names = list(NEIGHBORHOOD_ALIASES.keys())
    matches = difflib.get_close_matches(
        raw_name.strip(),
        canonical_names,
        n=1,
        cutoff=0.7,  # 70% similarity threshold
    )
    if matches:
        logger.debug("Fuzzy matched '%s' -> '%s'", raw_name, matches[0])
        return matches[0]

    # Also try fuzzy matching against all aliases
    all_aliases = list(lookup.keys())
    matches = difflib.get_close_matches(
        cleaned,
        all_aliases,
        n=1,
        cutoff=0.75,
    )
    if matches:
        canonical = lookup[matches[0]]
        logger.debug("Fuzzy alias matched '%s' -> '%s'", raw_name, canonical)
        return canonical

    return None


# Patterns that should skip fuzzy matching and go straight to geocoding
_SKIP_FUZZY_PATTERNS = [
    re.compile(r"^berkeley map area\s*\d+$", re.IGNORECASE),
    re.compile(r"^\d+$"),  # Pure numeric codes like "21103", "11701"
    re.compile(r"^not listed$", re.IGNORECASE),
    re.compile(r"^alameda", re.IGNORECASE),  # "ALAMEDA COUNTY", "ALAMEDA", etc.
    re.compile(r"^county/", re.IGNORECASE),  # "County/Alameda Area"
    re.compile(r"^oakland", re.IGNORECASE),  # Oakland zip codes, etc.
    re.compile(r"^berk\s*-\s*berkeley$", re.IGNORECASE),  # "BERK - Berkeley"
    re.compile(r"alameda to \d+", re.IGNORECASE),  # "Alameda to 280"
    re.compile(r"^upper kensington$", re.IGNORECASE),  # Not Berkeley proper
    re.compile(r"^kensington$", re.IGNORECASE),  # Not Berkeley proper
]


def _should_skip_fuzzy(cleaned_name: str) -> bool:
    """Return True if this raw name should skip fuzzy matching.

    These are generic/numeric values that can't be reliably fuzzy-matched
    and should only be resolved via spatial geocoding using lat/long.
    """
    return any(pat.search(cleaned_name) for pat in _SKIP_FUZZY_PATTERNS)


def normalize_all(db: Database) -> tuple[int, int]:
    """Normalize neighborhoods for all property_sales rows missing one.

    Returns:
        (normalized_count, remaining_null_count)
    """
    rows = db.get_sales_missing_neighborhood()
    logger.info("Found %d sales with missing neighborhood. Normalizing...", len(rows))

    updates: list[tuple[str, int]] = []
    still_null = 0

    for row in rows:
        raw = row.get("neighborhood_raw")
        canonical = normalize_neighborhood(raw) if raw else None

        if canonical:
            updates.append((canonical, row["id"]))
        else:
            still_null += 1

    if updates:
        db.update_neighborhoods_batch(updates)
        logger.info("Normalized %d neighborhoods via alias/fuzzy matching.", len(updates))

    if still_null:
        logger.info(
            "%d sales still missing neighborhood (need geocoding).", still_null
        )

    return len(updates), still_null
