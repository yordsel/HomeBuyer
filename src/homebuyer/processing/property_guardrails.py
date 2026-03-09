"""Property-type-aware analysis guardrails.

Provides a centralized applicability matrix that maps
(analysis_type, property_category, record_type) to an applicability status.
Both backend services and frontend UI consult this matrix to prevent
running analyses that don't make sense for a given property type.

For example:
- ADU/SB9 analysis should NOT run on condos (owner doesn't control the lot)
- Improvement simulation should NOT run on vacant land (no structure)
- Rental income analysis should NOT run on commercial properties
"""

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Applicability(Enum):
    """Whether an analysis type applies to a property category."""

    APPLICABLE = "applicable"
    RESTRICTED = "restricted"  # Partially applicable with caveats
    NOT_APPLICABLE = "not_applicable"


# ---- Analysis types matching tool / endpoint names ----
ANALYSIS_TYPES = [
    "price_prediction",
    "comparables",
    "neighborhood_stats",
    "market_summary",
    "sell_vs_hold",
    "development_potential",
    "improvement_simulation",
    "rental_income",
    "investment_scenarios",
]

# ---- Property categories matching DB property_category values ----
PROPERTY_CATEGORIES = [
    "sfr",
    "duplex",
    "triplex",
    "fourplex",
    "apartment",  # 5+ units
    "condo",
    "townhouse",
    "coop",
    "pud",
    "land",
    "mixed_use",
    "commercial",
    "other",
]

# ---- Reason strings ----
_UNIT_NOT_LOT = (
    "This property is a unit within a larger building — the owner does not "
    "control the underlying lot. Development potential (ADU, SB9, lot-split) "
    "applies at the lot level, not the individual unit."
)
_APARTMENT_SCALE = (
    "Development potential (ADU, SB9) is not relevant for apartment buildings "
    "with 5+ existing units — these analyses target smaller residential properties."
)
_LAND_NO_STRUCTURE = (
    "There is no existing structure on this land parcel. "
    "Improvement simulation requires a building to improve."
)
_LAND_NO_RENTAL = (
    "There are no existing units on this land parcel to generate rental income."
)
_COMMERCIAL_RESIDENTIAL = (
    "This is a commercial property. Residential-focused analyses "
    "(development potential, rental income, improvement ROI) do not apply."
)
_SB9_SFR_ONLY = (
    "SB9 lot splitting is only available for single-family residential "
    "properties in R-1 or R-1H zoning districts."
)
_DUPLEX_NO_SB9 = (
    "SB9 lot splitting is not applicable to duplexes, triplexes, or "
    "fourplexes — it applies only to single-family homes."
)
_CONDO_AS_IS_ONLY = (
    "Investment scenarios for condos/townhouses/co-ops are limited to "
    "as-is rental analysis. ADU, SB9, and multi-unit expansion scenarios "
    "do not apply since the owner does not control the lot."
)
_APARTMENT_AS_IS_ONLY = (
    "Investment scenarios for apartment buildings (5+ units) are limited to "
    "as-is rental analysis of existing units."
)
_MIXED_USE_RESTRICTED = (
    "Development potential is limited to the residential portion of "
    "mixed-use properties."
)

# ---------------------------------------------------------------------------
# Applicability matrix
# ---------------------------------------------------------------------------
# Keys are analysis types.  Values are dicts mapping property_category
# to (Applicability, reason).  Categories not listed default to APPLICABLE.

_MATRIX: dict[str, dict[str, tuple[Applicability, str]]] = {
    "development_potential": {
        "sfr": (Applicability.APPLICABLE, ""),
        "duplex": (Applicability.RESTRICTED, _DUPLEX_NO_SB9),
        "triplex": (Applicability.RESTRICTED, _DUPLEX_NO_SB9),
        "fourplex": (Applicability.RESTRICTED, _DUPLEX_NO_SB9),
        "apartment": (Applicability.NOT_APPLICABLE, _APARTMENT_SCALE),
        "condo": (Applicability.NOT_APPLICABLE, _UNIT_NOT_LOT),
        "townhouse": (Applicability.NOT_APPLICABLE, _UNIT_NOT_LOT),
        "coop": (Applicability.NOT_APPLICABLE, _UNIT_NOT_LOT),
        "pud": (Applicability.RESTRICTED, _DUPLEX_NO_SB9),
        "land": (
            Applicability.RESTRICTED,
            "Development analysis for land focuses on new construction "
            "capacity based on zoning — ADU/SB9 do not apply to vacant lots.",
        ),
        "mixed_use": (Applicability.RESTRICTED, _MIXED_USE_RESTRICTED),
        "commercial": (Applicability.NOT_APPLICABLE, _COMMERCIAL_RESIDENTIAL),
    },
    "improvement_simulation": {
        "land": (Applicability.NOT_APPLICABLE, _LAND_NO_STRUCTURE),
        "commercial": (Applicability.NOT_APPLICABLE, _COMMERCIAL_RESIDENTIAL),
    },
    "rental_income": {
        "land": (Applicability.NOT_APPLICABLE, _LAND_NO_RENTAL),
        "commercial": (Applicability.NOT_APPLICABLE, _COMMERCIAL_RESIDENTIAL),
    },
    "investment_scenarios": {
        "sfr": (Applicability.APPLICABLE, ""),
        "duplex": (Applicability.RESTRICTED, _DUPLEX_NO_SB9),
        "triplex": (Applicability.RESTRICTED, _DUPLEX_NO_SB9),
        "fourplex": (Applicability.RESTRICTED, _DUPLEX_NO_SB9),
        "apartment": (Applicability.RESTRICTED, _APARTMENT_AS_IS_ONLY),
        "condo": (Applicability.RESTRICTED, _CONDO_AS_IS_ONLY),
        "townhouse": (Applicability.RESTRICTED, _CONDO_AS_IS_ONLY),
        "coop": (Applicability.RESTRICTED, _CONDO_AS_IS_ONLY),
        "pud": (Applicability.RESTRICTED, _DUPLEX_NO_SB9),
        "land": (Applicability.NOT_APPLICABLE, _LAND_NO_RENTAL),
        "mixed_use": (Applicability.RESTRICTED, _MIXED_USE_RESTRICTED),
        "commercial": (Applicability.NOT_APPLICABLE, _COMMERCIAL_RESIDENTIAL),
    },
}

# Investment scenario types that should be excluded per property category.
# Scenario type names match what RentalAnalyzer uses internally.
_EXCLUDED_SCENARIOS: dict[str, list[str]] = {
    "sfr": [],  # Full suite
    "duplex": ["sb9_split"],
    "triplex": ["sb9_split"],
    "fourplex": ["sb9_split"],
    "apartment": ["adu", "sb9_split", "multi_unit"],
    "condo": ["adu", "sb9_split", "multi_unit"],
    "townhouse": ["adu", "sb9_split", "multi_unit"],
    "coop": ["adu", "sb9_split", "multi_unit"],
    "pud": ["sb9_split"],
    "land": ["adu", "sb9_split", "multi_unit", "as_is"],  # No scenarios at all
    "mixed_use": ["sb9_split"],
    "commercial": ["adu", "sb9_split", "multi_unit", "as_is"],
}

# Dev potential sub-analyses to skip per property category.
_SKIP_DEV_SUB: dict[str, set[str]] = {
    "duplex": {"sb9"},
    "triplex": {"sb9"},
    "fourplex": {"sb9"},
    "pud": {"sb9"},
    "land": {"adu", "sb9", "improvements"},
    "mixed_use": {"sb9"},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_applicability(
    analysis_type: str,
    property_category: Optional[str],
    record_type: Optional[str] = None,
) -> tuple[Applicability, str]:
    """Check if an analysis type applies to a property category.

    Returns ``(Applicability, reason_string)``.
    If *property_category* is ``None`` or unknown, returns
    ``(APPLICABLE, "")`` as a permissive default.
    """
    if not property_category:
        return (Applicability.APPLICABLE, "")

    cat = property_category.lower().strip()

    # Unit-level records (condos, co-ops) that try to run lot-level analyses
    if record_type == "unit" and analysis_type == "development_potential":
        return (Applicability.NOT_APPLICABLE, _UNIT_NOT_LOT)

    matrix_entry = _MATRIX.get(analysis_type)
    if not matrix_entry:
        # Analysis types not in the matrix (price_prediction, comps, etc.)
        # are universally applicable.
        return (Applicability.APPLICABLE, "")

    entry = matrix_entry.get(cat)
    if entry:
        return entry

    # Category not explicitly listed → default to applicable
    return (Applicability.APPLICABLE, "")


def get_applicable_analyses(
    property_category: Optional[str],
    record_type: Optional[str] = None,
) -> dict[str, tuple[Applicability, str]]:
    """Return applicability for ALL analysis types for a given property category."""
    return {
        atype: check_applicability(atype, property_category, record_type)
        for atype in ANALYSIS_TYPES
    }


def get_restricted_scenarios(
    property_category: Optional[str],
) -> list[str]:
    """Return list of investment scenario types to EXCLUDE for a property category.

    Scenario type names: ``"as_is"``, ``"adu"``, ``"sb9_split"``, ``"multi_unit"``.
    An empty list means all scenarios are allowed.
    """
    if not property_category:
        return []
    return _EXCLUDED_SCENARIOS.get(property_category.lower().strip(), [])


def get_dev_sub_skips(
    property_category: Optional[str],
) -> set[str]:
    """Return set of development sub-analyses to skip for a property category.

    Sub-analysis names: ``"adu"``, ``"sb9"``, ``"improvements"``.
    An empty set means compute everything.
    """
    if not property_category:
        return set()
    return _SKIP_DEV_SUB.get(property_category.lower().strip(), set())
