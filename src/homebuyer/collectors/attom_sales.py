"""Bulk collector for historical sale data from ATTOM's expanded history API.

Iterates over known Redfin addresses in the database and fetches their full
sale history from ATTOM.  Each sale transaction is stored as a new
``PropertySale`` record with ``data_source='attom'``.

The existing dedup index ``(address, sale_date, sale_price)`` ensures that
sales already captured by the Redfin collector are not re-inserted.

Usage:
    homebuyer collect attom-sales           # all known addresses
    homebuyer collect attom-sales --limit 5 # first 5 addresses (for testing)
"""

import logging
import time
from datetime import date, datetime
from typing import Optional

from homebuyer.collectors.attom import AttomClient
from homebuyer.storage.database import Database
from homebuyer.storage.models import CollectionResult, PropertySale

logger = logging.getLogger(__name__)


class AttomSalesCollector:
    """Collects historical sale data from ATTOM for addresses already in the DB."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.attom = AttomClient()

        # Load geocoder for neighborhood resolution (required for model training)
        self._geocoder = None
        try:
            from homebuyer.processing.geocode import NeighborhoodGeocoder
            self._geocoder = NeighborhoodGeocoder()
        except Exception:
            logger.warning(
                "Neighborhood geocoder unavailable — ATTOM sales will lack "
                "neighborhood labels and won't be used for model training."
            )

    def collect(
        self,
        limit: Optional[int] = None,
        delay: float = 2.0,
    ) -> CollectionResult:
        """Collect ATTOM sale history for known Redfin addresses.

        Args:
            limit: Maximum number of addresses to process (None = all).
            delay: Seconds to wait between ATTOM API calls (rate limiting).

        Returns:
            A ``CollectionResult`` summarizing what was collected.
        """
        result = CollectionResult(source="attom_sales", started_at=datetime.now())

        if not self.attom.enabled:
            result.errors.append("ATTOM API key not configured.")
            result.completed_at = datetime.now()
            return result

        run_id = self.db.start_collection_run(
            "attom_sales",
            {"limit": limit, "delay": delay},
        )

        try:
            addresses = self.db.get_unique_redfin_addresses()
            if limit:
                addresses = addresses[:limit]

            logger.info(
                "ATTOM sales collection: %d addresses to process (limit=%s)",
                len(addresses), limit,
            )

            all_sales: list[PropertySale] = []
            addresses_processed = 0
            addresses_with_sales = 0

            for i, addr_row in enumerate(addresses):
                address = addr_row["address"]
                city = addr_row.get("city", "Berkeley")
                state = addr_row.get("state", "CA")
                zip_code = addr_row.get("zip_code", "")
                lat = addr_row.get("latitude")
                lng = addr_row.get("longitude")

                address2 = f"{city}, {state} {zip_code}".strip()

                logger.debug(
                    "[%d/%d] Fetching sale history for %s",
                    i + 1, len(addresses), address,
                )

                # Rate limiting between API calls
                if i > 0:
                    time.sleep(delay)

                try:
                    history = self.attom.lookup_sale_history(
                        address1=address, address2=address2,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to fetch sale history for %s: %s", address, e
                    )
                    continue

                addresses_processed += 1

                if not history:
                    continue

                addresses_with_sales += 1

                # Resolve neighborhood from coordinates
                neighborhood = None
                sale_lat = lat
                sale_lng = lng
                if self._geocoder and sale_lat and sale_lng:
                    neighborhood = self._geocoder.geocode_point(sale_lat, sale_lng)

                # Convert each sale transaction to a PropertySale record
                for txn in history:
                    # Use ATTOM lat/lng if available, fall back to Redfin's
                    txn_lat = txn.get("latitude") or lat
                    txn_lng = txn.get("longitude") or lng

                    if not txn_lat or not txn_lng:
                        continue

                    try:
                        sale_date_str = txn["sale_date"]
                        sale_date_obj = date.fromisoformat(sale_date_str)
                    except (KeyError, ValueError):
                        continue

                    sale_price = txn.get("sale_price")
                    if not sale_price or sale_price <= 0:
                        continue

                    # Compute price_per_sqft if sqft is available
                    sqft = txn.get("sqft")
                    price_per_sqft = None
                    if sqft and sqft > 0:
                        price_per_sqft = round(sale_price / sqft, 2)

                    sale = PropertySale(
                        address=address,
                        city=city,
                        state=state,
                        zip_code=zip_code,
                        sale_date=sale_date_obj,
                        sale_price=sale_price,
                        latitude=float(txn_lat),
                        longitude=float(txn_lng),
                        sale_type=txn.get("sale_type"),
                        property_type=txn.get("property_type"),
                        beds=txn.get("beds"),
                        baths=txn.get("baths"),
                        sqft=sqft,
                        lot_size_sqft=txn.get("lot_size_sqft"),
                        year_built=txn.get("year_built"),
                        price_per_sqft=price_per_sqft,
                        neighborhood=neighborhood,
                        data_source="attom",
                    )
                    all_sales.append(sale)

                if (i + 1) % 25 == 0:
                    logger.info(
                        "Progress: %d/%d addresses processed, %d sales found so far",
                        i + 1, len(addresses), len(all_sales),
                    )

            result.records_fetched = len(all_sales)
            logger.info(
                "ATTOM collection done: %d addresses processed, "
                "%d had sales, %d total sale records. Inserting...",
                addresses_processed, addresses_with_sales, len(all_sales),
            )

            if all_sales:
                inserted, duplicates = self.db.upsert_sales_batch(all_sales)
                result.records_inserted = inserted
                result.records_duplicates = duplicates
                logger.info(
                    "Inserted %d new records, %d duplicates skipped.",
                    inserted, duplicates,
                )

        except Exception as e:
            logger.error("ATTOM sales collection failed: %s", e)
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result
