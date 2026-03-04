"""Collector for Census ACS (American Community Survey) income data.

Fetches median household income by zip code (ZCTA) from the Census
Bureau's public API. No API key is required for low-volume usage
(< 500 queries/day).

Data comes from ACS 5-year estimates, available from vintage year
2020 onward at the ZCTA level. Each vintage covers 5 years of data
(e.g., vintage 2023 covers 2019–2023).
"""

import logging
from datetime import datetime
from typing import Optional

import requests

from homebuyer.config import BERKELEY_ZIP_CODES, CENSUS_ACS_BASE_URL
from homebuyer.storage.database import Database
from homebuyer.storage.models import CensusIncome, CollectionResult

logger = logging.getLogger(__name__)

# ACS variable codes
_VAR_MEDIAN_INCOME = "B19013_001E"  # Median household income estimate
_VAR_MARGIN_OF_ERROR = "B19013_001M"  # Margin of error

# 5-year ACS vintages available at ZCTA level
# Pre-2020 requires different geography syntax; we start at 2020.
_ACS_VINTAGE_YEARS = [2020, 2021, 2022, 2023, 2024]


class CensusCollector:
    """Fetches median household income from the Census ACS API."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def collect(
        self,
        zip_codes: Optional[list[str]] = None,
        vintage_years: Optional[list[int]] = None,
    ) -> CollectionResult:
        """Download ACS median household income for Berkeley zip codes.

        Fetches data for each available vintage year and stores in the
        census_income table. Skips years that return errors (e.g., the
        most recent year's data may not be published yet).

        Args:
            zip_codes: List of zip codes to query (default: Berkeley zips).
            vintage_years: ACS vintage years to fetch (default: 2020–2024).

        Returns:
            A CollectionResult summarizing what was collected.
        """
        result = CollectionResult(source="census_acs", started_at=datetime.now())
        run_id = self.db.start_collection_run("census_acs")

        if zip_codes is None:
            zip_codes = list(BERKELEY_ZIP_CODES)
        if vintage_years is None:
            vintage_years = list(_ACS_VINTAGE_YEARS)

        all_records: list[CensusIncome] = []

        for year in vintage_years:
            try:
                records = self._fetch_year(year, zip_codes)
                all_records.extend(records)
                logger.info(
                    "ACS %d: fetched income for %d zip codes.", year, len(records)
                )
            except Exception as e:
                # Some vintage years may not be available yet
                logger.warning("ACS %d: skipping (%s).", year, e)

        result.records_fetched = len(all_records)

        if all_records:
            affected = self.db.upsert_census_income_batch(all_records)
            result.records_inserted = affected
            result.records_duplicates = len(all_records) - affected

        logger.info(
            "Census ACS: %d records fetched, %d inserted/updated, %d unchanged.",
            result.records_fetched,
            result.records_inserted,
            result.records_duplicates,
        )

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result

    def _fetch_year(
        self, year: int, zip_codes: list[str]
    ) -> list[CensusIncome]:
        """Fetch income data for a single ACS vintage year.

        Args:
            year: ACS vintage year (e.g., 2023).
            zip_codes: List of ZCTA codes to query.

        Returns:
            List of CensusIncome records.

        Raises:
            ValueError: If the API returns an error or no data.
        """
        zcta_list = ",".join(zip_codes)
        url = (
            f"{CENSUS_ACS_BASE_URL}/{year}/acs/acs5"
            f"?get=NAME,{_VAR_MEDIAN_INCOME},{_VAR_MARGIN_OF_ERROR}"
            f"&for=zip%20code%20tabulation%20area:{zcta_list}"
        )

        response = self.session.get(url, timeout=30)

        if response.status_code != 200:
            raise ValueError(
                f"Census API returned HTTP {response.status_code} for ACS {year}"
            )

        data = response.json()

        # Response format: first row is headers, subsequent rows are data
        # [["NAME","B19013_001E","B19013_001M","zip code tabulation area"],
        #  ["ZCTA5 94702","99135","5000","94702"], ...]
        if not data or len(data) < 2:
            raise ValueError(f"No data returned for ACS {year}")

        records: list[CensusIncome] = []
        headers = data[0]

        # Find column indices
        try:
            income_idx = headers.index(_VAR_MEDIAN_INCOME)
            moe_idx = headers.index(_VAR_MARGIN_OF_ERROR)
            zcta_idx = headers.index("zip code tabulation area")
        except ValueError as e:
            raise ValueError(f"Unexpected Census API response format: {e}") from e

        for row in data[1:]:
            zip_code = row[zcta_idx]
            income_str = row[income_idx]
            moe_str = row[moe_idx]

            # Census uses negative values or null for suppressed data
            income = _safe_int(income_str)
            if income is None or income <= 0:
                logger.debug(
                    "Skipping %s year %d: income=%s", zip_code, year, income_str
                )
                continue

            moe = _safe_int(moe_str)
            # Negative MOE means a calculated/substituted value
            if moe is not None and moe < 0:
                moe = abs(moe)

            records.append(
                CensusIncome(
                    zip_code=zip_code,
                    acs_year=year,
                    median_household_income=income,
                    margin_of_error=moe,
                )
            )

        return records


def _safe_int(value: Optional[str]) -> Optional[int]:
    """Parse an integer, returning None for invalid or null values."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
