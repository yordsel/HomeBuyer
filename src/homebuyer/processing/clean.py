"""Data validation and cleaning utilities."""

import logging

from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)

# Reasonable ranges for Berkeley residential properties
VALID_RANGES = {
    "sale_price": (50_000, 30_000_000),
    "beds": (0, 15),
    "baths": (0, 15),
    "sqft": (100, 50_000),
    "lot_size_sqft": (100, 500_000),
    "year_built": (1850, 2027),
    "price_per_sqft": (50, 5_000),
}


def validate_sales(db: Database) -> dict[str, int]:
    """Check property sales for out-of-range values and log warnings.

    Does NOT delete or modify data — just reports issues.

    Returns:
        A dict of field_name -> count_of_outliers.
    """
    outliers: dict[str, int] = {}

    for field, (low, high) in VALID_RANGES.items():
        row = db.conn.execute(
            f"SELECT COUNT(*) FROM property_sales WHERE {field} IS NOT NULL "
            f"AND ({field} < ? OR {field} > ?)",
            (low, high),
        ).fetchone()

        count = row[0]
        if count > 0:
            outliers[field] = count
            logger.warning(
                "Field '%s': %d values outside range [%s, %s]",
                field, count, f"{low:,}", f"{high:,}",
            )

    if not outliers:
        logger.info("All fields within expected ranges.")

    return outliers
