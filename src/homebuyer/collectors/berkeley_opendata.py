"""Collector for Berkeley Open Data (Socrata) — BESO energy benchmarking.

Fetches BESO (Building Energy Saving Ordinance) records from the City
of Berkeley's open data portal. No API key is required.

The dataset contains energy benchmarking data for commercial and large
residential buildings (>15,000 sqft). Since Jan 1, 2026, BESO compliance
is required at time of sale.

Socrata endpoint: https://data.cityofberkeley.info/resource/8k7b-6awf.json
"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from homebuyer.config import BERKELEY_OPENDATA_BESO_URL
from homebuyer.storage.database import Database
from homebuyer.storage.models import BESORecord, CollectionResult
from homebuyer.utils.parse import safe_float, safe_int

logger = logging.getLogger(__name__)

# Socrata field mappings by reporting year
# The dataset uses year-prefixed field names like "_2024_energy_star_score"
_YEAR_FIELDS = {
    2024: {
        "energy_star_score": "_2024_energy_star_score",
        "site_eui": "_2024_site_eui_kbtu_ft2_",
        "benchmark_status": "_2024_benchmark_status",
    },
    2023: {
        "energy_star_score": "_2023_energy_star_score",
        "site_eui": "_2023_site_eui_kbtu_ft2_",
        "benchmark_status": "_2023_benchmark_status",
    },
    2022: {
        "energy_star_score": "_2022_energy_star_score",
        "site_eui": "_2022_site_eui_kbtu_ft2_",
        "benchmark_status": "_2022_benchmark_status",
    },
    2021: {
        "energy_star_score": "_2021_energy_star_score",
        "site_eui": "_2021_site_eui_kbtu_ft2_",
        "benchmark_status": "_2021_benchmark_status",
    },
}


class BESOCollector:
    """Fetches BESO energy benchmarking data from Berkeley Open Data."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def collect(self, local_file: Optional[Path] = None) -> CollectionResult:
        """Download all BESO records and store in the database.

        Each Socrata row contains multi-year data. We extract the most
        recent year's data as separate records per reporting year.

        Args:
            local_file: Optional path to a locally-downloaded JSON or CSV
                file from the Berkeley Open Data portal. Use this when
                the Socrata API is blocked.

        Returns:
            A CollectionResult summarizing what was collected.
        """
        result = CollectionResult(source="beso", started_at=datetime.now())
        run_id = self.db.start_collection_run("beso")

        try:
            if local_file:
                raw_records = self._load_local(local_file)
            else:
                raw_records = self._fetch_all()
            beso_records = self._parse_records(raw_records)
            result.records_fetched = len(beso_records)

            if beso_records:
                affected = self.db.upsert_beso_records_batch(beso_records)
                result.records_inserted = affected
                result.records_duplicates = len(beso_records) - affected

            logger.info(
                "BESO: %d records fetched, %d inserted/updated, %d unchanged.",
                result.records_fetched,
                result.records_inserted,
                result.records_duplicates,
            )

        except Exception as e:
            logger.error("BESO collection failed: %s", e)
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result

    def _fetch_all(self) -> list[dict]:
        """Fetch all BESO records from the Socrata API."""
        url = f"{BERKELEY_OPENDATA_BESO_URL}?$limit=5000"
        response = self.session.get(url, timeout=30)

        if response.status_code != 200:
            raise ValueError(
                f"Berkeley Open Data API returned HTTP {response.status_code}"
            )

        data = response.json()
        logger.info("BESO: fetched %d raw records from Socrata.", len(data))
        return data

    def _load_local(self, path: Path) -> list[dict]:
        """Load BESO data from a local JSON or CSV file."""
        if path.suffix.lower() == ".json":
            with open(path) as f:
                data = json.load(f)
            logger.info("BESO: loaded %d records from %s.", len(data), path)
            return data

        # CSV: normalize column headers to match Socrata JSON field names
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # CSV headers use spaces/caps; Socrata JSON uses lowercase/underscores
                normalized = {
                    k.strip().lower().replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_"): v
                    for k, v in row.items()
                }
                rows.append(normalized)
        logger.info("BESO: loaded %d records from %s.", len(rows), path)
        return rows

    def _parse_records(self, raw_records: list[dict]) -> list[BESORecord]:
        """Parse Socrata JSON into BESORecord objects.

        Each raw record may contain data for multiple years. We create
        a separate BESORecord for the most recent year that has data.
        """
        records: list[BESORecord] = []

        for row in raw_records:
            beso_id = row.get("beso_id")
            address = row.get("building_address")
            if not beso_id or not address:
                continue

            property_type = row.get("beso_property_type")
            floor_area = safe_int(row.get("floor_area"))
            assessment_status = row.get("assessment_first_cycle_status")

            # Extract the most recent year with data
            for year in sorted(_YEAR_FIELDS.keys(), reverse=True):
                fields = _YEAR_FIELDS[year]
                score_key = fields["energy_star_score"]
                eui_key = fields["site_eui"]
                status_key = fields["benchmark_status"]

                score = safe_int(row.get(score_key))
                eui = safe_float(row.get(eui_key))
                bench_status = row.get(status_key)

                # Only create a record if we have at least some data
                if score is not None or eui is not None or bench_status:
                    records.append(
                        BESORecord(
                            beso_id=beso_id,
                            building_address=address.strip().upper(),
                            beso_property_type=property_type,
                            floor_area=floor_area,
                            energy_star_score=score,
                            site_eui=eui,
                            benchmark_status=bench_status,
                            assessment_status=assessment_status,
                            reporting_year=year,
                        )
                    )
                    break  # only keep most recent year

        return records


