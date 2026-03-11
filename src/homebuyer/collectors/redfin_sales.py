"""Collector for individual property sales from the Redfin gis-csv API.

Handles:
- Adaptive price-range splitting to bypass the 350-row API cap
- CSV parsing and field mapping
- Berkeley-only filtering (neighboring cities leak into results)
- Deduplication on insert via MLS number and address+date+price
"""

import csv
import io
import logging
from datetime import date, datetime

from homebuyer.config import (
    BERKELEY_CITY_NAME,
    DEFAULT_PRICE_RANGES,
    DEFAULT_SOLD_WITHIN_DAYS,
    PriceRange,
    REDFIN_CAP_SAFETY_THRESHOLD,
    REDFIN_GIS_CSV_BASE,
    REDFIN_MARKET_NAME,
    BERKELEY_REGION_ID,
    BERKELEY_REGION_TYPE,
    REQUEST_DELAY_SECONDS,
)
from homebuyer.storage.database import Database
from homebuyer.storage.models import CollectionResult, PropertySale
from homebuyer.utils.date_utils import parse_redfin_date
from homebuyer.utils.http import create_session, rate_limited_get
from homebuyer.utils.parse import safe_float, safe_int

logger = logging.getLogger(__name__)

# Minimum price range width before we stop recursive splitting ($)
MIN_SPLIT_WIDTH = 10_000


class RedfinSalesCollector:
    """Collects individual property sales from Redfin's gis-csv API."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.session = create_session()

    def collect(
        self,
        sold_within_days: int = DEFAULT_SOLD_WITHIN_DAYS,
        price_ranges: list[tuple[int, int]] | None = None,
    ) -> CollectionResult:
        """Collect all Berkeley property sales using adaptive price-range splitting.

        Args:
            sold_within_days: How many days back to query (max ~1825 for 5 years).
            price_ranges: Override price range buckets. Defaults to DEFAULT_PRICE_RANGES.

        Returns:
            A CollectionResult summarizing what was collected.
        """
        result = CollectionResult(source="redfin_sales", started_at=datetime.now())
        run_id = self.db.start_collection_run(
            "redfin_sales",
            {"sold_within_days": sold_within_days},
        )

        ranges = price_ranges or DEFAULT_PRICE_RANGES

        try:
            all_sales: list[PropertySale] = []

            for min_price, max_price in ranges:
                pr = PriceRange(min_price, max_price)
                logger.info("Collecting sales for price range %s", pr)
                chunk_sales = self._collect_range(pr, sold_within_days)
                all_sales.extend(chunk_sales)
                logger.info(
                    "  Range %s: %d Berkeley sales found", pr, len(chunk_sales)
                )

            result.records_fetched = len(all_sales)
            logger.info("Total sales fetched: %d. Inserting into database...", len(all_sales))

            inserted, duplicates = self.db.upsert_sales_batch(all_sales)
            result.records_inserted = inserted
            result.records_duplicates = duplicates

            logger.info(
                "Collection complete: %d inserted, %d duplicates skipped.",
                inserted,
                duplicates,
            )

        except Exception as e:
            logger.error("Collection failed: %s", e)
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result

    def _collect_range(
        self, price_range: PriceRange, sold_within_days: int
    ) -> list[PropertySale]:
        """Fetch sales for a single price range, splitting adaptively if capped.

        If the API returns >= REDFIN_CAP_SAFETY_THRESHOLD rows, the range is
        likely capped at 350. We split it in half and recurse.

        Returns a list of PropertySale objects filtered to Berkeley only.
        """
        rows = self._fetch_csv(price_range, sold_within_days)

        if len(rows) >= REDFIN_CAP_SAFETY_THRESHOLD and price_range.width > MIN_SPLIT_WIDTH:
            logger.warning(
                "Range %s returned %d rows (likely capped). Splitting...",
                price_range,
                len(rows),
            )
            left_range, right_range = price_range.split()
            left_sales = self._collect_range(left_range, sold_within_days)
            right_sales = self._collect_range(right_range, sold_within_days)
            return left_sales + right_sales

        if len(rows) >= REDFIN_CAP_SAFETY_THRESHOLD:
            logger.warning(
                "Range %s still capped at %d rows but too narrow to split further (%s width). "
                "Some records may be missing.",
                price_range,
                len(rows),
                f"${price_range.width:,}",
            )

        # Parse and filter to Berkeley
        sales = []
        for row in rows:
            try:
                sale = self._parse_row(row, str(price_range))
                if sale and sale.city.strip().lower() == BERKELEY_CITY_NAME.lower():
                    sales.append(sale)
            except Exception as e:
                logger.debug("Skipping malformed row: %s — %s", row.get("ADDRESS", "?"), e)

        return sales

    def _fetch_csv(
        self, price_range: PriceRange, sold_within_days: int
    ) -> list[dict]:
        """Fetch a single CSV chunk from the Redfin API and return parsed rows."""
        params = {
            "al": "1",
            "market": REDFIN_MARKET_NAME,
            "region_id": str(BERKELEY_REGION_ID),
            "region_type": str(BERKELEY_REGION_TYPE),
            "sold_within_days": str(sold_within_days),
            "status": "9",  # sold
            "uipt": "1,2,3,4,5,6,7,8",  # all property types
            "min_price": str(price_range.min_price),
            "max_price": str(price_range.max_price),
        }

        try:
            response = rate_limited_get(
                self.session, REDFIN_GIS_CSV_BASE, params=params, delay=REQUEST_DELAY_SECONDS
            )
        except Exception as e:
            logger.error("Failed to fetch CSV for range %s: %s", price_range, e)
            return []

        # Parse CSV from response text
        text = response.text
        if not text.strip():
            logger.warning("Empty response for range %s", price_range)
            return []

        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for row in reader:
            # Skip the MLS disclaimer row (has no ADDRESS field or it's None/empty)
            address = _safe_str(row.get("ADDRESS"))
            if address:
                rows.append(row)

        logger.debug("Range %s: fetched %d rows from API", price_range, len(rows))
        return rows

    def _parse_row(self, row: dict, price_range_bucket: str) -> PropertySale | None:
        """Parse a CSV row dict into a PropertySale object.

        Returns None if essential fields are missing.
        """
        address = _safe_str(row.get("ADDRESS"))
        city = _safe_str(row.get("CITY"))
        price_str = _safe_str(row.get("PRICE"))
        sold_date_str = _safe_str(row.get("SOLD DATE"))
        lat_str = _safe_str(row.get("LATITUDE"))
        lon_str = _safe_str(row.get("LONGITUDE"))

        # Require address, city, price, date, and coordinates
        if not all([address, city, price_str, sold_date_str, lat_str, lon_str]):
            return None

        sale_date = parse_redfin_date(sold_date_str)
        if sale_date is None:
            return None

        try:
            sale_price = int(float(price_str))
        except (ValueError, TypeError):
            return None

        if sale_price <= 0:
            return None

        # The URL column has a long header name — find it dynamically
        url_value = None
        for key in row:
            if key and key.startswith("URL"):
                url_value = _safe_str(row[key]) or None
                break

        return PropertySale(
            mls_number=_safe_str(row.get("MLS#")) or None,
            address=address,
            city=city,
            state=_safe_str(row.get("STATE OR PROVINCE")) or "CA",
            zip_code=_safe_str(row.get("ZIP OR POSTAL CODE")),
            sale_date=sale_date,
            sale_price=sale_price,
            sale_type=_safe_str(row.get("SALE TYPE")) or None,
            property_type=_safe_str(row.get("PROPERTY TYPE")) or None,
            beds=safe_float(row.get("BEDS")),
            baths=safe_float(row.get("BATHS")),
            sqft=safe_int(row.get("SQUARE FEET")),
            lot_size_sqft=safe_int(row.get("LOT SIZE")),
            year_built=safe_int(row.get("YEAR BUILT")),
            price_per_sqft=safe_float(row.get("$/SQUARE FEET")),
            hoa_per_month=safe_int(row.get("HOA/MONTH")),
            latitude=float(lat_str),
            longitude=float(lon_str),
            neighborhood_raw=_safe_str(row.get("LOCATION")) or None,
            redfin_url=url_value,
            days_on_market=safe_int(row.get("DAYS ON MARKET")),
            price_range_bucket=price_range_bucket,
            data_source="redfin",
        )


def _safe_str(value) -> str:
    """Safely convert a value to a stripped string. Handles None from CSV parser."""
    if value is None:
        return ""
    return str(value).strip()


