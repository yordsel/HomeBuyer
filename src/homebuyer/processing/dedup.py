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
    mls_dupes = db.conn.execute("""
        SELECT mls_number, COUNT(*) as cnt
        FROM property_sales
        WHERE mls_number IS NOT NULL
        GROUP BY mls_number
        HAVING cnt > 1
    """).fetchall()

    if mls_dupes:
        for row in mls_dupes:
            mls = row["mls_number"]
            # Keep the one with the lowest ID, delete the rest
            db.conn.execute("""
                DELETE FROM property_sales
                WHERE mls_number = ?
                AND id NOT IN (
                    SELECT MIN(id) FROM property_sales WHERE mls_number = ?
                )
            """, (mls, mls))
            removed += row["cnt"] - 1

    # Strategy 2: Duplicate address + sale_date + sale_price (for records without MLS#)
    addr_dupes = db.conn.execute("""
        SELECT address, sale_date, sale_price, COUNT(*) as cnt
        FROM property_sales
        WHERE mls_number IS NULL
        GROUP BY address, sale_date, sale_price
        HAVING cnt > 1
    """).fetchall()

    if addr_dupes:
        for row in addr_dupes:
            db.conn.execute("""
                DELETE FROM property_sales
                WHERE address = ? AND sale_date = ? AND sale_price = ?
                AND mls_number IS NULL
                AND id NOT IN (
                    SELECT MIN(id) FROM property_sales
                    WHERE address = ? AND sale_date = ? AND sale_price = ?
                    AND mls_number IS NULL
                )
            """, (
                row["address"], row["sale_date"], row["sale_price"],
                row["address"], row["sale_date"], row["sale_price"],
            ))
            removed += row["cnt"] - 1

    db.conn.commit()

    remaining = db.conn.execute("SELECT COUNT(*) FROM property_sales").fetchone()[0]
    logger.info("Deduplication: removed %d duplicates. %d records remain.", removed, remaining)

    return removed, remaining
