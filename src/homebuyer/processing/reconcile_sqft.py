"""Reconcile building_sqft vs sqft into computed_bldg_sqft.

The properties table has two building-size columns from different sources:
- building_sqft: assessor-reported total building footprint
- sqft: third-party (RentCast/MLS) per-unit living area

These conflict for ~4000+ rows.  This module applies category-based rules
to pick the best value and writes it to computed_bldg_sqft, recording the
reasoning in data_notes (a JSON array).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)

# Each rule is: (label, WHERE clause, computed value SQL, note text)
# Rules are evaluated top-to-bottom; earlier rules take priority because
# each UPDATE only touches rows where computed_bldg_sqft IS STILL NULL.
#
# data_notes is assumed to be a JSON array (or NULL).  The SQL CASE
# expression only writes notes when data_notes IS NULL; existing non-null
# values are preserved as-is.  If a row has malformed JSON in data_notes,
# it will be left untouched — this is intentional to avoid data loss.
_RECONCILIATION_RULES: list[tuple[str, str, str, str]] = [
    # --- Fake vacants (building_sqft = 0 but property clearly exists) ---
    (
        "S1: Fake vacant with rooms",
        """building_sqft = 0
           AND sqft > 0
           AND (beds > 0 OR baths > 0)""",
        "sqft",
        "Assessor reports 0 bldg sqft but property has beds/baths; using third-party sqft",
    ),
    (
        "S2: Fake vacant sqft-only",
        """building_sqft = 0
           AND sqft > 0
           AND (beds IS NULL OR beds = 0)
           AND (baths IS NULL OR baths = 0)""",
        "sqft",
        "Assessor reports 0 bldg sqft; using third-party sqft as fallback",
    ),
    # --- Condo-specific (building_sqft often = whole building, sqft = per-unit) ---
    (
        "S3: Condo bldg = whole building",
        """property_category IN ('condo', 'coop', 'townhouse')
           AND building_sqft > 0 AND sqft > 0
           AND building_sqft > sqft * 3""",
        "sqft",
        "Assessor building_sqft appears to be whole-building total; using per-unit sqft",
    ),
    (
        "S4: Condo sqft = whole building",
        """property_category IN ('condo', 'coop', 'townhouse')
           AND building_sqft > 0 AND sqft > 0
           AND sqft > building_sqft * 3""",
        "building_sqft",
        "Third-party sqft appears to be whole-building total; using assessor building_sqft",
    ),
    (
        "S5: Condo moderate bldg > sqft",
        """property_category IN ('condo', 'coop', 'townhouse')
           AND building_sqft > 0 AND sqft > 0
           AND building_sqft > sqft""",
        "sqft",
        "Condo building_sqft > unit sqft; using per-unit sqft",
    ),
    (
        "S6: Condo moderate sqft > bldg",
        """property_category IN ('condo', 'coop', 'townhouse')
           AND building_sqft > 0 AND sqft > 0
           AND sqft > building_sqft""",
        "sqft",
        "Condo sqft > building_sqft; using larger per-unit sqft",
    ),
    # --- Non-condo mismatches ---
    # S7 was removed: it handled condo equal-value cases (building_sqft == sqft)
    # which are now caught by the "OK: Match" happy-path rule below.
    (
        "S8: Non-condo bldg > sqft",
        """property_category NOT IN ('condo', 'coop', 'townhouse')
           AND building_sqft > 0 AND sqft > 0
           AND building_sqft > sqft""",
        "building_sqft",
        "Assessor building_sqft > third-party sqft; using assessor value",
    ),
    (
        "S9: Non-condo sqft > bldg",
        """property_category NOT IN ('condo', 'coop', 'townhouse')
           AND building_sqft > 0 AND sqft > 0
           AND sqft > building_sqft""",
        "sqft",
        "Third-party sqft > assessor building_sqft; using larger value",
    ),
    # --- Single-source rows ---
    (
        "S10: Not enriched (bldg only)",
        """building_sqft > 0
           AND (sqft IS NULL OR sqft = 0)""",
        "building_sqft",
        "No third-party data; using assessor building_sqft",
    ),
    (
        "S11: No data at all",
        """(building_sqft IS NULL OR building_sqft = 0)
           AND (sqft IS NULL OR sqft = 0)""",
        "NULL",
        "No building sqft data from any source",
    ),
    # --- Happy path: both agree ---
    (
        "OK: Match",
        """building_sqft > 0 AND sqft > 0
           AND building_sqft = sqft""",
        "sqft",
        None,  # no note needed — sources agree
    ),
    (
        "OK: Only sqft",
        """(building_sqft IS NULL OR building_sqft = 0)
           AND sqft > 0""",
        "sqft",
        None,
    ),
]


def reconcile_sqft(db: Database, *, force: bool = False) -> dict[str, int]:
    """Populate computed_bldg_sqft and data_notes for all properties.

    Parameters
    ----------
    db : Database
        Connected database instance.
    force : bool
        If True, re-reconcile all rows (clears computed_bldg_sqft and data_notes, then regenerates both).
        If False (default), only touches rows where computed_bldg_sqft IS NULL.

    Returns
    -------
    dict mapping rule label → number of rows updated.
    """
    if force:
        db.execute("UPDATE properties SET computed_bldg_sqft = NULL, data_notes = NULL")
        db.commit()
        logger.info("Force mode: cleared computed_bldg_sqft and data_notes.")

    stats: dict[str, int] = {}

    for label, where, value_expr, note_text in _RECONCILIATION_RULES:
        try:
            # Count matching rows before update (to measure impact)
            pre_count = db.fetchval(
                f"SELECT COUNT(*) FROM properties WHERE computed_bldg_sqft IS NULL AND {where}"
            ) or 0

            if pre_count == 0:
                stats[label] = 0
                continue

            if note_text is not None:
                note_json = json.dumps([note_text])
                sql = f"""
                    UPDATE properties
                    SET computed_bldg_sqft = {value_expr},
                        data_notes = CASE
                            WHEN data_notes IS NULL THEN ?
                            ELSE data_notes
                        END
                    WHERE computed_bldg_sqft IS NULL
                      AND {where}
                """
                db.execute(sql, (note_json,))
            else:
                # No note needed (happy path)
                sql = f"""
                    UPDATE properties
                    SET computed_bldg_sqft = {value_expr}
                    WHERE computed_bldg_sqft IS NULL
                      AND {where}
                """
                db.execute(sql)

            db.commit()
            stats[label] = pre_count

            if pre_count > 0:
                logger.info("  %s: %d rows", label, pre_count)
        except Exception:
            logger.warning("Reconciliation rule %s failed, rolling back.", label, exc_info=True)
            db.rollback()
            stats[label] = 0

    # Summary
    try:
        total_reconciled = db.fetchval(
            "SELECT COUNT(*) FROM properties WHERE computed_bldg_sqft IS NOT NULL"
        ) or 0
        total_noted = db.fetchval(
            "SELECT COUNT(*) FROM properties WHERE data_notes IS NOT NULL"
        ) or 0
        total_props = db.fetchval("SELECT COUNT(*) FROM properties") or 0
    except Exception:
        logger.warning("Failed to compute reconciliation summary.", exc_info=True)
        db.rollback()
        total_reconciled = total_noted = total_props = 0

    logger.info(
        "Reconciliation complete: %d/%d properties have computed_bldg_sqft, "
        "%d have data_notes.",
        total_reconciled,
        total_props,
        total_noted,
    )

    stats["_total_reconciled"] = total_reconciled
    stats["_total_noted"] = total_noted
    stats["_total_properties"] = total_props
    return stats
