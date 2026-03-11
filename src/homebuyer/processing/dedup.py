"""Deduplication logic for property sales records.

Handles duplicates that arise from:
- Overlapping price-range splits
- Re-running the collector
- MLS data quirks
"""

import logging

from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


def deduplicate_sales(db: Database) -> tuple[int, int]:
    """Find and remove duplicate property sale records.

    Strategy (applied in order):
    1. Same MLS# appearing multiple times -> keep the row with the lowest ID
       (first inserted, which came from the most specific price range)
    2. Same address + sale_date + sale_price -> keep lowest ID

    Returns:
        (duplicates_removed, total_remaining)
    """
    removed = 0

    # Strategy 1: Duplicate MLS numbers
    mls_dupes = db.fetchall("""
        SELECT mls_number, COUNT(*) as cnt
        FROM property_sales
        WHERE mls_number IS NOT NULL
        GROUP BY mls_number
        HAVING COUNT(*) > 1
    """)

    if mls_dupes:
        for row in mls_dupes:
            r = dict(row)
            mls = r["mls_number"]
            # Keep the one with the lowest ID, delete the rest
            db.execute("""
                DELETE FROM property_sales
                WHERE mls_number = ?
                AND id NOT IN (
                    SELECT MIN(id) FROM property_sales WHERE mls_number = ?
                )
            """, (mls, mls))
            removed += r["cnt"] - 1

    # Strategy 2: Duplicate address + sale_date + sale_price (for records without MLS#)
    addr_dupes = db.fetchall("""
        SELECT address, sale_date, sale_price, COUNT(*) as cnt
        FROM property_sales
        WHERE mls_number IS NULL
        GROUP BY address, sale_date, sale_price
        HAVING COUNT(*) > 1
    """)

    if addr_dupes:
        for row in addr_dupes:
            r = dict(row)
            db.execute("""
                DELETE FROM property_sales
                WHERE address = ? AND sale_date = ? AND sale_price = ?
                AND mls_number IS NULL
                AND id NOT IN (
                    SELECT MIN(id) FROM property_sales
                    WHERE address = ? AND sale_date = ? AND sale_price = ?
                    AND mls_number IS NULL
                )
            """, (
                r["address"], r["sale_date"], r["sale_price"],
                r["address"], r["sale_date"], r["sale_price"],
            ))
            removed += r["cnt"] - 1

    db.commit()

    remaining = db.fetchval("SELECT COUNT(*) FROM property_sales")
    logger.info("Deduplication: removed %d duplicates. %d records remain.", removed, remaining)

    return removed, remaining
