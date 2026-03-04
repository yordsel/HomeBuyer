"""Collector for FRED (Federal Reserve Economic Data).

Uses the direct CSV download endpoint which requires no API key.

Fetches two categories of data:
1. Mortgage rates: MORTGAGE30US (30-year fixed), MORTGAGE15US (15-year fixed)
2. Economic indicators: NASDAQ, 10-Year Treasury, Consumer Sentiment,
   Bay Area CPI, SF Metro Unemployment
"""

import csv
import io
import logging
from datetime import date, datetime

from homebuyer.config import (
    FRED_CSV_URL,
    FRED_ECONOMIC_SERIES,
    FRED_SERIES_15YR,
    FRED_SERIES_30YR,
)
from homebuyer.storage.database import Database
from homebuyer.storage.models import CollectionResult, EconomicIndicator, MortgageRate
from homebuyer.utils.http import create_session

logger = logging.getLogger(__name__)


class FredCollector:
    """Fetches mortgage rate data from FRED."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.session = create_session()

    def collect(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> CollectionResult:
        """Download MORTGAGE30US and MORTGAGE15US, insert into mortgage_rates.

        Args:
            start_date: Start of date range (default: 2018-01-01 for ~7 years).
            end_date: End of date range (default: today).

        Returns:
            A CollectionResult summarizing what was collected.
        """
        result = CollectionResult(source="fred", started_at=datetime.now())
        run_id = self.db.start_collection_run("fred")

        if start_date is None:
            start_date = date(2018, 1, 1)
        if end_date is None:
            end_date = date.today()

        try:
            # Fetch both series in a single CSV download
            # FRED supports multiple series IDs comma-separated
            url = FRED_CSV_URL
            params = {
                "id": f"{FRED_SERIES_30YR},{FRED_SERIES_15YR}",
                "cosd": start_date.isoformat(),
                "coed": end_date.isoformat(),
            }

            logger.info(
                "Fetching FRED mortgage rates from %s to %s...",
                start_date, end_date,
            )

            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            rates = self._parse_csv(response.text, start_date=start_date, end_date=end_date)
            result.records_fetched = len(rates)

            logger.info("Parsed %d rate observations. Inserting...", len(rates))

            affected = self.db.upsert_mortgage_rates_batch(rates)
            result.records_inserted = affected
            result.records_duplicates = len(rates) - affected

            logger.info(
                "Mortgage rates: %d inserted/updated, %d unchanged.",
                affected,
                result.records_duplicates,
            )

        except Exception as e:
            logger.error("FRED collection failed: %s", e)
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result

    def collect_indicators(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> CollectionResult:
        """Download economic indicator series from FRED.

        Fetches each series individually (they have different frequencies)
        and stores them in the generic economic_indicators table.

        Args:
            start_date: Start of date range (default: 2018-01-01).
            end_date: End of date range (default: today).

        Returns:
            A CollectionResult summarizing what was collected.
        """
        result = CollectionResult(source="fred_indicators", started_at=datetime.now())
        run_id = self.db.start_collection_run("fred_indicators")

        if start_date is None:
            start_date = date(2018, 1, 1)
        if end_date is None:
            end_date = date.today()

        all_indicators: list[EconomicIndicator] = []

        try:
            for series_id, description in FRED_ECONOMIC_SERIES.items():
                logger.info("Fetching FRED series %s (%s)...", series_id, description)

                params = {
                    "id": series_id,
                    "cosd": start_date.isoformat(),
                    "coed": end_date.isoformat(),
                }
                response = self.session.get(
                    FRED_CSV_URL, params=params, timeout=30
                )
                response.raise_for_status()

                indicators = self._parse_indicator_csv(
                    response.text, series_id,
                    start_date=start_date, end_date=end_date,
                )
                logger.info(
                    "  %s: parsed %d observations.", series_id, len(indicators)
                )
                all_indicators.extend(indicators)

            result.records_fetched = len(all_indicators)

            if all_indicators:
                affected = self.db.upsert_economic_indicators_batch(all_indicators)
                result.records_inserted = affected
                result.records_duplicates = len(all_indicators) - affected

            logger.info(
                "Economic indicators: %d total, %d inserted/updated, %d unchanged.",
                result.records_fetched,
                result.records_inserted,
                result.records_duplicates,
            )

        except Exception as e:
            logger.error("FRED indicator collection failed: %s", e)
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)
        return result

    def _parse_indicator_csv(
        self,
        text: str,
        series_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[EconomicIndicator]:
        """Parse a single-series FRED CSV into EconomicIndicator objects.

        Args:
            text: The CSV response text.
            series_id: The FRED series ID (used as the series_id in DB).
            start_date: Only include observations on or after this date.
            end_date: Only include observations on or before this date.
        """
        indicators: list[EconomicIndicator] = []
        reader = csv.DictReader(io.StringIO(text))

        for row in reader:
            date_str = (
                row.get("observation_date", "")
                or row.get("DATE", "")
            ).strip()
            if not date_str:
                continue

            try:
                obs_date = date.fromisoformat(date_str)
            except ValueError:
                continue

            if start_date and obs_date < start_date:
                continue
            if end_date and obs_date > end_date:
                continue

            value = _parse_fred_value(row.get(series_id))
            if value is None:
                continue

            indicators.append(
                EconomicIndicator(
                    series_id=series_id,
                    observation_date=obs_date,
                    value=value,
                )
            )

        return indicators

    def _parse_csv(
        self,
        text: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[MortgageRate]:
        """Parse FRED's CSV response into MortgageRate objects.

        FRED CSV format:
            observation_date,MORTGAGE30US,MORTGAGE15US
            2018-01-04,3.95,3.38
            2018-01-11,3.99,3.44
            ...

        Missing values are represented as empty strings.

        Args:
            text: The CSV response text.
            start_date: Only include observations on or after this date.
            end_date: Only include observations on or before this date.
        """
        rates: list[MortgageRate] = []
        reader = csv.DictReader(io.StringIO(text))

        for row in reader:
            # FRED uses 'observation_date' as the column header
            date_str = (
                row.get("observation_date", "")
                or row.get("DATE", "")
            ).strip()
            if not date_str:
                continue

            try:
                obs_date = date.fromisoformat(date_str)
            except ValueError:
                logger.debug("Skipping unparseable FRED date: %s", date_str)
                continue

            # Filter by date range (FRED ignores cosd/coed for multi-series CSV)
            if start_date and obs_date < start_date:
                continue
            if end_date and obs_date > end_date:
                continue

            rate_30 = _parse_fred_value(row.get(FRED_SERIES_30YR))
            rate_15 = _parse_fred_value(row.get(FRED_SERIES_15YR))

            # Skip rows where both rates are missing
            if rate_30 is None and rate_15 is None:
                continue

            rates.append(
                MortgageRate(
                    observation_date=obs_date,
                    rate_30yr=rate_30,
                    rate_15yr=rate_15,
                )
            )

        return rates


def _parse_fred_value(value: str | None) -> float | None:
    """Parse a FRED value, handling '.' as missing data."""
    if not value or value.strip() == "." or not value.strip():
        return None
    try:
        return float(value.strip())
    except (ValueError, TypeError):
        return None
