"""Collector for Berkeley parcel data from the City of Berkeley Open Data portal.

Downloads residential parcel records from the Socrata API and stores them
in the ``properties`` table. The dataset contains ~29,000 total parcels
with APN, address, lat/lon, lot size, building sqft, and use code.

Socrata endpoint: https://data.cityofberkeley.info/resource/rax9-nuvx.json
"""

import logging
import time
from datetime import datetime
from typing import Optional

import requests

from homebuyer.config import BERKELEY_OPENDATA_PARCELS_URL
from homebuyer.storage.database import Database
from homebuyer.storage.models import BerkeleyParcel, CollectionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alameda County residential use codes → human-readable descriptions
# Source: Alameda County Assessor's Office
# ---------------------------------------------------------------------------

USE_CODE_MAP: dict[str, str] = {
    # Single family
    "1000": "Vacant Residential Land",
    "1100": "Single Family Residential",
    "1200": "Single Family Residential (misc. improvements)",
    "1400": "Single Family Residential (rural)",
    "1500": "Single Family Residential (rural, misc.)",
    "1505": "Single Family Residential (secondary)",
    "1600": "Single Family Residential (manufactured/mobile)",
    "1800": "Single Family Residential (other)",
    # Multi-family
    "2100": "Duplex (2 units)",
    "2200": "Duplex (2 units, misc.)",
    "2300": "Triplex (3 units)",
    "2400": "Fourplex (4 units)",
    "2500": "Multi-Family (5+ units, apartments)",
    "2501": "Multi-Family (5+ units, garden)",
    "2502": "Multi-Family (5+ units, high-rise)",
    "2600": "Multi-Family (mixed residential/commercial)",
    "2700": "Multi-Family (other)",
    # Condos / co-ops / townhouses
    "7100": "Condominium",
    "7200": "Planned Unit Development (PUD)",
    "7300": "Condominium (common area)",
    "7301": "Condominium (parking)",
    "7700": "Multi-Residential (5+ condos/co-ops)",
}

# Set of all residential use codes for filtering
RESIDENTIAL_USE_CODES = set(USE_CODE_MAP.keys())

# Socrata pagination limit
SOCRATA_BATCH_SIZE = 2000


class ParcelCollector:
    """Download Berkeley parcels from the City of Berkeley Open Data (Socrata) API."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def collect(
        self,
        min_lot_sqft: int = 4000,
        residential_only: bool = True,
    ) -> CollectionResult:
        """Fetch parcels from Socrata API with pagination.

        Args:
            min_lot_sqft: Minimum lot size in square feet. Parcels below
                this threshold are excluded. Set to 0 to include all.
            residential_only: If True, only include parcels with residential
                use codes.

        Returns:
            A CollectionResult summarizing what was collected.
        """
        result = CollectionResult(source="parcels", started_at=datetime.now())
        run_id = self.db.start_collection_run("parcels")

        try:
            raw_records = self._fetch_all(min_lot_sqft=min_lot_sqft)
            parcels = self._parse_records(
                raw_records,
                residential_only=residential_only,
            )
            result.records_fetched = len(parcels)

            if parcels:
                inserted, updated = self.db.upsert_properties_batch(parcels)
                result.records_inserted = inserted + updated
                result.records_duplicates = len(parcels) - inserted - updated

            logger.info(
                "Parcels: %d fetched, %d inserted/updated, %d unchanged.",
                result.records_fetched,
                result.records_inserted,
                result.records_duplicates,
            )

        except Exception as e:
            logger.error("Parcel collection failed: %s", e)
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result

    def _fetch_all(self, min_lot_sqft: int = 4000) -> list[dict]:
        """Fetch all matching parcels from the Socrata API with pagination.

        Uses server-side filtering on lot_size to reduce data transfer,
        then client-side filtering on use codes.

        Args:
            min_lot_sqft: Minimum lot size filter (applied server-side).

        Returns:
            List of raw Socrata JSON records.
        """
        all_records: list[dict] = []
        offset = 0

        # Build server-side filter
        where_clause = f"lot_size >= {min_lot_sqft}" if min_lot_sqft > 0 else ""

        while True:
            params: dict[str, str | int] = {
                "$limit": SOCRATA_BATCH_SIZE,
                "$offset": offset,
                "$order": ":id",  # stable ordering for pagination
            }
            if where_clause:
                params["$where"] = where_clause

            logger.info(
                "Fetching parcels: offset=%d, limit=%d ...",
                offset, SOCRATA_BATCH_SIZE,
            )

            response = self.session.get(
                BERKELEY_OPENDATA_PARCELS_URL,
                params=params,
                timeout=60,
            )

            if response.status_code != 200:
                raise ValueError(
                    f"Socrata API returned HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )

            batch = response.json()
            if not batch:
                break  # no more records

            all_records.extend(batch)
            logger.info(
                "  Received %d records (total so far: %d).",
                len(batch), len(all_records),
            )

            if len(batch) < SOCRATA_BATCH_SIZE:
                break  # last page

            offset += SOCRATA_BATCH_SIZE
            time.sleep(1.0)  # politeness delay between pages

        logger.info(
            "Socrata: fetched %d total raw parcel records.",
            len(all_records),
        )
        return all_records

    def _parse_records(
        self,
        raw_records: list[dict],
        residential_only: bool = True,
    ) -> list[BerkeleyParcel]:
        """Parse Socrata JSON into BerkeleyParcel objects.

        Applies use-code filtering and extracts lat/lon from the dataset.

        Args:
            raw_records: Raw JSON records from the Socrata API.
            residential_only: If True, only include residential use codes.

        Returns:
            List of BerkeleyParcel objects ready for DB insertion.
        """
        parcels: list[BerkeleyParcel] = []
        skipped_no_coords = 0
        skipped_use_code = 0

        for row in raw_records:
            apn = row.get("apn") or row.get("assessor_parcel_number")
            if not apn:
                continue

            # Use code filtering
            use_code = str(row.get("use_code", "") or "").strip()
            if residential_only and use_code not in RESIDENTIAL_USE_CODES:
                skipped_use_code += 1
                continue

            # Extract coordinates
            lat = _safe_float(row.get("latitude"))
            lon = _safe_float(row.get("longitude"))

            # Fallback: try the_geom if lat/lon columns aren't present
            if lat is None or lon is None:
                geom = row.get("the_geom")
                if isinstance(geom, dict):
                    coords = geom.get("coordinates")
                    if coords:
                        # GeoJSON is [lon, lat] for Point, or centroid for Polygon
                        if geom.get("type") == "Point":
                            lon, lat = coords[0], coords[1]
                        elif geom.get("type") in ("Polygon", "MultiPolygon"):
                            # Calculate centroid from first ring
                            try:
                                from shapely.geometry import shape
                                centroid = shape(geom).centroid
                                lon, lat = centroid.x, centroid.y
                            except Exception:
                                pass

            if lat is None or lon is None:
                skipped_no_coords += 1
                continue

            # Parse address components
            # Socrata field names: situs_addre, situs_stree, situs_str_1, situs_zip
            address_raw = (
                row.get("situs_addre")
                or row.get("primary_address")
                or row.get("address")
                or ""
            )
            street_number = (
                row.get("situs_stree")
                or row.get("street_number")
                or row.get("house_number")
                or ""
            )
            street_name = (
                row.get("situs_str_1")
                or row.get("street_name")
                or ""
            )

            # Build full address if not directly available
            if not address_raw and street_number and street_name:
                address_raw = f"{street_number} {street_name}"

            address = address_raw.strip().upper()
            if not address:
                continue

            # Extract zip code
            zip_code = str(
                row.get("situs_zip") or row.get("zip_code") or row.get("zip") or ""
            ).strip()
            if not zip_code:
                # Default to Berkeley zip if not present
                zip_code = "94702"

            # Lot and building size
            lot_size = _safe_int(row.get("lot_size"))
            building_sqft = _safe_int(
                row.get("building_ar")
                or row.get("building_sqft")
                or row.get("bldg_sqft")
            )

            # Use code description
            use_description = USE_CODE_MAP.get(use_code)

            parcels.append(
                BerkeleyParcel(
                    apn=apn.strip(),
                    address=address,
                    street_number=str(street_number).strip(),
                    street_name=str(street_name).strip().upper(),
                    zip_code=zip_code,
                    latitude=lat,
                    longitude=lon,
                    lot_size_sqft=lot_size or 0,
                    building_sqft=building_sqft,
                    use_code=use_code,
                    use_description=use_description,
                )
            )

        logger.info(
            "Parsed %d parcels from %d raw records "
            "(skipped: %d non-residential, %d missing coords).",
            len(parcels),
            len(raw_records),
            skipped_use_code,
            skipped_no_coords,
        )
        return parcels


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: object) -> Optional[float]:
    """Parse a float, returning None for invalid or null values."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: object) -> Optional[int]:
    """Parse an integer, returning None for invalid or null values."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None
