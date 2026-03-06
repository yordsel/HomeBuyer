"""Batch ATTOM enrichment for the properties table.

Iterates through properties where ``attom_enriched = 0`` and fetches
property details (beds, baths, sqft, year_built, etc.) and last-sale
data from the ATTOM API. Designed to be resumable — only processes
un-enriched rows, so it is safe to run multiple times.

Usage:
    homebuyer enrich attom --limit 100 --delay 2.0
"""

import logging
import time
from datetime import datetime
from typing import Optional

from homebuyer.collectors.attom import AttomClient
from homebuyer.storage.database import Database
from homebuyer.storage.models import CollectionResult

logger = logging.getLogger(__name__)


class AttomParcelEnricher:
    """Batch-enrich properties table with ATTOM property details."""

    def __init__(self, db: Database, attom_client: Optional[AttomClient] = None) -> None:
        self.db = db
        self.attom = attom_client or AttomClient()

    def enrich(
        self,
        limit: Optional[int] = None,
        delay: float = 2.0,
    ) -> CollectionResult:
        """Fetch ATTOM details for properties where attom_enriched = 0.

        Resumable: only processes un-enriched rows. Safe to run
        multiple times.

        Args:
            limit: Maximum number of properties to enrich. None = all.
            delay: Seconds to wait between ATTOM API calls (rate limiting).

        Returns:
            A CollectionResult summarizing what was enriched.
        """
        result = CollectionResult(source="attom-parcels", started_at=datetime.now())
        run_id = self.db.start_collection_run("attom-parcels")

        if not self.attom.enabled:
            msg = "ATTOM API key not configured. Set ATTOM_API_KEY env var."
            logger.error(msg)
            result.errors.append(msg)
            result.completed_at = datetime.now()
            self.db.complete_collection_run(run_id, result)
            return result

        try:
            rows = self.db.get_properties_missing_attom(limit=limit)
            total = len(rows)

            if total == 0:
                logger.info("No properties need ATTOM enrichment.")
                result.completed_at = datetime.now()
                self.db.complete_collection_run(run_id, result)
                return result

            logger.info("ATTOM enrichment: %d properties to process.", total)

            enriched_count = 0
            found_count = 0
            batch_updates: list[dict] = []
            batch_size = 25  # commit every N records

            for i, row in enumerate(rows, 1):
                prop_id = row["id"]
                address = row["address"]
                zip_code = row.get("zip_code", "")

                try:
                    update = self._enrich_single(prop_id, address, zip_code)
                    batch_updates.append(update)

                    if update.get("beds") is not None or update.get("sqft") is not None:
                        found_count += 1

                    enriched_count += 1

                except Exception as e:
                    logger.warning(
                        "Error enriching %s (id=%d): %s",
                        address, prop_id, e,
                    )
                    # Mark as enriched to avoid retrying on every run
                    batch_updates.append({
                        "id": prop_id,
                        "attom_enriched": True,
                    })
                    result.errors.append(f"{address}: {e}")

                # Batch commit
                if len(batch_updates) >= batch_size:
                    self.db.update_properties_attom_batch(batch_updates)
                    batch_updates = []

                # Progress logging
                if i % batch_size == 0 or i == total:
                    logger.info(
                        "ATTOM progress: %d/%d processed (%d found data).",
                        i, total, found_count,
                    )

                # Rate limiting
                if i < total:
                    time.sleep(delay)

            # Flush remaining updates
            if batch_updates:
                self.db.update_properties_attom_batch(batch_updates)

            result.records_fetched = total
            result.records_inserted = found_count
            result.records_duplicates = enriched_count - found_count

            logger.info(
                "ATTOM enrichment complete: %d processed, %d found data, %d no data.",
                enriched_count, found_count, enriched_count - found_count,
            )

        except Exception as e:
            logger.error("ATTOM enrichment failed: %s", e)
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result

    def _enrich_single(self, prop_id: int, address: str, zip_code: str) -> dict:
        """Enrich a single property from ATTOM.

        Calls both property/detail and sale/detail endpoints.

        Args:
            prop_id: Database row ID.
            address: Street address for ATTOM lookup.
            zip_code: Zip code to build address2.

        Returns:
            Dict of fields to update in the properties table.
        """
        update: dict = {
            "id": prop_id,
            "attom_enriched": True,
        }

        # Parse address for ATTOM lookup:
        # ATTOM expects address1 = street address, address2 = "city, state zip"
        # Our addresses are like "1234 CEDAR ST BERKELEY 94702"
        # We need to extract just the street part
        address1 = _extract_street_address(address)
        address2 = f"Berkeley, CA {zip_code}" if zip_code else "Berkeley, CA"

        # --- Property detail ---
        detail = self.attom.lookup_property(address1, address2)
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

        # --- Last sale ---
        sale_price, sale_date = self.attom.lookup_last_sale(address1, address2)
        if sale_price:
            update["last_sale_price"] = sale_price
        if sale_date:
            update["last_sale_date"] = sale_date

        return update


def _extract_street_address(full_address: str) -> str:
    """Extract just the street address from a full address string.

    Our addresses look like: "1234 CEDAR ST BERKELEY 94702"
    or "1234 CEDAR ST" (already just the street part).

    ATTOM expects just "1234 Cedar St" for address1.

    Strategy: remove the city name and zip code if present.
    """
    addr = full_address.strip()

    # Remove trailing zip code (5 digits)
    import re
    addr = re.sub(r"\s+\d{5}(-\d{4})?$", "", addr)

    # Remove city name at the end
    for city in ("BERKELEY", "ALBANY", "EMERYVILLE", "OAKLAND", "KENSINGTON"):
        if addr.upper().endswith(f" {city}"):
            addr = addr[: -(len(city) + 1)].strip()
            break

    return addr.strip()
