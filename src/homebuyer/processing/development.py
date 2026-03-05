"""Development potential calculator for Berkeley properties.

Computes ADU feasibility, Middle Housing Ordinance potential, SB 9 lot
splitting eligibility, and improvement ROI based on zoning rules,
lot size, and existing building characteristics.

Zoning rules are encoded from:
- Berkeley Municipal Code Title 23 (Zoning Ordinance)
- Middle Housing Ordinance (effective Nov 2025)
- ADU/JADU regulations (State + Berkeley overlay)
- SB 9 lot splitting (R-1/R-1H zones only)
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from homebuyer.processing.zoning import ZoningClassifier, ZoningInfo
from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Zoning Rules — static config from Berkeley Municipal Code
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ZoningRule:
    """Development parameters for a single zoning district."""

    zone_class: str
    base_units: int  # base max units (for standard lot)
    units_per_sqft: Optional[int] = None  # 1 unit per N sqft of lot (R-2, R-2A)
    max_lot_coverage_pct: float = 0.45  # 45% default
    max_height_ft: int = 35
    is_hillside: bool = False
    middle_housing_eligible: bool = True
    middle_housing_max_units: Optional[int] = None  # None = not eligible
    middle_housing_coverage_pct: float = 0.60  # 60% under MH
    sb9_eligible: bool = False
    adu_max_sqft: int = 800
    adu_max_height_ft: int = 16  # 16ft default, same in hillside
    residential: bool = True


# Key Berkeley zoning districts and their development rules
ZONING_RULES: dict[str, ZoningRule] = {
    # Single Family Residential
    "R-1": ZoningRule(
        zone_class="R-1",
        base_units=1,
        max_lot_coverage_pct=0.45,
        middle_housing_max_units=5,
        sb9_eligible=True,
    ),
    # Single Family Residential — Hillside
    "R-1H": ZoningRule(
        zone_class="R-1H",
        base_units=1,
        max_lot_coverage_pct=0.45,
        is_hillside=True,
        middle_housing_eligible=False,
        sb9_eligible=True,
        adu_max_height_ft=16,
    ),
    # Multi-Unit 2 (1 per 2,500 sqft)
    "R-2": ZoningRule(
        zone_class="R-2",
        base_units=1,
        units_per_sqft=2500,
        max_lot_coverage_pct=0.45,
        middle_housing_max_units=6,
    ),
    # Multi-Unit 2 Hillside
    "R-2H": ZoningRule(
        zone_class="R-2H",
        base_units=1,
        units_per_sqft=2500,
        max_lot_coverage_pct=0.45,
        is_hillside=True,
        middle_housing_eligible=False,
        adu_max_height_ft=16,
    ),
    # Multi-Unit 2A (1 per 1,650 sqft)
    "R-2A": ZoningRule(
        zone_class="R-2A",
        base_units=1,
        units_per_sqft=1650,
        max_lot_coverage_pct=0.45,
        middle_housing_max_units=7,
    ),
    # Multi-Unit 2A Hillside
    "R-2AH": ZoningRule(
        zone_class="R-2AH",
        base_units=1,
        units_per_sqft=1650,
        max_lot_coverage_pct=0.45,
        is_hillside=True,
        middle_housing_eligible=False,
        adu_max_height_ft=16,
    ),
    # Multi-Family Residential
    "R-3": ZoningRule(
        zone_class="R-3",
        base_units=3,
        units_per_sqft=1500,
        max_lot_coverage_pct=0.50,
        middle_housing_eligible=False,
    ),
    # Multi-Family Hillside
    "R-3H": ZoningRule(
        zone_class="R-3H",
        base_units=3,
        units_per_sqft=1500,
        max_lot_coverage_pct=0.50,
        is_hillside=True,
        middle_housing_eligible=False,
        adu_max_height_ft=16,
    ),
    # Multi-Family High Density
    "R-4": ZoningRule(
        zone_class="R-4",
        base_units=4,
        units_per_sqft=1000,
        max_lot_coverage_pct=0.55,
        middle_housing_eligible=False,
    ),
    # Multi-Family High Density Hillside
    "R-5H": ZoningRule(
        zone_class="R-5H",
        base_units=4,
        units_per_sqft=1000,
        max_lot_coverage_pct=0.55,
        is_hillside=True,
        middle_housing_eligible=False,
        adu_max_height_ft=16,
    ),
    # Mixed Use Residential
    "MU-R": ZoningRule(
        zone_class="MU-R",
        base_units=1,
        units_per_sqft=1500,
        max_lot_coverage_pct=0.60,
        middle_housing_max_units=7,
    ),
    "MUR": ZoningRule(
        zone_class="MUR",
        base_units=1,
        units_per_sqft=1500,
        max_lot_coverage_pct=0.60,
        middle_housing_max_units=7,
    ),
    # Environmental Safety — Residential
    "ES-R": ZoningRule(
        zone_class="ES-R",
        base_units=1,
        max_lot_coverage_pct=0.20,
        is_hillside=True,
        middle_housing_eligible=False,
        adu_max_sqft=500,
        adu_max_height_ft=16,
    ),
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class UnitPotential:
    """Maximum allowable units under base zoning and Middle Housing."""

    base_max_units: int
    middle_housing_eligible: bool
    middle_housing_max_units: Optional[int] = None
    effective_max_units: int = 1


@dataclass
class ADUFeasibility:
    """ADU (Accessory Dwelling Unit) feasibility assessment."""

    eligible: bool
    max_adu_sqft: int = 800
    remaining_lot_coverage_sqft: Optional[int] = None
    notes: str = ""


@dataclass
class SB9Eligibility:
    """SB 9 lot splitting eligibility."""

    eligible: bool
    can_split: bool = False
    resulting_lot_sizes: Optional[list[int]] = None
    max_total_units: int = 1
    notes: str = ""


@dataclass
class ImprovementROI:
    """ROI estimate for a category of home improvement."""

    category: str
    avg_job_value: float
    avg_ppsf_premium_pct: float
    sample_count: int


@dataclass
class DevelopmentPotential:
    """Complete development potential assessment for a property."""

    zoning: Optional[ZoningInfo] = None
    zone_rule: Optional[ZoningRule] = None
    units: Optional[UnitPotential] = None
    adu: Optional[ADUFeasibility] = None
    sb9: Optional[SB9Eligibility] = None
    beso: list[dict] = field(default_factory=list)
    improvements: list[ImprovementROI] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


class DevelopmentPotentialCalculator:
    """Computes development potential for Berkeley properties."""

    def __init__(
        self,
        classifier: ZoningClassifier,
        db: Database,
    ) -> None:
        self.classifier = classifier
        self.db = db

    def compute(
        self,
        lat: float,
        lon: float,
        lot_size_sqft: Optional[int] = None,
        sqft: Optional[int] = None,
        address: Optional[str] = None,
    ) -> DevelopmentPotential:
        """Compute development potential for a location.

        Args:
            lat: Latitude.
            lon: Longitude.
            lot_size_sqft: Lot size in sqft (used for unit calculations).
            sqft: Existing building sqft (used for ADU coverage calc).
            address: Street address (used for BESO lookup).

        Returns:
            A DevelopmentPotential with all computed results.
        """
        result = DevelopmentPotential()

        # 1. Get zoning info
        zoning_info = self.classifier.classify_point_full(lat, lon)
        if not zoning_info:
            # Try plain classify as fallback
            zone_class = self.classifier.classify_point(lat, lon)
            if zone_class:
                zoning_info = ZoningInfo(zone_class=zone_class)
        result.zoning = zoning_info

        if not zoning_info:
            return result

        # 2. Look up zoning rule
        rule = ZONING_RULES.get(zoning_info.zone_class)
        if not rule:
            # Try stripping trailing characters (e.g., "R-1A" -> "R-1")
            base_zone = zoning_info.zone_class.split("-")[0] + "-" + zoning_info.zone_class.split("-")[1][:1] if "-" in zoning_info.zone_class else zoning_info.zone_class
            rule = ZONING_RULES.get(base_zone)
        result.zone_rule = rule

        if not rule:
            return result

        # 3. Compute unit potential
        result.units = self._compute_units(rule, lot_size_sqft)

        # 4. Compute ADU feasibility
        result.adu = self._compute_adu(rule, lot_size_sqft, sqft)

        # 5. Compute SB 9 eligibility
        result.sb9 = self._compute_sb9(rule, lot_size_sqft)

        # 6. BESO lookup
        if address:
            result.beso = self.db.lookup_beso_by_address(address)

        # 7. Improvement ROI
        result.improvements = self._compute_improvement_roi()

        return result

    def _compute_units(
        self, rule: ZoningRule, lot_size_sqft: Optional[int]
    ) -> UnitPotential:
        """Calculate max allowable units under base zoning and Middle Housing."""
        # Base units
        if rule.units_per_sqft and lot_size_sqft:
            base_max = max(1, lot_size_sqft // rule.units_per_sqft)
        else:
            base_max = rule.base_units

        # Middle Housing
        mh_eligible = (
            rule.middle_housing_eligible
            and not rule.is_hillside
            and rule.middle_housing_max_units is not None
            and (lot_size_sqft is None or lot_size_sqft >= 5000)
        )

        mh_max = rule.middle_housing_max_units if mh_eligible else None
        effective = max(base_max, mh_max or 0)

        return UnitPotential(
            base_max_units=base_max,
            middle_housing_eligible=mh_eligible,
            middle_housing_max_units=mh_max,
            effective_max_units=effective,
        )

    def _compute_adu(
        self,
        rule: ZoningRule,
        lot_size_sqft: Optional[int],
        sqft: Optional[int],
    ) -> ADUFeasibility:
        """Assess ADU feasibility based on remaining lot coverage."""
        if not rule.residential:
            return ADUFeasibility(eligible=False, notes="Non-residential zone")

        max_adu = rule.adu_max_sqft
        notes_parts: list[str] = []

        if rule.is_hillside:
            notes_parts.append("Hillside zone: 16ft max height, 1 ADU or 1 JADU (not both)")

        remaining = None
        if lot_size_sqft and sqft:
            max_coverage = int(lot_size_sqft * rule.max_lot_coverage_pct)
            remaining = max(0, max_coverage - sqft)
            if remaining < 200:
                return ADUFeasibility(
                    eligible=False,
                    max_adu_sqft=max_adu,
                    remaining_lot_coverage_sqft=remaining,
                    notes="Insufficient remaining lot coverage for ADU",
                )
            # ADU can't exceed remaining coverage or the zone max
            max_adu = min(max_adu, remaining)

        eligible = True
        notes_parts.append(f"Max ADU: {max_adu} sqft, {rule.adu_max_height_ft}ft height")

        return ADUFeasibility(
            eligible=eligible,
            max_adu_sqft=max_adu,
            remaining_lot_coverage_sqft=remaining,
            notes="; ".join(notes_parts),
        )

    def _compute_sb9(
        self, rule: ZoningRule, lot_size_sqft: Optional[int]
    ) -> SB9Eligibility:
        """Check SB 9 lot splitting eligibility."""
        if not rule.sb9_eligible:
            return SB9Eligibility(
                eligible=False,
                notes=f"{rule.zone_class} is not eligible for SB 9 (R-1/R-1H only)",
            )

        if lot_size_sqft is None:
            return SB9Eligibility(
                eligible=True,
                can_split=False,
                max_total_units=2,
                notes="SB 9 eligible zone; lot size needed to assess splitting",
            )

        # SB 9 requirements: min 2,400 sqft, each resulting lot >= 1,200 sqft
        can_split = lot_size_sqft >= 2400
        resulting = None
        max_units = 2  # duplex on existing lot

        if can_split:
            half = lot_size_sqft // 2
            resulting = [half, lot_size_sqft - half]
            max_units = 4  # 2 units per resulting lot

        notes = f"Lot: {lot_size_sqft:,} sqft"
        if can_split:
            notes += f"; can split into ~{resulting[0]:,} + {resulting[1]:,} sqft"
            notes += f"; up to {max_units} total units"
        else:
            notes += f"; too small to split (need 2,400+ sqft)"

        return SB9Eligibility(
            eligible=True,
            can_split=can_split,
            resulting_lot_sizes=resulting,
            max_total_units=max_units,
            notes=notes,
        )

    def _compute_improvement_roi(self) -> list[ImprovementROI]:
        """Compute improvement ROI estimates from permit category analysis.

        Compares average $/sqft for properties with specific permit categories
        vs. properties without, to estimate the value premium per category.
        """
        try:
            rows = self.db.conn.execute(
                """
                WITH permit_cats AS (
                    SELECT
                        UPPER(TRIM(bp.address)) AS addr,
                        CASE
                            WHEN LOWER(bp.description) LIKE '%adu%'
                                 OR LOWER(bp.description) LIKE '%accessory dwelling%'
                                 THEN 'ADU'
                            WHEN LOWER(bp.description) LIKE '%addition%'
                                 OR LOWER(bp.description) LIKE '%add %'
                                 THEN 'Addition'
                            WHEN LOWER(bp.description) LIKE '%kitchen%'
                                 THEN 'Kitchen'
                            WHEN LOWER(bp.description) LIKE '%bath%'
                                 THEN 'Bathroom'
                            WHEN LOWER(bp.description) LIKE '%solar%'
                                 OR LOWER(bp.description) LIKE '%photovoltaic%'
                                 THEN 'Solar'
                            WHEN LOWER(bp.description) LIKE '%roof%'
                                 THEN 'Roof'
                            WHEN LOWER(bp.description) LIKE '%remodel%'
                                 OR LOWER(bp.description) LIKE '%renovation%'
                                 THEN 'Remodel'
                            WHEN LOWER(bp.description) LIKE '%seismic%'
                                 OR LOWER(bp.description) LIKE '%foundation%'
                                 THEN 'Seismic/Foundation'
                            ELSE NULL
                        END AS category,
                        bp.job_value
                    FROM building_permits bp
                    WHERE bp.description IS NOT NULL
                ),
                overall AS (
                    SELECT AVG(price_per_sqft) AS avg_ppsf
                    FROM property_sales
                    WHERE price_per_sqft IS NOT NULL AND price_per_sqft > 0
                ),
                cat_stats AS (
                    SELECT
                        pc.category,
                        COUNT(DISTINCT ps.id) AS sample_count,
                        AVG(pc.job_value) AS avg_job_value,
                        AVG(ps.price_per_sqft) AS avg_ppsf
                    FROM permit_cats pc
                    JOIN property_sales ps
                        ON UPPER(TRIM(ps.address)) = pc.addr
                    WHERE pc.category IS NOT NULL
                        AND ps.price_per_sqft IS NOT NULL
                        AND ps.price_per_sqft > 0
                        AND pc.job_value IS NOT NULL
                        AND pc.job_value > 0
                    GROUP BY pc.category
                    HAVING COUNT(DISTINCT ps.id) >= 5
                )
                SELECT
                    cs.category,
                    cs.avg_job_value,
                    ((cs.avg_ppsf - o.avg_ppsf) / o.avg_ppsf) * 100 AS premium_pct,
                    cs.sample_count
                FROM cat_stats cs
                CROSS JOIN overall o
                ORDER BY premium_pct DESC
                """
            ).fetchall()

            return [
                ImprovementROI(
                    category=r[0],
                    avg_job_value=round(r[1], 0),
                    avg_ppsf_premium_pct=round(r[2], 1),
                    sample_count=r[3],
                )
                for r in rows
            ]
        except Exception as e:
            logger.warning("Could not compute improvement ROI: %s", e)
            return []
