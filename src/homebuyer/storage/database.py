"""SQLite database manager with schema initialization and upsert operations."""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from homebuyer.storage.models import CollectionResult, MarketMetric, MortgageRate, PropertySale

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT
);

CREATE TABLE IF NOT EXISTS property_sales (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    mls_number          TEXT,
    address             TEXT NOT NULL,
    city                TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'CA',
    zip_code            TEXT NOT NULL,
    sale_date           TEXT NOT NULL,
    sale_price          INTEGER NOT NULL,
    sale_type           TEXT,
    property_type       TEXT,
    beds                REAL,
    baths               REAL,
    sqft                INTEGER,
    lot_size_sqft       INTEGER,
    year_built          INTEGER,
    price_per_sqft      REAL,
    hoa_per_month       INTEGER,
    latitude            REAL NOT NULL,
    longitude           REAL NOT NULL,
    neighborhood_raw    TEXT,
    neighborhood        TEXT,
    redfin_url          TEXT,
    days_on_market      INTEGER,
    collected_at        TEXT NOT NULL DEFAULT (datetime('now')),
    price_range_bucket  TEXT,
    CHECK (sale_price > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_mls
    ON property_sales(mls_number) WHERE mls_number IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_dedup
    ON property_sales(address, sale_date, sale_price);
CREATE INDEX IF NOT EXISTS idx_sales_date ON property_sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_neighborhood ON property_sales(neighborhood);
CREATE INDEX IF NOT EXISTS idx_sales_zip ON property_sales(zip_code);
CREATE INDEX IF NOT EXISTS idx_sales_price ON property_sales(sale_price);

CREATE TABLE IF NOT EXISTS market_metrics (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    period_begin                TEXT NOT NULL,
    period_end                  TEXT NOT NULL,
    period_duration             TEXT NOT NULL,
    region_name                 TEXT NOT NULL DEFAULT 'Berkeley, CA',
    property_type               TEXT,
    median_sale_price           INTEGER,
    median_list_price           INTEGER,
    median_ppsf                 REAL,
    homes_sold                  INTEGER,
    new_listings                INTEGER,
    inventory                   INTEGER,
    months_of_supply            REAL,
    median_dom                  INTEGER,
    avg_sale_to_list            REAL,
    sold_above_list_pct         REAL,
    price_drops_pct             REAL,
    off_market_in_two_weeks_pct REAL,
    UNIQUE(period_begin, period_duration, region_name, property_type)
);

CREATE INDEX IF NOT EXISTS idx_market_period ON market_metrics(period_begin);

CREATE TABLE IF NOT EXISTS mortgage_rates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_date    TEXT NOT NULL UNIQUE,
    rate_30yr           REAL,
    rate_15yr           REAL
);

CREATE INDEX IF NOT EXISTS idx_rates_date ON mortgage_rates(observation_date);

CREATE TABLE IF NOT EXISTS neighborhoods (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    aliases         TEXT,
    geometry_wkt    TEXT,
    centroid_lat    REAL,
    centroid_lon    REAL,
    area_sqmi       REAL
);

CREATE TABLE IF NOT EXISTS collection_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    completed_at        TEXT,
    status              TEXT NOT NULL DEFAULT 'running',
    records_fetched     INTEGER DEFAULT 0,
    records_inserted    INTEGER DEFAULT 0,
    records_duplicates  INTEGER DEFAULT 0,
    parameters          TEXT,
    error_message       TEXT
);
"""


class Database:
    """SQLite database manager for the HomeBuyer application."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def connect(self) -> "Database":
        """Open connection with WAL mode and row factory."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        logger.debug("Connected to database: %s", self.db_path)
        return self

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("Database connection closed.")

    def __enter__(self) -> "Database":
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def initialize_schema(self) -> None:
        """Create all tables if they don't exist."""
        self.conn.executescript(_SCHEMA_SQL)
        # Record schema version if not already set
        existing = self.conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0]
        if existing is None or existing < SCHEMA_VERSION:
            self.conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, description) VALUES (?, ?)",
                (SCHEMA_VERSION, "Initial schema"),
            )
            self.conn.commit()
        logger.info("Database schema initialized (version %d).", SCHEMA_VERSION)

    # ------------------------------------------------------------------
    # Property Sales
    # ------------------------------------------------------------------

    def upsert_sale(self, sale: PropertySale) -> bool:
        """Insert a property sale, skipping if duplicate. Returns True if inserted."""
        sql = """
            INSERT INTO property_sales (
                mls_number, address, city, state, zip_code, sale_date, sale_price,
                sale_type, property_type, beds, baths, sqft, lot_size_sqft,
                year_built, price_per_sqft, hoa_per_month, latitude, longitude,
                neighborhood_raw, neighborhood, redfin_url, days_on_market,
                price_range_bucket
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT DO NOTHING
        """
        params = (
            sale.mls_number,
            sale.address,
            sale.city,
            sale.state,
            sale.zip_code,
            sale.sale_date.isoformat(),
            sale.sale_price,
            sale.sale_type,
            sale.property_type,
            sale.beds,
            sale.baths,
            sale.sqft,
            sale.lot_size_sqft,
            sale.year_built,
            sale.price_per_sqft,
            sale.hoa_per_month,
            sale.latitude,
            sale.longitude,
            sale.neighborhood_raw,
            sale.neighborhood,
            sale.redfin_url,
            sale.days_on_market,
            sale.price_range_bucket,
        )
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor.rowcount > 0

    def upsert_sales_batch(self, sales: list[PropertySale]) -> tuple[int, int]:
        """Insert a batch of sales. Returns (inserted_count, duplicate_count)."""
        inserted = 0
        duplicates = 0
        sql = """
            INSERT INTO property_sales (
                mls_number, address, city, state, zip_code, sale_date, sale_price,
                sale_type, property_type, beds, baths, sqft, lot_size_sqft,
                year_built, price_per_sqft, hoa_per_month, latitude, longitude,
                neighborhood_raw, neighborhood, redfin_url, days_on_market,
                price_range_bucket
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT DO NOTHING
        """
        with self.conn:
            for sale in sales:
                params = (
                    sale.mls_number,
                    sale.address,
                    sale.city,
                    sale.state,
                    sale.zip_code,
                    sale.sale_date.isoformat(),
                    sale.sale_price,
                    sale.sale_type,
                    sale.property_type,
                    sale.beds,
                    sale.baths,
                    sale.sqft,
                    sale.lot_size_sqft,
                    sale.year_built,
                    sale.price_per_sqft,
                    sale.hoa_per_month,
                    sale.latitude,
                    sale.longitude,
                    sale.neighborhood_raw,
                    sale.neighborhood,
                    sale.redfin_url,
                    sale.days_on_market,
                    sale.price_range_bucket,
                )
                cursor = self.conn.execute(sql, params)
                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    duplicates += 1
        return inserted, duplicates

    # ------------------------------------------------------------------
    # Market Metrics
    # ------------------------------------------------------------------

    def upsert_market_metric(self, metric: MarketMetric) -> bool:
        """Insert or update a market metric row. Returns True if inserted/updated."""
        sql = """
            INSERT INTO market_metrics (
                period_begin, period_end, period_duration, region_name, property_type,
                median_sale_price, median_list_price, median_ppsf, homes_sold,
                new_listings, inventory, months_of_supply, median_dom,
                avg_sale_to_list, sold_above_list_pct, price_drops_pct,
                off_market_in_two_weeks_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(period_begin, period_duration, region_name, property_type)
            DO UPDATE SET
                period_end = excluded.period_end,
                median_sale_price = excluded.median_sale_price,
                median_list_price = excluded.median_list_price,
                median_ppsf = excluded.median_ppsf,
                homes_sold = excluded.homes_sold,
                new_listings = excluded.new_listings,
                inventory = excluded.inventory,
                months_of_supply = excluded.months_of_supply,
                median_dom = excluded.median_dom,
                avg_sale_to_list = excluded.avg_sale_to_list,
                sold_above_list_pct = excluded.sold_above_list_pct,
                price_drops_pct = excluded.price_drops_pct,
                off_market_in_two_weeks_pct = excluded.off_market_in_two_weeks_pct
        """
        params = (
            metric.period_begin.isoformat(),
            metric.period_end.isoformat(),
            metric.period_duration,
            metric.region_name,
            metric.property_type,
            metric.median_sale_price,
            metric.median_list_price,
            metric.median_ppsf,
            metric.homes_sold,
            metric.new_listings,
            metric.inventory,
            metric.months_of_supply,
            metric.median_dom,
            metric.avg_sale_to_list,
            metric.sold_above_list_pct,
            metric.price_drops_pct,
            metric.off_market_in_two_weeks_pct,
        )
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor.rowcount > 0

    def upsert_market_metrics_batch(self, metrics: list[MarketMetric]) -> int:
        """Insert/update a batch of market metrics. Returns count of affected rows."""
        affected = 0
        sql = """
            INSERT INTO market_metrics (
                period_begin, period_end, period_duration, region_name, property_type,
                median_sale_price, median_list_price, median_ppsf, homes_sold,
                new_listings, inventory, months_of_supply, median_dom,
                avg_sale_to_list, sold_above_list_pct, price_drops_pct,
                off_market_in_two_weeks_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(period_begin, period_duration, region_name, property_type)
            DO UPDATE SET
                period_end = excluded.period_end,
                median_sale_price = excluded.median_sale_price,
                median_list_price = excluded.median_list_price,
                median_ppsf = excluded.median_ppsf,
                homes_sold = excluded.homes_sold,
                new_listings = excluded.new_listings,
                inventory = excluded.inventory,
                months_of_supply = excluded.months_of_supply,
                median_dom = excluded.median_dom,
                avg_sale_to_list = excluded.avg_sale_to_list,
                sold_above_list_pct = excluded.sold_above_list_pct,
                price_drops_pct = excluded.price_drops_pct,
                off_market_in_two_weeks_pct = excluded.off_market_in_two_weeks_pct
        """
        with self.conn:
            for m in metrics:
                params = (
                    m.period_begin.isoformat(),
                    m.period_end.isoformat(),
                    m.period_duration,
                    m.region_name,
                    m.property_type,
                    m.median_sale_price,
                    m.median_list_price,
                    m.median_ppsf,
                    m.homes_sold,
                    m.new_listings,
                    m.inventory,
                    m.months_of_supply,
                    m.median_dom,
                    m.avg_sale_to_list,
                    m.sold_above_list_pct,
                    m.price_drops_pct,
                    m.off_market_in_two_weeks_pct,
                )
                cursor = self.conn.execute(sql, params)
                if cursor.rowcount > 0:
                    affected += 1
        return affected

    # ------------------------------------------------------------------
    # Mortgage Rates
    # ------------------------------------------------------------------

    def upsert_mortgage_rate(self, rate: MortgageRate) -> bool:
        """Insert or update a mortgage rate observation."""
        sql = """
            INSERT INTO mortgage_rates (observation_date, rate_30yr, rate_15yr)
            VALUES (?, ?, ?)
            ON CONFLICT(observation_date) DO UPDATE SET
                rate_30yr = excluded.rate_30yr,
                rate_15yr = excluded.rate_15yr
        """
        cursor = self.conn.execute(
            sql, (rate.observation_date.isoformat(), rate.rate_30yr, rate.rate_15yr)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def upsert_mortgage_rates_batch(self, rates: list[MortgageRate]) -> int:
        """Insert/update a batch of mortgage rates. Returns count of affected rows."""
        affected = 0
        sql = """
            INSERT INTO mortgage_rates (observation_date, rate_30yr, rate_15yr)
            VALUES (?, ?, ?)
            ON CONFLICT(observation_date) DO UPDATE SET
                rate_30yr = excluded.rate_30yr,
                rate_15yr = excluded.rate_15yr
        """
        with self.conn:
            for r in rates:
                cursor = self.conn.execute(
                    sql, (r.observation_date.isoformat(), r.rate_30yr, r.rate_15yr)
                )
                if cursor.rowcount > 0:
                    affected += 1
        return affected

    # ------------------------------------------------------------------
    # Neighborhoods
    # ------------------------------------------------------------------

    def upsert_neighborhood(
        self,
        name: str,
        aliases: list[str] | None = None,
        geometry_wkt: str | None = None,
        centroid_lat: float | None = None,
        centroid_lon: float | None = None,
        area_sqmi: float | None = None,
    ) -> None:
        """Insert or update a neighborhood reference record."""
        aliases_json = json.dumps(aliases) if aliases else None
        sql = """
            INSERT INTO neighborhoods (name, aliases, geometry_wkt, centroid_lat, centroid_lon, area_sqmi)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                aliases = excluded.aliases,
                geometry_wkt = excluded.geometry_wkt,
                centroid_lat = excluded.centroid_lat,
                centroid_lon = excluded.centroid_lon,
                area_sqmi = excluded.area_sqmi
        """
        self.conn.execute(sql, (name, aliases_json, geometry_wkt, centroid_lat, centroid_lon, area_sqmi))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Collection Runs (audit trail)
    # ------------------------------------------------------------------

    def start_collection_run(self, source: str, parameters: dict | None = None) -> int:
        """Record the start of a collection run. Returns the run ID."""
        params_json = json.dumps(parameters) if parameters else None
        cursor = self.conn.execute(
            "INSERT INTO collection_runs (source, started_at, parameters) VALUES (?, ?, ?)",
            (source, datetime.now().isoformat(), params_json),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def complete_collection_run(self, run_id: int, result: CollectionResult) -> None:
        """Record the completion of a collection run."""
        error_msg = "; ".join(result.errors) if result.errors else None
        status = "success" if result.success else "failed"
        self.conn.execute(
            """UPDATE collection_runs SET
                completed_at = ?, status = ?, records_fetched = ?,
                records_inserted = ?, records_duplicates = ?, error_message = ?
            WHERE id = ?""",
            (
                datetime.now().isoformat(),
                status,
                result.records_fetched,
                result.records_inserted,
                result.records_duplicates,
                error_msg,
                run_id,
            ),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Statistics / Status
    # ------------------------------------------------------------------

    def get_statistics(self) -> dict:
        """Return row counts and date ranges for all tables."""
        stats: dict = {}

        # Property sales
        row = self.conn.execute(
            "SELECT COUNT(*), MIN(sale_date), MAX(sale_date) FROM property_sales"
        ).fetchone()
        stats["property_sales"] = {
            "count": row[0],
            "min_date": row[1],
            "max_date": row[2],
        }

        # Neighborhood coverage
        row = self.conn.execute(
            "SELECT COUNT(*) FROM property_sales WHERE neighborhood IS NOT NULL"
        ).fetchone()
        total = stats["property_sales"]["count"]
        geocoded = row[0]
        stats["neighborhood_coverage"] = {
            "geocoded": geocoded,
            "total": total,
            "pct": round(geocoded / total * 100, 1) if total > 0 else 0,
        }

        # Market metrics
        row = self.conn.execute(
            "SELECT COUNT(*), MIN(period_begin), MAX(period_begin) FROM market_metrics"
        ).fetchone()
        stats["market_metrics"] = {
            "count": row[0],
            "min_date": row[1],
            "max_date": row[2],
        }

        # Mortgage rates
        row = self.conn.execute(
            "SELECT COUNT(*), MIN(observation_date), MAX(observation_date) FROM mortgage_rates"
        ).fetchone()
        stats["mortgage_rates"] = {
            "count": row[0],
            "min_date": row[1],
            "max_date": row[2],
        }

        # Neighborhoods
        row = self.conn.execute("SELECT COUNT(*) FROM neighborhoods").fetchone()
        stats["neighborhoods"] = {"count": row[0]}

        # Last collection run
        row = self.conn.execute(
            "SELECT source, completed_at, status FROM collection_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            stats["last_run"] = {
                "source": row[0],
                "completed_at": row[1],
                "status": row[2],
            }

        return stats

    # ------------------------------------------------------------------
    # Processing helpers
    # ------------------------------------------------------------------

    def get_sales_missing_neighborhood(self) -> list[dict]:
        """Get all sales where neighborhood is NULL, with lat/long."""
        rows = self.conn.execute(
            "SELECT id, latitude, longitude, neighborhood_raw FROM property_sales WHERE neighborhood IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_neighborhood(self, sale_id: int, neighborhood: str) -> None:
        """Set the normalized neighborhood for a property sale."""
        self.conn.execute(
            "UPDATE property_sales SET neighborhood = ? WHERE id = ?",
            (neighborhood, sale_id),
        )

    def update_neighborhoods_batch(self, updates: list[tuple[str, int]]) -> None:
        """Batch update neighborhoods. Each tuple is (neighborhood, sale_id)."""
        with self.conn:
            self.conn.executemany(
                "UPDATE property_sales SET neighborhood = ? WHERE id = ?",
                updates,
            )
