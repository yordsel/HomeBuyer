"""Batch RentCast enrichment for the properties table.

Iterates through properties missing key fields (beds, baths, sqft, year_built)
and fetches property details from the RentCast API. Designed to be resumable
— only processes rows that still lack data, so it is safe to run multiple times.

Raw API responses are cached in the api_response_cache table so data is
never lost and can be re-parsed later without additional API calls.

RentCast rate limit: 20 requests/second per API key.
Uses concurrent threads (default 8) to saturate bandwidth while respecting
the rate limit via a shared semaphore.

Usage:
    homebuyer enrich rentcast --limit 100 --workers 8
"""

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

from homebuyer.collectors.rentcast import RentcastClient
from homebuyer.storage.database import Database
from homebuyer.storage.models import CollectionResult

logger = logging.getLogger(__name__)


class RentcastParcelEnricher:
    """Batch-enrich properties table with RentCast property details."""

    def __init__(
        self,
        db: Database,
        rentcast_client: Optional[RentcastClient] = None,
    ) -> None:
        self.db = db
        self.rentcast = rentcast_client or RentcastClient()

    def enrich(
        self,
        limit: Optional[int] = None,
        delay: float = 0.06,
        force: bool = False,
        workers: int = 8,
    ) -> CollectionResult:
        """Fetch RentCast details for properties missing key fields.

        Uses a thread pool for concurrent API calls. Each worker creates its
        own RentcastClient/session to avoid sharing connections across threads.

        Args:
            limit: Maximum number of properties to enrich. None = all.
            delay: Minimum seconds between API calls per-worker. Default 0.06.
            force: If True, re-enrich ALL properties (ignore existing data).
            workers: Number of concurrent threads (default 8).
                     RentCast allows 20 req/s — 8 workers at ~400ms latency
                     gives ~20 req/s effective throughput.

        Returns:
            A CollectionResult summarizing what was enriched.
        """
        result = CollectionResult(source="rentcast-parcels", started_at=datetime.now())
        run_id = self.db.start_collection_run("rentcast-parcels")

        if not self.rentcast.enabled:
            msg = "RentCast API key not configured. Set RENTCAST_API_KEY env var."
            logger.error(msg)
            result.errors.append(msg)
            result.completed_at = datetime.now()
            self.db.complete_collection_run(run_id, result)
            return result

        try:
            rows = self._get_rows_to_enrich(limit=limit, force=force)
            total = len(rows)

            if total == 0:
                logger.info("No properties need RentCast enrichment.")
                result.completed_at = datetime.now()
                self.db.complete_collection_run(run_id, result)
                return result

            est_time = total / 15  # ~15 req/s with rate limiter
            logger.info(
                "RentCast enrichment: %d properties to process with %d workers "
                "(est. %.0f seconds / %.1f minutes).",
                total, workers, est_time, est_time / 60,
            )

            # --- Shared counters (thread-safe) ---
            lock = threading.Lock()
            counters = {"processed": 0, "found": 0, "not_found": 0, "errors": 0}
            errors: list[str] = []
            batch_updates: list[dict] = []
            pending_cache: list[dict] = []
            batch_size = 100

            # Token-bucket rate limiter: max 15 req/s (safe margin under 20)
            max_rps = 15
            rate_lock = threading.Lock()
            _last_request_times: list[float] = []

            def _wait_for_rate_limit() -> None:
                """Block until we're under the rate limit."""
                while True:
                    now = time.monotonic()
                    with rate_lock:
                        # Remove timestamps older than 1 second
                        while _last_request_times and _last_request_times[0] < now - 1.0:
                            _last_request_times.pop(0)
                        if len(_last_request_times) < max_rps:
                            _last_request_times.append(now)
                            return
                    # Wait a bit before retrying
                    time.sleep(0.02)

            def _process_row(row: dict) -> Optional[tuple[dict, Optional[dict]]]:
                """Process a single row in a worker thread."""
                prop_id = row["id"]
                address = row["address"]
                zip_code = row.get("zip_code", "")

                _wait_for_rate_limit()

                try:
                    return self._enrich_single(prop_id, address, zip_code)
                except Exception as e:
                    logger.warning(
                        "Error enriching %s (id=%d): %s", address, prop_id, e,
                    )
                    with lock:
                        counters["errors"] += 1
                        errors.append(f"{address}: {e}")
                    return None

            # --- Run with thread pool ---
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_process_row, row): row
                    for row in rows
                }

                for future in as_completed(futures):
                    row_result = future.result()

                    with lock:
                        counters["processed"] += 1
                        i = counters["processed"]

                        if row_result:
                            update, cache_entry = row_result
                            batch_updates.append(update)
                            if cache_entry:
                                pending_cache.append(cache_entry)
                            if update.get("beds") is not None:
                                counters["found"] += 1
                            else:
                                counters["not_found"] += 1

                        # Batch commit (under lock for DB safety)
                        if len(batch_updates) >= batch_size:
                            self.db.update_properties_enrichment_batch(batch_updates)
                            # Flush pending cache writes (main thread)
                            for ce in pending_cache:
                                try:
                                    self.db.cache_api_response(**ce)
                                except Exception:
                                    pass
                            batch_updates = []
                            pending_cache = []

                        # Progress logging
                        if i % 500 == 0 or i == total:
                            elapsed = (datetime.now() - result.started_at).total_seconds()
                            rate = i / elapsed if elapsed > 0 else 0
                            eta_s = (total - i) / rate if rate > 0 else 0
                            logger.info(
                                "RentCast progress: %d/%d (%.0f%%) — "
                                "%d found, %d no data, %d errors — "
                                "%.1f req/s, ETA %.0fs (%.1f min)",
                                i, total, 100 * i / total,
                                counters["found"], counters["not_found"],
                                counters["errors"],
                                rate, eta_s, eta_s / 60,
                            )

            # Flush remaining updates
            if batch_updates:
                self.db.update_properties_enrichment_batch(batch_updates)
            for ce in pending_cache:
                try:
                    self.db.cache_api_response(**ce)
                except Exception:
                    pass

            result.records_fetched = total
            result.records_inserted = counters["found"]
            result.records_duplicates = counters["not_found"]
            result.errors = errors

            logger.info(
                "RentCast enrichment complete: %d processed, "
                "%d found data, %d no data, %d errors.",
                counters["processed"], counters["found"],
                counters["not_found"], counters["errors"],
            )

        except Exception as e:
            logger.error("RentCast enrichment failed: %s", e)
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result

    def _get_rows_to_enrich(
        self,
        limit: Optional[int] = None,
        force: bool = False,
    ) -> list[dict]:
        """Get properties that need enrichment.

        Default: properties where beds OR baths OR sqft is NULL.
        Force mode: ALL properties.
        """
        if force:
            sql = (
                "SELECT id, apn, address, street_number, street_name, "
                "zip_code, latitude, longitude "
                "FROM properties"
            )
        else:
            sql = (
                "SELECT id, apn, address, street_number, street_name, "
                "zip_code, latitude, longitude "
                "FROM properties "
                "WHERE beds IS NULL OR baths IS NULL OR sqft IS NULL"
            )
        if limit:
            sql += f" LIMIT {limit}"
        rows = self.db.fetchall(sql)
        return [dict(r) for r in rows]

    def _enrich_single(
        self, prop_id: int, address: str, zip_code: str,
    ) -> tuple[dict, Optional[dict]]:
        """Enrich a single property from RentCast.

        Args:
            prop_id: Database row ID.
            address: Full address from DB (e.g. "1615 ALCATRAZ AVE BERKELEY 94703").
            zip_code: Zip code.

        Returns:
            Tuple of (update_dict, cache_entry_or_None).  The cache entry is
            returned rather than written here because SQLite connections are
            not thread-safe and this method runs in worker threads.
        """
        update: dict = {
            "id": prop_id,
            "rentcast_enriched": True,
        }
        cache_entry: Optional[dict] = None

        # Parse address for RentCast lookup
        street = _extract_street_address(address)
        full_addr = f"{street}, Berkeley, CA"
        if zip_code:
            full_addr += f" {zip_code}"

        detail = self.rentcast.lookup_property(address=full_addr)
        if detail:
            if detail.beds is not None:
                update["beds"] = detail.beds
            if detail.baths is not None:
                update["baths"] = detail.baths
            if detail.sqft is not None:
                update["sqft"] = detail.sqft
            if detail.year_built is not None:
                update["year_built"] = detail.year_built
            if detail.property_type is not None:
                update["property_type"] = detail.property_type
            if detail.last_sale_price is not None:
                update["last_sale_price"] = detail.last_sale_price
            if detail.last_sale_date is not None:
                update["last_sale_date"] = detail.last_sale_date

            # Prepare cache entry for main-thread write
            if detail._raw_json:
                cache_entry = {
                    "source": "rentcast",
                    "endpoint": "/v1/properties",
                    "cache_key": full_addr.lower().strip(),
                    "request_params": {"address": full_addr},
                    "response_json": json.dumps(detail._raw_json),
                }

        return update, cache_entry


def _extract_street_address(full_address: str) -> str:
    """Extract just the street address from a full address string.

    Our addresses look like: "1234 CEDAR ST BERKELEY 94702"
    or "1234 CEDAR ST" (already just the street part).

    RentCast expects a complete address, but we build it ourselves.
    So we just need the street part.
    """
    addr = full_address.strip()

    # Remove trailing zip code (5 digits)
    addr = re.sub(r"\s+\d{5}(-\d{4})?$", "", addr)

    # Remove city name at the end
    for city in ("BERKELEY", "ALBANY", "EMERYVILLE", "OAKLAND", "KENSINGTON"):
        if addr.upper().endswith(f" {city}"):
            addr = addr[: -(len(city) + 1)].strip()
            break

    return addr.strip()
