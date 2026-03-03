"""Collector for aggregated market metrics from Redfin Data Center.

Downloads the city-level market tracker TSV (~985MB gzipped), streams it,
and filters to Berkeley rows only before inserting into the database.
"""

import csv
import gzip
import io
import logging
from datetime import date, datetime
from pathlib import Path

from homebuyer.config import REDFIN_MARKET_S3_CITY, RAW_DIR
from homebuyer.storage.database import Database
from homebuyer.storage.models import CollectionResult, MarketMetric
from homebuyer.utils.http import create_session, stream_download

logger = logging.getLogger(__name__)

# The TSV file to download
_TSV_FILENAME = "city_market_tracker.tsv000.gz"

# Column names we need from the TSV (Redfin Data Center format)
# The TSV uses UPPERCASE column names throughout.
_REGION_COLUMN = "REGION"
_CITY_COLUMN = "CITY"
_STATE_CODE_COLUMN = "STATE_CODE"


class RedfinMarketCollector:
    """Downloads and filters Redfin Data Center market metrics for Berkeley."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.session = create_session()

    def collect(self, force_download: bool = False) -> CollectionResult:
        """Download city TSV, filter to Berkeley, insert into market_metrics.

        Args:
            force_download: Re-download even if file exists and is recent.

        Returns:
            A CollectionResult summarizing what was collected.
        """
        result = CollectionResult(source="redfin_market", started_at=datetime.now())
        run_id = self.db.start_collection_run("redfin_market")

        try:
            # Step 1: Download the gzipped TSV
            gz_path = RAW_DIR / "redfin_market" / _TSV_FILENAME
            if not gz_path.exists() or force_download:
                logger.info("Downloading Redfin market data (~985MB compressed)...")
                stream_download(
                    self.session,
                    REDFIN_MARKET_S3_CITY,
                    gz_path,
                    description="Redfin market data",
                )
            else:
                logger.info("Using cached file: %s", gz_path)

            # Step 2: Stream, filter, and parse
            logger.info("Filtering Berkeley rows from TSV...")
            metrics = list(self._stream_filter_berkeley(gz_path))
            result.records_fetched = len(metrics)
            logger.info("Found %d Berkeley market metric rows.", len(metrics))

            # Step 3: Insert into database
            affected = self.db.upsert_market_metrics_batch(metrics)
            result.records_inserted = affected
            result.records_duplicates = len(metrics) - affected

            logger.info(
                "Market metrics: %d inserted/updated, %d unchanged.",
                affected,
                result.records_duplicates,
            )

        except Exception as e:
            logger.error("Market data collection failed: %s", e)
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result

    def _stream_filter_berkeley(self, gz_path: Path):
        """Yield MarketMetric objects for Berkeley rows from the gzipped TSV.

        Streams the file line-by-line to avoid loading the full ~985MB into memory.
        """
        with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")

            for row in reader:
                # Filter to Berkeley, CA rows only
                # TSV uses UPPERCASE column names throughout
                region = row.get("REGION", "").strip()
                city = row.get("CITY", "").strip()
                state_code = row.get("STATE_CODE", "").strip()

                # Must be in California to exclude:
                # - "Bath (Berkeley Springs), WV"
                # - "Holiday City-Berkeley, NJ"
                if state_code != "CA":
                    continue

                # Match on "Berkeley, CA" in region or "Berkeley" in city
                is_berkeley = False
                if "Berkeley" in region and "CA" in region:
                    is_berkeley = True
                elif city.lower() == "berkeley":
                    is_berkeley = True

                if not is_berkeley:
                    continue

                try:
                    metric = self._parse_row(row)
                    if metric:
                        yield metric
                except Exception as e:
                    logger.debug("Skipping malformed market row: %s", e)

    def _parse_row(self, row: dict) -> MarketMetric | None:
        """Parse a TSV row dict into a MarketMetric object.

        All column names in the Redfin Data Center TSV are UPPERCASE.
        """
        period_begin_str = row.get("PERIOD_BEGIN", "").strip()
        period_end_str = row.get("PERIOD_END", "").strip()
        period_duration = row.get("PERIOD_DURATION", "").strip()

        if not period_begin_str or not period_end_str:
            return None

        try:
            period_begin = date.fromisoformat(period_begin_str)
            period_end = date.fromisoformat(period_end_str)
        except ValueError:
            return None

        region = row.get("REGION", "Berkeley, CA").strip()
        property_type = row.get("PROPERTY_TYPE", "").strip() or None

        return MarketMetric(
            period_begin=period_begin,
            period_end=period_end,
            period_duration=period_duration,
            region_name=region,
            property_type=property_type,
            median_sale_price=_safe_int(row.get("MEDIAN_SALE_PRICE")),
            median_list_price=_safe_int(row.get("MEDIAN_LIST_PRICE")),
            median_ppsf=_safe_float(row.get("MEDIAN_PPSF")),
            homes_sold=_safe_int(row.get("HOMES_SOLD")),
            new_listings=_safe_int(row.get("NEW_LISTINGS")),
            inventory=_safe_int(row.get("INVENTORY")),
            months_of_supply=_safe_float(row.get("MONTHS_OF_SUPPLY")),
            median_dom=_safe_int(row.get("MEDIAN_DOM")),
            avg_sale_to_list=_safe_float(row.get("AVG_SALE_TO_LIST")),
            sold_above_list_pct=_safe_float(row.get("SOLD_ABOVE_LIST")),
            price_drops_pct=_safe_float(row.get("PRICE_DROPS")),
            off_market_in_two_weeks_pct=_safe_float(
                row.get("OFF_MARKET_IN_TWO_WEEKS")
            ),
        )


def _safe_float(value: str | None) -> float | None:
    """Parse a string to float, returning None on failure, empty, or 'NA'."""
    if not value or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned.upper() == "NA":
        return None
    try:
        result = float(cleaned)
        return result if result == result else None  # NaN check
    except (ValueError, TypeError):
        return None


def _safe_int(value: str | None) -> int | None:
    """Parse a string to int via float, returning None on failure."""
    f = _safe_float(value)
    return int(f) if f is not None else None
