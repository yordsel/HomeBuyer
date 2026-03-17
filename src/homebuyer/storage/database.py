"""Database manager with dual-mode support (SQLite + PostgreSQL).

When the DATABASE_URL environment variable is set, connects to PostgreSQL.
Otherwise falls back to a local SQLite file for development.
"""

import json
import logging
import math
import os
import re
import sqlite3
import calendar
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import psycopg2
    import psycopg2.extras

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

from homebuyer.storage.models import (
    BESORecord,
    BerkeleyParcel,
    BuildingPermit,
    CensusIncome,
    CollectionResult,
    EconomicIndicator,
    MarketMetric,
    MortgageRate,
    PropertySale,
    UseCode,
)

logger = logging.getLogger(__name__)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two points using the haversine formula."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Schema DDL (SQLite dialect — translated at runtime for Postgres)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 5

_SCHEMA_SQL_SQLITE = """
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
    sale_date           TEXT,
    sale_price          INTEGER,
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
    zoning_class        TEXT,
    redfin_url          TEXT,
    days_on_market      INTEGER,
    collected_at        TEXT NOT NULL DEFAULT (datetime('now')),
    price_range_bucket  TEXT,
    data_source         TEXT,
    CHECK (sale_price IS NULL OR sale_price > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_mls
    ON property_sales(mls_number) WHERE mls_number IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_dedup
    ON property_sales(address, sale_date, sale_price)
    WHERE sale_date IS NOT NULL AND sale_price IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_dedup_property_only
    ON property_sales(address)
    WHERE sale_date IS NULL AND sale_price IS NULL;
CREATE INDEX IF NOT EXISTS idx_sales_date ON property_sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_neighborhood ON property_sales(neighborhood);
CREATE INDEX IF NOT EXISTS idx_sales_zip ON property_sales(zip_code);
CREATE INDEX IF NOT EXISTS idx_sales_price ON property_sales(sale_price);
CREATE INDEX IF NOT EXISTS idx_sales_zoning ON property_sales(zoning_class);

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

CREATE TABLE IF NOT EXISTS economic_indicators (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id           TEXT NOT NULL,
    observation_date    TEXT NOT NULL,
    value               REAL NOT NULL,
    UNIQUE(series_id, observation_date)
);

CREATE INDEX IF NOT EXISTS idx_econ_series_date
    ON economic_indicators(series_id, observation_date);

CREATE TABLE IF NOT EXISTS census_income (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    zip_code                    TEXT NOT NULL,
    acs_year                    INTEGER NOT NULL,
    median_household_income     INTEGER NOT NULL,
    margin_of_error             INTEGER,
    UNIQUE(zip_code, acs_year)
);

CREATE INDEX IF NOT EXISTS idx_census_zip_year
    ON census_income(zip_code, acs_year);

CREATE TABLE IF NOT EXISTS neighborhoods (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    aliases         TEXT,
    geometry_wkt    TEXT,
    centroid_lat    REAL,
    centroid_lon    REAL,
    area_sqmi       REAL
);

CREATE TABLE IF NOT EXISTS building_permits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    record_number       TEXT NOT NULL,
    permit_type         TEXT,
    status              TEXT,
    address             TEXT NOT NULL,
    zip_code            TEXT,
    parcel_id           TEXT,
    description         TEXT,
    job_value           REAL,
    construction_type   TEXT,
    contractor_cslb     TEXT,
    owner_name          TEXT,
    filed_date          TEXT,
    detail_url          TEXT,
    collected_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(record_number)
);

CREATE INDEX IF NOT EXISTS idx_permits_address ON building_permits(address);
CREATE INDEX IF NOT EXISTS idx_permits_filed ON building_permits(filed_date);
CREATE INDEX IF NOT EXISTS idx_permits_type ON building_permits(permit_type);

CREATE TABLE IF NOT EXISTS beso_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    beso_id             TEXT NOT NULL,
    building_address    TEXT NOT NULL,
    beso_property_type  TEXT,
    floor_area          INTEGER,
    energy_star_score   INTEGER,
    site_eui            REAL,
    benchmark_status    TEXT,
    assessment_status   TEXT,
    reporting_year      INTEGER,
    collected_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(beso_id, reporting_year)
);

CREATE INDEX IF NOT EXISTS idx_beso_address ON beso_records(building_address);
CREATE INDEX IF NOT EXISTS idx_beso_year ON beso_records(reporting_year);

CREATE TABLE IF NOT EXISTS properties (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    apn                 TEXT NOT NULL UNIQUE,
    address             TEXT NOT NULL,
    street_number       TEXT,
    street_name         TEXT,
    zip_code            TEXT NOT NULL,
    latitude            REAL NOT NULL,
    longitude           REAL NOT NULL,
    lot_size_sqft       INTEGER,
    building_sqft       INTEGER,
    use_code            TEXT,
    use_description     TEXT,
    neighborhood        TEXT,
    zoning_class        TEXT,
    beds                REAL,
    baths               REAL,
    sqft                INTEGER,
    year_built          INTEGER,
    property_type       TEXT,
    last_sale_date      TEXT,
    last_sale_price     INTEGER,
    rentcast_enriched   INTEGER NOT NULL DEFAULT 0,
    situs_unit          TEXT,
    property_category   TEXT,
    ownership_type      TEXT,
    record_type         TEXT,
    lot_group_key       TEXT,
    parcel_lot_size_sqft INTEGER,
    collected_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_properties_address ON properties(address);
CREATE INDEX IF NOT EXISTS idx_properties_zip ON properties(zip_code);
CREATE INDEX IF NOT EXISTS idx_properties_neighborhood ON properties(neighborhood);
CREATE INDEX IF NOT EXISTS idx_properties_zoning ON properties(zoning_class);
CREATE INDEX IF NOT EXISTS idx_properties_use_code ON properties(use_code);
CREATE INDEX IF NOT EXISTS idx_properties_lot_size ON properties(lot_size_sqft);
CREATE INDEX IF NOT EXISTS idx_properties_rentcast ON properties(rentcast_enriched);
CREATE INDEX IF NOT EXISTS idx_properties_lot_group ON properties(lot_group_key);
CREATE INDEX IF NOT EXISTS idx_properties_record_type ON properties(record_type);
CREATE INDEX IF NOT EXISTS idx_properties_category ON properties(property_category);

CREATE TABLE IF NOT EXISTS use_codes (
    use_code            TEXT PRIMARY KEY,
    description         TEXT NOT NULL,
    property_category   TEXT NOT NULL,
    ownership_type      TEXT NOT NULL,
    record_type         TEXT NOT NULL,
    estimated_units     INTEGER,
    is_residential      INTEGER NOT NULL DEFAULT 1,
    lot_size_meaning    TEXT,
    building_ar_meaning TEXT
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

CREATE TABLE IF NOT EXISTS predictions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    latitude                REAL NOT NULL,
    longitude               REAL NOT NULL,
    neighborhood            TEXT,
    zip_code                TEXT,
    beds                    REAL,
    baths                   REAL,
    sqft                    INTEGER,
    year_built              INTEGER,
    lot_size_sqft           INTEGER,
    property_type           TEXT,
    list_price              INTEGER,
    hoa_per_month           INTEGER,
    predicted_price         INTEGER NOT NULL,
    price_lower             INTEGER NOT NULL,
    price_upper             INTEGER NOT NULL,
    base_value              INTEGER,
    predicted_premium_pct   REAL,
    feature_contributions   TEXT,
    source                  TEXT NOT NULL DEFAULT 'chat',
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_predictions_location
    ON predictions(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_predictions_neighborhood
    ON predictions(neighborhood);
CREATE INDEX IF NOT EXISTS idx_predictions_created
    ON predictions(created_at);

CREATE TABLE IF NOT EXISTS api_response_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    cache_key       TEXT NOT NULL,
    request_params  TEXT,
    response_json   TEXT NOT NULL,
    http_status     INTEGER DEFAULT 200,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, endpoint, cache_key)
);

CREATE INDEX IF NOT EXISTS idx_api_cache_lookup
    ON api_response_cache(source, endpoint, cache_key);
CREATE INDEX IF NOT EXISTS idx_api_cache_fetched
    ON api_response_cache(fetched_at);

CREATE TABLE IF NOT EXISTS precomputed_scenarios (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id      INTEGER NOT NULL,
    scenario_type    TEXT NOT NULL DEFAULT 'buyer',
    prediction_json  TEXT NOT NULL,
    rental_json      TEXT,
    potential_json   TEXT,
    comparables_json TEXT,
    computed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    model_version    TEXT,
    UNIQUE(property_id, scenario_type)
);

CREATE INDEX IF NOT EXISTS idx_precomputed_property
    ON precomputed_scenarios(property_id);
CREATE INDEX IF NOT EXISTS idx_precomputed_type
    ON precomputed_scenarios(scenario_type);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT,
    full_name       TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS oauth_accounts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,
    provider            TEXT NOT NULL,
    provider_user_id    TEXT NOT NULL,
    email               TEXT,
    display_name        TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(provider, provider_user_id)
);

CREATE INDEX IF NOT EXISTS idx_oauth_accounts_user ON oauth_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_oauth_accounts_provider ON oauth_accounts(provider, provider_user_id);

CREATE TABLE IF NOT EXISTS fun_facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT NOT NULL,
    stat_key        TEXT NOT NULL,
    stat_value      TEXT NOT NULL,
    display_text    TEXT NOT NULL,
    detail_json     TEXT,
    generated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(category, stat_key)
);

CREATE INDEX IF NOT EXISTS idx_fun_facts_category ON fun_facts(category);

CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    session_id      TEXT NOT NULL UNIQUE,
    title           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id     INTEGER NOT NULL,
    role                TEXT NOT NULL,
    content             TEXT NOT NULL,
    blocks_json         TEXT,
    tools_used_json     TEXT,
    tool_events_json    TEXT,
    message_index       INTEGER NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conv_messages_conv ON conversation_messages(conversation_id);

CREATE TABLE IF NOT EXISTS tos_acceptances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    tos_version     TEXT NOT NULL,
    ip_address      TEXT,
    accepted_at     TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_tos_user ON tos_acceptances(user_id);
CREATE INDEX IF NOT EXISTS idx_conv_messages_idx ON conversation_messages(conversation_id, message_index);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    token_hash      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    revoked         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);

CREATE TABLE IF NOT EXISTS auth_activity_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    event_type      TEXT NOT NULL,
    ip_address      TEXT,
    user_agent      TEXT,
    success         INTEGER NOT NULL DEFAULT 1,
    detail          TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_auth_activity_user ON auth_activity_log(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_activity_type ON auth_activity_log(event_type);
CREATE INDEX IF NOT EXISTS idx_auth_activity_created ON auth_activity_log(created_at);

CREATE TABLE IF NOT EXISTS email_verification_tokens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    token_hash      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    used            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_email_verify_user ON email_verification_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_email_verify_hash ON email_verification_tokens(token_hash);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    token_hash      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    used            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_pw_reset_user ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_pw_reset_hash ON password_reset_tokens(token_hash);

-- ---------------------------------------------------------------------------
-- Faketor research context persistence (Phase G, schema v5)
--
-- One row per authenticated user. Anonymous users are in-memory only.
-- All complex state is JSON-serialized using the containers' to_dict()
-- methods (BuyerState, MarketSnapshot, PropertyState).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS research_contexts (
    user_id         INTEGER PRIMARY KEY,
    session_id      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_active     TEXT NOT NULL DEFAULT (datetime('now')),
    buyer_state     TEXT NOT NULL DEFAULT '{}',
    market_snapshot TEXT NOT NULL DEFAULT '{}',
    property_state  TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS buyer_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL UNIQUE,
    segment_id      TEXT,
    segment_confidence REAL NOT NULL DEFAULT 0.0,
    intent          TEXT,
    capital         INTEGER,
    equity          INTEGER,
    income          INTEGER,
    current_rent    INTEGER,
    profile_json    TEXT NOT NULL DEFAULT '{}',
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_buyer_profiles_segment ON buyer_profiles(segment_id);

CREATE TABLE IF NOT EXISTS property_analyses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    property_id     INTEGER NOT NULL,
    address         TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    result_summary  TEXT,
    conclusion      TEXT,
    computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    market_snapshot_at REAL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, property_id, tool_name)
);

CREATE INDEX IF NOT EXISTS idx_prop_analyses_user ON property_analyses(user_id);
CREATE INDEX IF NOT EXISTS idx_prop_analyses_property ON property_analyses(user_id, property_id);
"""


def _sqlite_to_postgres_ddl(sql: str) -> str:
    """Translate SQLite DDL to PostgreSQL DDL."""
    # Replace AUTOINCREMENT with SERIAL
    sql = re.sub(
        r"(\w+)\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
        r"\1 SERIAL PRIMARY KEY",
        sql,
        flags=re.IGNORECASE,
    )
    # Replace DEFAULT (datetime('now')) with a text-format-compatible default.
    # Since columns are TEXT, we need to store timestamps in the same ISO 8601
    # format that SQLite's datetime('now') produces: 'YYYY-MM-DD HH:MI:SS'.
    sql = re.sub(
        r"DEFAULT\s+\(datetime\('now'\)\)",
        "DEFAULT (TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))",
        sql,
        flags=re.IGNORECASE,
    )
    # Replace REAL with DOUBLE PRECISION (word-boundary aware to avoid
    # corrupting identifiers that happen to contain 'REAL').
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)
    return sql


def _adapt_sql(sql: str, backend: str) -> str:
    """Adapt a SQL string from SQLite dialect to PostgreSQL if needed.

    Handles:
    - ? → %s placeholder substitution
    - datetime('now') → TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
    - date('now', '-N years/months/days') → (CURRENT_DATE - INTERVAL 'N years/months/days')
    - date('now') → CURRENT_DATE
    - INSERT OR REPLACE → INSERT ... ON CONFLICT ... DO UPDATE (caller handles)
    - INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING (caller handles)
    """
    if backend == "sqlite":
        return sql
    # Escape existing % characters so psycopg2 doesn't treat them as
    # format specifiers (e.g. LIKE 'R-1%' → LIKE 'R-1%%'), then
    # replace ? placeholders with %s.
    sql = sql.replace("%", "%%")
    sql = sql.replace("?", "%s")
    # Replace inline datetime('now') with a UTC text timestamp to match
    # the TEXT column format used by SQLite's datetime('now').
    sql = re.sub(
        r"datetime\('now'\)",
        "TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')",
        sql,
        flags=re.IGNORECASE,
    )
    # Replace date('now', '-N <unit>') → (CURRENT_DATE - INTERVAL 'N <unit>')
    sql = re.sub(
        r"date\('now',\s*'-(\d+)\s+(year|month|day)s?'\)",
        r"(CURRENT_DATE - INTERVAL '\1 \2s')",
        sql,
        flags=re.IGNORECASE,
    )
    # Replace date('now') → CURRENT_DATE
    sql = re.sub(r"date\('now'\)", "CURRENT_DATE", sql, flags=re.IGNORECASE)
    return sql


class Database:
    """Dual-mode database manager for the HomeBuyer application.

    Supports SQLite (local development) and PostgreSQL (production).
    The backend is selected based on constructor arguments:
    - Pass a ``Path`` for SQLite
    - Pass a ``str`` (DATABASE_URL) for PostgreSQL
    """

    def __init__(self, db_source: Path | str) -> None:
        if isinstance(db_source, str) and db_source.startswith(("postgres://", "postgresql://")):
            if not HAS_PSYCOPG2:
                raise ImportError(
                    "psycopg2 is required for PostgreSQL. "
                    "Install with: pip install psycopg2-binary"
                )
            self.backend = "postgres"
            self._dsn = db_source
            self.db_path: Optional[Path] = None
        else:
            self.backend = "sqlite"
            self._dsn = ""
            self.db_path = Path(db_source) if isinstance(db_source, str) else db_source
        self._conn: Any = None

    @property
    def is_postgres(self) -> bool:
        return self.backend == "postgres"

    @property
    def conn(self):
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def connect(self, check_same_thread: bool = True) -> "Database":
        """Open connection."""
        if self.is_postgres:
            self._conn = psycopg2.connect(
                self._dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            self._conn.autocommit = False
            logger.debug("Connected to PostgreSQL database")
        else:
            assert self.db_path is not None
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.db_path), check_same_thread=check_same_thread
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            logger.debug("Connected to SQLite database: %s", self.db_path)
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

    # ------------------------------------------------------------------
    # SQL execution helpers (dialect-aware)
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple | list | None = None) -> Any:
        """Execute a SQL statement with dialect translation.

        For Postgres: translates ? → %s, datetime('now') → TO_CHAR(NOW() ...).
        Returns a cursor.
        """
        sql = _adapt_sql(sql, self.backend)
        if self.is_postgres:
            cur = self.conn.cursor()
            cur.execute(sql, tuple(params) if params else None)
            return cur
        else:
            return self.conn.execute(sql, tuple(params) if params else ())

    def executemany(self, sql: str, params_seq: list) -> Any:
        """Execute a parameterized statement for each parameter set."""
        sql = _adapt_sql(sql, self.backend)
        if self.is_postgres:
            cur = self.conn.cursor()
            for p in params_seq:
                cur.execute(sql, tuple(p))
            return cur
        else:
            return self.conn.executemany(sql, params_seq)

    def fetchone(self, sql: str, params: tuple | list | None = None) -> Optional[dict]:
        """Execute and fetch one row as a dict, or None."""
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        if self.is_postgres:
            return dict(row)
        return dict(row)

    def fetchall(self, sql: str, params: tuple | list | None = None) -> list[dict]:
        """Execute and fetch all rows as dicts."""
        cursor = self.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def fetchval(self, sql: str, params: tuple | list | None = None) -> Any:
        """Execute and fetch a single scalar value."""
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        if self.is_postgres:
            # RealDictRow — get the first value
            return list(row.values())[0]
        # sqlite3.Row
        return row[0]

    def commit(self) -> None:
        """Commit the current transaction."""
        self.conn.commit()

    # ------------------------------------------------------------------
    # Fun facts helpers
    # ------------------------------------------------------------------

    def upsert_fun_fact(
        self,
        category: str,
        stat_key: str,
        stat_value: str,
        display_text: str,
        detail_json: str | None = None,
    ) -> None:
        """Insert or replace a fun fact."""
        if self.is_postgres:
            self.execute(
                "INSERT INTO fun_facts (category, stat_key, stat_value, display_text, detail_json, generated_at) "
                "VALUES (?, ?, ?, ?, ?, "
                "TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')) "
                "ON CONFLICT (category, stat_key) DO UPDATE SET "
                "stat_value = EXCLUDED.stat_value, "
                "display_text = EXCLUDED.display_text, "
                "detail_json = EXCLUDED.detail_json, "
                "generated_at = TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')",
                (category, stat_key, stat_value, display_text, detail_json),
            )
            self.commit()
        else:
            self.execute(
                "INSERT OR REPLACE INTO fun_facts "
                "(category, stat_key, stat_value, display_text, detail_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (category, stat_key, stat_value, display_text, detail_json),
            )

    def get_random_fun_fact(self) -> Optional[dict]:
        """Return a single random fun fact."""
        return self.fetchone(
            "SELECT category, stat_key, stat_value, display_text, detail_json "
            "FROM fun_facts ORDER BY RANDOM() LIMIT 1"
        )

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        if self.is_postgres:
            row = self.fetchval(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ?",
                (table_name,),
            )
            return bool(row and row > 0)
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            return bool(row and row[0] > 0)

    def get_table_columns(self, table_name: str) -> set[str]:
        """Get the set of column names for a table."""
        if self.is_postgres:
            rows = self.fetchall(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = ?",
                (table_name,),
            )
            return {r["column_name"] for r in rows}
        else:
            rows = self.conn.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()
            return {row[1] for row in rows}

    def _now_cutoff(self, hours: int) -> str:
        """Return an ISO timestamp string for 'now minus N hours'.

        Used to replace SQLite's ``datetime('now', '-N hours')`` pattern.
        Works correctly with TEXT-typed timestamp columns on both SQLite and
        PostgreSQL because the comparison is purely string-based (ISO 8601
        strings sort chronologically).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return cutoff.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def date_cutoff(years: int = 0, months: int = 0, days: int = 0) -> str:
        """Return an ISO date string for 'today minus N years/months/days'.

        Replaces SQLite ``date('now', '-N years')`` with a backend-agnostic
        Python-computed string.  Since all date columns are stored as TEXT in
        ISO 8601 format (``YYYY-MM-DD``), plain string comparison (``>=``)
        works correctly on both SQLite and PostgreSQL.
        """
        today = date.today()
        # Approximate: shift year/month then subtract days
        y = today.year - years
        m = today.month - months
        while m < 1:
            y -= 1
            m += 12
        while m > 12:
            y += 1
            m -= 12
        # Clamp day to valid range for the target month
        max_day = calendar.monthrange(y, m)[1]
        d = min(today.day, max_day)
        result = date(y, m, d) - timedelta(days=days)
        return result.isoformat()

    def _insert_returning_id(self, sql: str, params: tuple | list) -> int:
        """Insert a row and return its auto-generated ID.

        For Postgres: appends RETURNING id.
        For SQLite: uses cursor.lastrowid.
        """
        if self.is_postgres:
            sql = _adapt_sql(sql, self.backend)
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
            cur = self.conn.cursor()
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
            return row["id"]
        else:
            cursor = self.conn.execute(sql, tuple(params))
            return cursor.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    def initialize_schema(self) -> None:
        """Create all tables if they don't exist."""
        # --- Migrations for existing databases ---
        if self.table_exists("property_sales"):
            existing_cols = self.get_table_columns("property_sales")
            if "zoning_class" not in existing_cols:
                self.execute("ALTER TABLE property_sales ADD COLUMN zoning_class TEXT")
                self.commit()
                logger.info("Migration: added zoning_class column to property_sales.")

            if "data_source" not in existing_cols:
                self.execute("ALTER TABLE property_sales ADD COLUMN data_source TEXT")
                self.execute(
                    "UPDATE property_sales SET data_source = 'redfin' WHERE data_source IS NULL"
                )
                self.commit()
                logger.info("Migration: added data_source column, backfilled as 'redfin'.")

        # --- Properties table migrations ---
        if self.table_exists("properties"):
            props_cols = self.get_table_columns("properties")
            new_props_cols = {
                "situs_unit": "TEXT",
                "property_category": "TEXT",
                "ownership_type": "TEXT",
                "record_type": "TEXT",
                "lot_group_key": "TEXT",
                "parcel_lot_size_sqft": "INTEGER",
            }
            for col_name, col_type in new_props_cols.items():
                if col_name not in props_cols:
                    self.execute(
                        f"ALTER TABLE properties ADD COLUMN {col_name} {col_type}"
                    )
                    self.commit()
                    logger.info("Migration: added %s column to properties.", col_name)

            # --- v4 migration: rename attom_enriched → rentcast_enriched ---
            if "attom_enriched" in props_cols and "rentcast_enriched" not in props_cols:
                self.execute(
                    "ALTER TABLE properties RENAME COLUMN attom_enriched TO rentcast_enriched"
                )
                # Replace the old index with one matching the new column name
                self.execute("DROP INDEX IF EXISTS idx_properties_attom")
                self.execute(
                    "CREATE INDEX IF NOT EXISTS idx_properties_rentcast "
                    "ON properties(rentcast_enriched)"
                )
                self.commit()
                logger.info(
                    "Migration v4: renamed attom_enriched → rentcast_enriched."
                )

        # --- v3 migration: make password_hash nullable for OAuth-only users ---
        if self.table_exists("users") and not self.is_postgres:
            # SQLite doesn't support ALTER COLUMN, so recreate table if needed
            # Check if password_hash is currently NOT NULL
            table_info = self.fetchall("PRAGMA table_info(users)")
            pw_col = next((c for c in table_info if c["name"] == "password_hash"), None)
            if pw_col and pw_col["notnull"]:
                logger.info("Migration v3: making password_hash nullable in users table.")
                # Temporarily disable FK enforcement for the table swap
                self.conn.execute("PRAGMA foreign_keys=OFF")
                # Drop leftover temp table from any interrupted previous migration
                self.execute("DROP TABLE IF EXISTS users_new")
                self.execute("""
                    CREATE TABLE users_new (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        email           TEXT NOT NULL UNIQUE,
                        password_hash   TEXT,
                        full_name       TEXT,
                        is_active       INTEGER NOT NULL DEFAULT 1,
                        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
                self.execute("""
                    INSERT INTO users_new (id, email, password_hash, full_name, is_active, created_at, updated_at)
                    SELECT id, email, password_hash, full_name, is_active, created_at, updated_at FROM users
                """)
                self.execute("DROP TABLE users")
                self.execute("ALTER TABLE users_new RENAME TO users")
                self.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
                self.commit()
                # Re-enable FK enforcement
                self.conn.execute("PRAGMA foreign_keys=ON")
                logger.info("Migration v3: users table recreated with nullable password_hash.")

        # --- Create/update schema ---
        if self.is_postgres:
            pg_ddl = _sqlite_to_postgres_ddl(_SCHEMA_SQL_SQLITE)
            # Split on semicolons and execute each statement individually
            for stmt in pg_ddl.split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        self.execute(stmt)
                    except Exception as e:
                        # Some statements may fail (e.g. duplicate index), that's OK
                        self.conn.rollback()
                        logger.debug("DDL statement skipped: %s", e)
            self.commit()
        else:
            self.conn.executescript(_SCHEMA_SQL_SQLITE)

        # Seed use_codes reference data after schema is created
        self._seed_use_codes()

        # Record schema version if not already set
        existing = self.fetchval("SELECT MAX(version) FROM schema_version")
        if existing is None or existing < SCHEMA_VERSION:
            if self.is_postgres:
                self.execute(
                    "INSERT INTO schema_version (version, description) VALUES (?, ?) "
                    "ON CONFLICT (version) DO UPDATE SET description = EXCLUDED.description",
                    (SCHEMA_VERSION, "Initial schema"),
                )
            else:
                self.conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version, description) VALUES (?, ?)",
                    (SCHEMA_VERSION, "Initial schema"),
                )
            self.commit()

        logger.info("Database schema initialized (version %d).", SCHEMA_VERSION)

    # ------------------------------------------------------------------
    # Use Codes Reference
    # ------------------------------------------------------------------

    def _seed_use_codes(self) -> None:
        """Populate the use_codes reference table with Alameda County Assessor codes."""
        count = self.fetchval("SELECT COUNT(*) FROM use_codes")
        if count and count > 0:
            return
        # fmt: off
        codes: list[tuple] = [
            # (use_code, description, property_category, ownership_type, record_type, estimated_units, is_residential, lot_size_meaning, building_ar_meaning)
            # --- Vacant land ---
            ("1000", "Vacant Residential Land", "land", "fee_simple", "lot", 0, 1, "parcel", None),
            # --- Single Family Residential ---
            ("1100", "Single Family Residential", "sfr", "fee_simple", "lot", 1, 1, "parcel", "building_footprint"),
            ("1200", "SFR with Misc. Improvements", "sfr", "fee_simple", "lot", 1, 1, "parcel", "building_footprint"),
            ("1400", "SFR Rural", "sfr", "fee_simple", "lot", 1, 1, "parcel", "building_footprint"),
            ("1500", "SFR Rural with Misc. Improvements", "sfr", "fee_simple", "lot", 1, 1, "parcel", "building_footprint"),
            ("1505", "Townhouse Style Condominium", "townhouse", "common_interest", "unit", 1, 1, "shared", "unit_area"),
            ("1600", "SFR Detached Site Condominium", "condo", "common_interest", "unit", 1, 1, "shared", "unit_area"),
            ("1800", "SFR Other", "sfr", "fee_simple", "lot", 1, 1, "parcel", "building_footprint"),
            # --- Multi-Family (2-4 units) ---
            ("2100", "Duplex", "duplex", "fee_simple", "lot", 2, 1, "parcel", "building_footprint"),
            ("2200", "Duplex – Better Quality", "duplex", "fee_simple", "lot", 2, 1, "parcel", "building_footprint"),
            ("2300", "Triplex", "triplex", "fee_simple", "lot", 3, 1, "parcel", "building_footprint"),
            ("2400", "Fourplex", "fourplex", "fee_simple", "lot", 4, 1, "parcel", "building_footprint"),
            ("2500", "2 Units – Lesser Quality", "duplex", "fee_simple", "lot", 2, 1, "parcel", "building_footprint"),
            ("2501", "5+ Unit Apartment – Garden Style", "apartment", "fee_simple", "lot", None, 1, "parcel", "building_footprint"),
            ("2502", "5+ Unit Apartment – High Rise", "apartment", "fee_simple", "lot", None, 1, "parcel", "building_footprint"),
            ("2600", "Mixed Residential/Commercial", "mixed_use", "fee_simple", "lot", None, 1, "parcel", "building_footprint"),
            ("2700", "Multi-Family Other", "apartment", "fee_simple", "lot", None, 1, "parcel", "building_footprint"),
            # --- Condominiums / Co-ops / PUDs ---
            ("7100", "Condominium", "condo", "common_interest", "unit", 1, 1, "shared", "unit_area"),
            ("7200", "Planned Unit Development (PUD)", "pud", "common_interest", "lot", 1, 1, "parcel", "building_footprint"),
            ("7300", "Condominium – Single Residential Living Unit", "condo", "common_interest", "unit", 1, 1, "shared", "unit_area"),
            ("7301", "Condominium – Residential Live/Work Unit", "condo", "common_interest", "unit", 1, 1, "shared", "unit_area"),
            ("7390", "Condominium – Common Area", "condo", "common_interest", "lot", 0, 0, "shared", None),
            ("7400", "Cooperative", "coop", "cooperative", "unit", 1, 1, "shared", "unit_area"),
            ("7700", "Multi-Residential (5+ Condos/Co-ops)", "condo", "common_interest", "unit", None, 1, "shared", "unit_area"),
            # --- Commercial / Other (non-residential, included for completeness) ---
            ("3100", "Store", "commercial", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("3200", "Store and Office Combination", "commercial", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("3500", "Service Station", "commercial", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("3600", "Garage and Auto Sales/Service", "commercial", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("4100", "Office Building – 1 Story", "commercial", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("4200", "Office Building – Multi-Story", "commercial", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("5100", "Industrial/Light Manufacturing", "commercial", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("5200", "Industrial/Heavy Manufacturing", "commercial", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("6100", "Church/Religious", "other", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("6200", "School/College", "other", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("6300", "Hospital/Medical", "other", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("6600", "Fraternity/Sorority", "other", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("6700", "Club/Lodge/Hall", "other", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("6800", "Parking Lot – Commercial", "commercial", "fee_simple", "lot", 0, 0, "parcel", None),
            ("6900", "Misc. Improvements (non-res.)", "other", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("8800", "Government Owned", "other", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("9100", "Utility Property", "other", "fee_simple", "lot", 0, 0, "parcel", "building_footprint"),
            ("9900", "Other/Miscellaneous", "other", "fee_simple", "lot", 0, 0, "parcel", None),
        ]
        # fmt: on

        if self.is_postgres:
            sql = """
                INSERT INTO use_codes (
                    use_code, description, property_category, ownership_type,
                    record_type, estimated_units, is_residential,
                    lot_size_meaning, building_ar_meaning
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (use_code) DO UPDATE SET
                    description = EXCLUDED.description,
                    property_category = EXCLUDED.property_category,
                    ownership_type = EXCLUDED.ownership_type,
                    record_type = EXCLUDED.record_type,
                    estimated_units = EXCLUDED.estimated_units,
                    is_residential = EXCLUDED.is_residential,
                    lot_size_meaning = EXCLUDED.lot_size_meaning,
                    building_ar_meaning = EXCLUDED.building_ar_meaning
            """
            cur = self.conn.cursor()
            for c in codes:
                cur.execute(sql, c)
            self.commit()
        else:
            sql = """
                INSERT OR REPLACE INTO use_codes (
                    use_code, description, property_category, ownership_type,
                    record_type, estimated_units, is_residential,
                    lot_size_meaning, building_ar_meaning
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            with self.conn:
                self.conn.executemany(sql, codes)
        logger.info("Seeded %d use codes into use_codes table.", len(codes))

    def get_use_codes(self, residential_only: bool = False) -> dict[str, UseCode]:
        """Load use codes from reference table as a dict keyed by use_code."""
        where = " WHERE is_residential = 1" if residential_only else ""
        rows = self.execute(
            f"SELECT use_code, description, property_category, ownership_type, "
            f"record_type, estimated_units, is_residential, lot_size_meaning, "
            f"building_ar_meaning FROM use_codes{where}"
        ).fetchall()
        result: dict[str, UseCode] = {}
        for r in rows:
            if self.is_postgres:
                result[r["use_code"]] = UseCode(
                    use_code=r["use_code"],
                    description=r["description"],
                    property_category=r["property_category"],
                    ownership_type=r["ownership_type"],
                    record_type=r["record_type"],
                    estimated_units=r["estimated_units"],
                    is_residential=bool(r["is_residential"]),
                    lot_size_meaning=r["lot_size_meaning"],
                    building_ar_meaning=r["building_ar_meaning"],
                )
            else:
                result[r[0]] = UseCode(
                    use_code=r[0],
                    description=r[1],
                    property_category=r[2],
                    ownership_type=r[3],
                    record_type=r[4],
                    estimated_units=r[5],
                    is_residential=bool(r[6]),
                    lot_size_meaning=r[7],
                    building_ar_meaning=r[8],
                )
        return result

    def get_residential_use_codes(self) -> set[str]:
        """Get the set of use codes classified as residential."""
        rows = self.execute(
            "SELECT use_code FROM use_codes WHERE is_residential = 1"
        ).fetchall()
        if self.is_postgres:
            return {r["use_code"] for r in rows}
        return {r[0] for r in rows}

    # ------------------------------------------------------------------
    # Property Sales
    # ------------------------------------------------------------------

    def upsert_sale(self, sale: PropertySale) -> bool:
        """Insert a property sale, skipping if duplicate. Returns True if inserted."""
        inserted, _ = self.upsert_sales_batch([sale])
        return inserted > 0

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
                price_range_bucket, data_source
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT DO NOTHING
        """
        adapted = _adapt_sql(sql, self.backend)
        with self.conn:
            for sale in sales:
                params = (
                    sale.mls_number,
                    sale.address,
                    sale.city,
                    sale.state,
                    sale.zip_code,
                    sale.sale_date.isoformat() if sale.sale_date else None,
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
                    sale.data_source,
                )
                if self.is_postgres:
                    cur = self.conn.cursor()
                    cur.execute(adapted, params)
                    if cur.rowcount > 0:
                        inserted += 1
                    else:
                        duplicates += 1
                else:
                    cursor = self.conn.execute(adapted, params)
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
        return self.upsert_market_metrics_batch([metric]) > 0

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
        adapted = _adapt_sql(sql, self.backend)
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
                if self.is_postgres:
                    cur = self.conn.cursor()
                    cur.execute(adapted, params)
                    if cur.rowcount > 0:
                        affected += 1
                else:
                    cursor = self.conn.execute(adapted, params)
                    if cursor.rowcount > 0:
                        affected += 1
        return affected

    # ------------------------------------------------------------------
    # Mortgage Rates
    # ------------------------------------------------------------------

    def upsert_mortgage_rate(self, rate: MortgageRate) -> bool:
        """Insert or update a mortgage rate observation."""
        return self.upsert_mortgage_rates_batch([rate]) > 0

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
        adapted = _adapt_sql(sql, self.backend)
        with self.conn:
            for r in rates:
                params = (r.observation_date.isoformat(), r.rate_30yr, r.rate_15yr)
                if self.is_postgres:
                    cur = self.conn.cursor()
                    cur.execute(adapted, params)
                    if cur.rowcount > 0:
                        affected += 1
                else:
                    cursor = self.conn.execute(adapted, params)
                    if cursor.rowcount > 0:
                        affected += 1
        return affected

    # ------------------------------------------------------------------
    # Economic Indicators
    # ------------------------------------------------------------------

    def upsert_economic_indicators_batch(
        self, indicators: list[EconomicIndicator]
    ) -> int:
        """Insert/update a batch of economic indicators. Returns affected rows."""
        affected = 0
        sql = """
            INSERT INTO economic_indicators (series_id, observation_date, value)
            VALUES (?, ?, ?)
            ON CONFLICT(series_id, observation_date) DO UPDATE SET
                value = excluded.value
        """
        adapted = _adapt_sql(sql, self.backend)
        with self.conn:
            for ind in indicators:
                params = (ind.series_id, ind.observation_date.isoformat(), ind.value)
                if self.is_postgres:
                    cur = self.conn.cursor()
                    cur.execute(adapted, params)
                    if cur.rowcount > 0:
                        affected += 1
                else:
                    cursor = self.conn.execute(adapted, params)
                    if cursor.rowcount > 0:
                        affected += 1
        return affected

    # ------------------------------------------------------------------
    # Census Income
    # ------------------------------------------------------------------

    def upsert_census_income_batch(self, records: list[CensusIncome]) -> int:
        """Insert/update a batch of Census income records. Returns affected rows."""
        affected = 0
        sql = """
            INSERT INTO census_income (
                zip_code, acs_year, median_household_income, margin_of_error
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(zip_code, acs_year) DO UPDATE SET
                median_household_income = excluded.median_household_income,
                margin_of_error = excluded.margin_of_error
        """
        adapted = _adapt_sql(sql, self.backend)
        with self.conn:
            for rec in records:
                params = (
                    rec.zip_code,
                    rec.acs_year,
                    rec.median_household_income,
                    rec.margin_of_error,
                )
                if self.is_postgres:
                    cur = self.conn.cursor()
                    cur.execute(adapted, params)
                    if cur.rowcount > 0:
                        affected += 1
                else:
                    cursor = self.conn.execute(adapted, params)
                    if cursor.rowcount > 0:
                        affected += 1
        return affected

    # ------------------------------------------------------------------
    # BESO Records
    # ------------------------------------------------------------------

    def upsert_beso_records_batch(self, records: list[BESORecord]) -> int:
        """Insert/update a batch of BESO records. Returns affected rows."""
        affected = 0
        sql = """
            INSERT INTO beso_records (
                beso_id, building_address, beso_property_type, floor_area,
                energy_star_score, site_eui, benchmark_status,
                assessment_status, reporting_year
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(beso_id, reporting_year) DO UPDATE SET
                building_address = excluded.building_address,
                beso_property_type = excluded.beso_property_type,
                floor_area = excluded.floor_area,
                energy_star_score = excluded.energy_star_score,
                site_eui = excluded.site_eui,
                benchmark_status = excluded.benchmark_status,
                assessment_status = excluded.assessment_status
        """
        adapted = _adapt_sql(sql, self.backend)
        with self.conn:
            for rec in records:
                params = (
                    rec.beso_id,
                    rec.building_address,
                    rec.beso_property_type,
                    rec.floor_area,
                    rec.energy_star_score,
                    rec.site_eui,
                    rec.benchmark_status,
                    rec.assessment_status,
                    rec.reporting_year,
                )
                if self.is_postgres:
                    cur = self.conn.cursor()
                    cur.execute(adapted, params)
                    if cur.rowcount > 0:
                        affected += 1
                else:
                    cursor = self.conn.execute(adapted, params)
                    if cursor.rowcount > 0:
                        affected += 1
        return affected

    def lookup_beso_by_address(self, address: str) -> list[dict]:
        """Look up BESO records by address (case-insensitive)."""
        normalized = address.strip().upper()
        return self.fetchall(
            """
            SELECT beso_id, building_address, beso_property_type, floor_area,
                   energy_star_score, site_eui, benchmark_status,
                   assessment_status, reporting_year
            FROM beso_records
            WHERE UPPER(TRIM(building_address)) = ?
            ORDER BY reporting_year DESC
            """,
            (normalized,),
        )

    # ------------------------------------------------------------------
    # Building Permits
    # ------------------------------------------------------------------

    def upsert_permits_batch(self, permits: list[BuildingPermit]) -> tuple[int, int]:
        """Insert a batch of building permits. Returns (inserted_count, duplicate_count)."""
        inserted = 0
        duplicates = 0
        sql = """
            INSERT INTO building_permits (
                record_number, permit_type, status, address, zip_code,
                parcel_id, description, job_value, construction_type,
                contractor_cslb, owner_name, filed_date, detail_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_number) DO UPDATE SET
                permit_type = excluded.permit_type,
                status = excluded.status,
                address = excluded.address,
                zip_code = excluded.zip_code,
                parcel_id = excluded.parcel_id,
                description = excluded.description,
                job_value = excluded.job_value,
                construction_type = excluded.construction_type,
                contractor_cslb = excluded.contractor_cslb,
                owner_name = excluded.owner_name,
                filed_date = excluded.filed_date,
                detail_url = excluded.detail_url
        """
        adapted = _adapt_sql(sql, self.backend)
        with self.conn:
            for p in permits:
                params = (
                    p.record_number,
                    p.permit_type,
                    p.status,
                    p.address,
                    p.zip_code,
                    p.parcel_id,
                    p.description,
                    p.job_value,
                    p.construction_type,
                    p.contractor_cslb,
                    p.owner_name,
                    p.filed_date,
                    p.detail_url,
                )
                if self.is_postgres:
                    cur = self.conn.cursor()
                    cur.execute(adapted, params)
                    if cur.rowcount > 0:
                        inserted += 1
                    else:
                        duplicates += 1
                else:
                    cursor = self.conn.execute(adapted, params)
                    if cursor.rowcount > 0:
                        inserted += 1
                    else:
                        duplicates += 1
        return inserted, duplicates

    def get_collected_permit_addresses(self) -> set[str]:
        """Return the set of addresses that already have permit data collected."""
        rows = self.execute(
            "SELECT DISTINCT UPPER(TRIM(address)) FROM building_permits"
        ).fetchall()
        if self.is_postgres:
            return {list(row.values())[0] for row in rows}
        return {row[0] for row in rows}

    def lookup_permits_by_address(self, address: str, limit: int = 50) -> list[dict]:
        """Return building permits for the given address, most recent first."""
        clean = address.strip().upper()
        # Try exact match first
        rows = self.fetchall(
            """
            SELECT record_number, permit_type, status, address, zip_code,
                   description, job_value, construction_type, filed_date, detail_url
            FROM building_permits
            WHERE UPPER(TRIM(address)) = ?
            ORDER BY filed_date DESC
            LIMIT ?
            """,
            (clean, limit),
        )

        if not rows:
            # Extract street number + street name for fuzzy match
            parts = clean.split()
            if len(parts) >= 2:
                street_prefix = f"{parts[0]} {parts[1]}%"
                rows = self.fetchall(
                    """
                    SELECT record_number, permit_type, status, address, zip_code,
                           description, job_value, construction_type, filed_date, detail_url
                    FROM building_permits
                    WHERE UPPER(TRIM(address)) LIKE ?
                    ORDER BY filed_date DESC
                    LIMIT ?
                    """,
                    (street_prefix, limit),
                )

        return rows

    # ------------------------------------------------------------------
    # Properties (Berkeley Parcels)
    # ------------------------------------------------------------------

    def upsert_properties_batch(self, parcels: list[BerkeleyParcel]) -> tuple[int, int]:
        """Insert or update a batch of parcels. Returns (inserted_count, updated_count)."""
        inserted = 0
        updated = 0
        sql = """
            INSERT INTO properties (
                apn, address, street_number, street_name, zip_code,
                latitude, longitude, lot_size_sqft, building_sqft,
                use_code, use_description, neighborhood, zoning_class,
                situs_unit, property_category, ownership_type, record_type,
                lot_group_key, parcel_lot_size_sqft
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(apn) DO UPDATE SET
                address = excluded.address,
                street_number = excluded.street_number,
                street_name = excluded.street_name,
                zip_code = excluded.zip_code,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                lot_size_sqft = excluded.lot_size_sqft,
                building_sqft = excluded.building_sqft,
                use_code = excluded.use_code,
                use_description = excluded.use_description,
                situs_unit = excluded.situs_unit,
                property_category = excluded.property_category,
                ownership_type = excluded.ownership_type,
                record_type = excluded.record_type,
                lot_group_key = excluded.lot_group_key,
                parcel_lot_size_sqft = excluded.parcel_lot_size_sqft,
                updated_at = datetime('now')
        """
        adapted = _adapt_sql(sql, self.backend)
        with self.conn:
            for p in parcels:
                params = (
                    p.apn,
                    p.address,
                    p.street_number,
                    p.street_name,
                    p.zip_code,
                    p.latitude,
                    p.longitude,
                    p.lot_size_sqft,
                    p.building_sqft,
                    p.use_code,
                    p.use_description,
                    p.neighborhood,
                    p.zoning_class,
                    p.situs_unit,
                    p.property_category,
                    p.ownership_type,
                    p.record_type,
                    p.lot_group_key,
                    p.parcel_lot_size_sqft,
                )
                if self.is_postgres:
                    cur = self.conn.cursor()
                    cur.execute(adapted, params)
                    if cur.rowcount > 0:
                        inserted += 1
                else:
                    cursor = self.conn.execute(adapted, params)
                    # rowcount=1 for both INSERT and UPDATE in SQLite
                    if cursor.rowcount > 0:
                        if cursor.lastrowid and cursor.lastrowid > 0:
                            inserted += 1
                        else:
                            updated += 1
        return inserted, updated

    def get_properties_missing_zoning(self) -> list[dict]:
        """Get all properties where zoning_class is NULL, with lat/long."""
        return self.fetchall(
            "SELECT id, latitude, longitude FROM properties "
            "WHERE zoning_class IS NULL AND latitude IS NOT NULL AND longitude IS NOT NULL"
        )

    def get_properties_missing_neighborhood(self) -> list[dict]:
        """Get all properties where neighborhood is NULL, with lat/long."""
        return self.fetchall(
            "SELECT id, latitude, longitude FROM properties "
            "WHERE neighborhood IS NULL AND latitude IS NOT NULL AND longitude IS NOT NULL"
        )

    def get_properties_missing_enrichment(self, limit: int | None = None) -> list[dict]:
        """Get properties not yet enriched via external API."""
        sql = (
            "SELECT id, apn, address, street_number, street_name, zip_code, "
            "latitude, longitude FROM properties WHERE rentcast_enriched = 0"
        )
        if limit:
            sql += f" LIMIT {limit}"
        return self.fetchall(sql)

    def update_properties_zoning_batch(self, updates: list[tuple[str, int]]) -> int:
        """Batch update zoning_class on properties. Each tuple is (zoning_class, property_id)."""
        sql = "UPDATE properties SET zoning_class = ?, updated_at = datetime('now') WHERE id = ?"
        with self.conn:
            self.executemany(sql, updates)
        return len(updates)

    def update_properties_neighborhood_batch(self, updates: list[tuple[str, int]]) -> int:
        """Batch update neighborhood on properties. Each tuple is (neighborhood, property_id)."""
        sql = "UPDATE properties SET neighborhood = ?, updated_at = datetime('now') WHERE id = ?"
        with self.conn:
            self.executemany(sql, updates)
        return len(updates)

    # ------------------------------------------------------------------
    # property_sales spatial enrichment
    # ------------------------------------------------------------------

    def get_sales_missing_neighborhood(self) -> list[dict]:
        """Get property_sales rows missing neighborhood that have lat/long."""
        return self.fetchall(
            "SELECT id, latitude, longitude FROM property_sales "
            "WHERE neighborhood IS NULL AND latitude IS NOT NULL AND longitude IS NOT NULL"
        )

    def get_sales_missing_zoning(self) -> list[dict]:
        """Get property_sales rows missing zoning_class that have lat/long."""
        return self.fetchall(
            "SELECT id, latitude, longitude FROM property_sales "
            "WHERE zoning_class IS NULL AND latitude IS NOT NULL AND longitude IS NOT NULL"
        )

    def update_sales_neighborhood_batch(self, updates: list[tuple[str, int]]) -> int:
        """Batch update neighborhood on property_sales."""
        with self.conn:
            self.executemany(
                "UPDATE property_sales SET neighborhood = ? WHERE id = ?",
                updates,
            )
        return len(updates)

    def update_sales_zoning_batch(self, updates: list[tuple[str, int]]) -> int:
        """Batch update zoning_class on property_sales."""
        with self.conn:
            self.executemany(
                "UPDATE property_sales SET zoning_class = ? WHERE id = ?",
                updates,
            )
        return len(updates)

    def update_properties_enrichment_batch(self, updates: list[dict]) -> int:
        """Batch update API-enriched fields on properties."""
        count = 0
        sql = """
            UPDATE properties SET
                beds = ?, baths = ?, sqft = ?, year_built = ?,
                property_type = ?, last_sale_date = ?, last_sale_price = ?,
                rentcast_enriched = 1, updated_at = datetime('now')
            WHERE id = ?
        """
        adapted = _adapt_sql(sql, self.backend)
        with self.conn:
            for u in updates:
                params = (
                    u.get("beds"),
                    u.get("baths"),
                    u.get("sqft"),
                    u.get("year_built"),
                    u.get("property_type"),
                    u.get("last_sale_date"),
                    u.get("last_sale_price"),
                    u["id"],
                )
                if self.is_postgres:
                    cur = self.conn.cursor()
                    cur.execute(adapted, params)
                else:
                    self.conn.execute(adapted, params)
                count += 1
        return count

    def get_properties_count(self) -> dict:
        """Return property statistics for the status command."""
        row = self.fetchone(
            "SELECT COUNT(*) AS total, "
            "COUNT(CASE WHEN neighborhood IS NOT NULL THEN 1 END) AS with_neighborhood, "
            "COUNT(CASE WHEN zoning_class IS NOT NULL THEN 1 END) AS with_zoning, "
            "COUNT(CASE WHEN rentcast_enriched = 1 THEN 1 END) AS enriched, "
            "COUNT(DISTINCT use_code) AS use_codes, "
            "COUNT(DISTINCT neighborhood) AS neighborhoods, "
            "COUNT(DISTINCT zip_code) AS zip_codes "
            "FROM properties"
        )
        if not row:
            return {"total": 0, "with_neighborhood": 0, "with_zoning": 0,
                    "enriched": 0, "use_codes": 0, "neighborhoods": 0, "zip_codes": 0}
        return {
            "total": row["total"],
            "with_neighborhood": row["with_neighborhood"],
            "with_zoning": row["with_zoning"],
            "enriched": row["enriched"],
            "use_codes": row["use_codes"],
            "neighborhoods": row["neighborhoods"],
            "zip_codes": row["zip_codes"],
        }

    # ------------------------------------------------------------------
    # API Response Cache
    # ------------------------------------------------------------------

    def cache_api_response(
        self,
        source: str,
        endpoint: str,
        cache_key: str,
        request_params: dict | None = None,
        response_json: str = "",
        http_status: int = 200,
    ) -> None:
        """Store a raw API response in the cache (upsert)."""
        params_json = json.dumps(request_params) if request_params else None
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if self.is_postgres:
            self.execute(
                """
                INSERT INTO api_response_cache
                    (source, endpoint, cache_key, request_params, response_json, http_status, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, endpoint, cache_key) DO UPDATE SET
                    request_params = EXCLUDED.request_params,
                    response_json  = EXCLUDED.response_json,
                    http_status    = EXCLUDED.http_status,
                    fetched_at     = EXCLUDED.fetched_at
                """,
                (source, endpoint, cache_key, params_json, response_json, http_status, now_utc),
            )
            self.commit()
        else:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO api_response_cache
                        (source, endpoint, cache_key, request_params, response_json, http_status, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(source, endpoint, cache_key) DO UPDATE SET
                        request_params = excluded.request_params,
                        response_json  = excluded.response_json,
                        http_status    = excluded.http_status,
                        fetched_at     = excluded.fetched_at
                    """,
                    (source, endpoint, cache_key, params_json, response_json, http_status),
                )

    def get_cached_api_response(
        self,
        source: str,
        endpoint: str,
        cache_key: str,
        max_age_hours: int = 0,
    ) -> dict | None:
        """Retrieve a cached API response."""
        sql = (
            "SELECT response_json, http_status, fetched_at FROM api_response_cache "
            "WHERE source = ? AND endpoint = ? AND cache_key = ?"
        )
        params: list = [source, endpoint, cache_key]
        if max_age_hours > 0:
            # Use Python-computed cutoff (works for both backends)
            cutoff = self._now_cutoff(max_age_hours)
            sql += " AND fetched_at > ?"
            params.append(cutoff)

        row = self.fetchone(sql, params)
        if not row:
            return None
        try:
            parsed = json.loads(row["response_json"])
        except (json.JSONDecodeError, TypeError):
            parsed = row["response_json"]
        return {
            "response": parsed,
            "http_status": row["http_status"],
            "fetched_at": row["fetched_at"],
        }

    def get_cached_api_responses_by_source(
        self,
        source: str,
        endpoint: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """List cached responses for a source (for debugging/export)."""
        sql = "SELECT cache_key, http_status, fetched_at FROM api_response_cache WHERE source = ?"
        params: list = [source]
        if endpoint:
            sql += " AND endpoint = ?"
            params.append(endpoint)
        sql += " ORDER BY fetched_at DESC LIMIT ?"
        params.append(limit)
        return self.fetchall(sql, params)

    # ------------------------------------------------------------------
    # Pre-computed scenarios
    # ------------------------------------------------------------------

    def upsert_precomputed_scenario(
        self,
        property_id: int,
        scenario_type: str,
        prediction_json: str,
        rental_json: str | None = None,
        potential_json: str | None = None,
        comparables_json: str | None = None,
        model_version: str | None = None,
    ) -> None:
        """Insert or replace a pre-computed scenario for a property."""
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if self.is_postgres:
            self.execute(
                """
                INSERT INTO precomputed_scenarios (
                    property_id, scenario_type, prediction_json,
                    rental_json, potential_json, comparables_json,
                    model_version, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (property_id, scenario_type) DO UPDATE SET
                    prediction_json = EXCLUDED.prediction_json,
                    rental_json = EXCLUDED.rental_json,
                    potential_json = EXCLUDED.potential_json,
                    comparables_json = EXCLUDED.comparables_json,
                    model_version = EXCLUDED.model_version,
                    computed_at = EXCLUDED.computed_at
                """,
                (
                    property_id, scenario_type, prediction_json,
                    rental_json, potential_json, comparables_json,
                    model_version, now_utc,
                ),
            )
            self.commit()
        else:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO precomputed_scenarios (
                    property_id, scenario_type, prediction_json,
                    rental_json, potential_json, comparables_json,
                    model_version, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    property_id, scenario_type, prediction_json,
                    rental_json, potential_json, comparables_json,
                    model_version,
                ),
            )
            self.conn.commit()

    def get_precomputed_scenario(
        self,
        property_id: int,
        scenario_type: str = "buyer",
    ) -> Optional[dict]:
        """Look up a pre-computed scenario by property ID."""
        return self.fetchone(
            "SELECT * FROM precomputed_scenarios WHERE property_id = ? AND scenario_type = ?",
            (property_id, scenario_type),
        )

    def get_precomputed_by_location(
        self,
        lat: float,
        lon: float,
        scenario_type: str = "buyer",
        max_distance_m: float = 5.0,
    ) -> Optional[dict]:
        """Find the nearest pre-computed scenario within *max_distance_m*."""
        delta = max_distance_m / 111_139.0
        rows = self.fetchall(
            """
            SELECT ps.*, p.*
            FROM precomputed_scenarios ps
            JOIN properties p ON p.id = ps.property_id
            WHERE ps.scenario_type = ?
              AND p.latitude BETWEEN ? AND ?
              AND p.longitude BETWEEN ? AND ?
            """,
            (scenario_type, lat - delta, lat + delta, lon - delta, lon + delta),
        )

        if not rows:
            return None

        best: Optional[dict] = None
        best_dist = float("inf")
        for d in rows:
            dist = _haversine(lat, lon, d["latitude"], d["longitude"])
            if dist < best_dist and dist <= max_distance_m:
                best_dist = dist
                scenario_keys = {
                    "property_id", "scenario_type", "prediction_json",
                    "rental_json", "potential_json", "comparables_json",
                    "computed_at", "model_version",
                }
                scenario = {k: d[k] for k in scenario_keys if k in d}
                prop = {}
                for k, v in d.items():
                    if k not in scenario_keys and k != "id":
                        prop[k] = v
                if "id" not in prop:
                    prop["id"] = d.get("property_id")
                scenario["property"] = prop
                best = scenario

        return best

    # ------------------------------------------------------------------
    # Property Search
    # ------------------------------------------------------------------

    def search_properties(self, query: str, limit: int = 5) -> list[dict]:
        """Search properties by address (fuzzy text match)."""
        normalized = query.strip().upper()
        if not normalized:
            return []

        # Try exact prefix match first
        rows = self.fetchall(
            "SELECT * FROM properties WHERE UPPER(address) LIKE ? ORDER BY address LIMIT ?",
            (f"{normalized}%", limit),
        )

        if not rows:
            rows = self.fetchall(
                "SELECT * FROM properties WHERE UPPER(address) LIKE ? ORDER BY address LIMIT ?",
                (f"%{normalized}%", limit),
            )

        return rows

    # -- Shared filter builder for advanced property queries ------------------

    @staticmethod
    def _build_property_filter_clause(
        *,
        neighborhoods: list[str] | None = None,
        zoning_classes: list[str] | None = None,
        zoning_pattern: str | None = None,
        property_type: str | None = None,
        property_category: str | None = None,
        record_type: str | None = None,
        ownership_type: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        min_beds: float | None = None,
        max_beds: float | None = None,
        min_baths: float | None = None,
        max_baths: float | None = None,
        min_lot_sqft: int | None = None,
        max_lot_sqft: int | None = None,
        min_sqft: int | None = None,
        max_sqft: int | None = None,
        min_year_built: int | None = None,
        max_year_built: int | None = None,
    ) -> tuple[str, list]:
        """Build a WHERE clause + params list from property search filters."""
        clauses: list[str] = []
        params: list = []

        if neighborhoods:
            placeholders = ",".join("?" for _ in neighborhoods)
            clauses.append(f"p.neighborhood IN ({placeholders})")
            params.extend(neighborhoods)
        if zoning_classes:
            placeholders = ",".join("?" for _ in zoning_classes)
            clauses.append(f"p.zoning_class IN ({placeholders})")
            params.extend(zoning_classes)
        if zoning_pattern:
            clauses.append("p.zoning_class LIKE ?")
            params.append(zoning_pattern)
        if property_type:
            clauses.append("p.property_type = ?")
            params.append(property_type)
        if property_category:
            clauses.append("p.property_category = ?")
            params.append(property_category)
        if record_type:
            clauses.append("p.record_type = ?")
            params.append(record_type)
        if ownership_type:
            clauses.append("p.ownership_type = ?")
            params.append(ownership_type)
        if min_price is not None:
            clauses.append("p.last_sale_price >= ?")
            params.append(min_price)
        if max_price is not None:
            clauses.append("p.last_sale_price <= ?")
            params.append(max_price)
        if min_beds is not None:
            clauses.append("p.beds >= ?")
            params.append(min_beds)
        if max_beds is not None:
            clauses.append("p.beds <= ?")
            params.append(max_beds)
        if min_baths is not None:
            clauses.append("p.baths >= ?")
            params.append(min_baths)
        if max_baths is not None:
            clauses.append("p.baths <= ?")
            params.append(max_baths)
        if min_lot_sqft is not None:
            clauses.append("p.lot_size_sqft >= ?")
            params.append(min_lot_sqft)
        if max_lot_sqft is not None:
            clauses.append("p.lot_size_sqft <= ?")
            params.append(max_lot_sqft)
        if min_sqft is not None:
            clauses.append("p.sqft >= ?")
            params.append(min_sqft)
        if max_sqft is not None:
            clauses.append("p.sqft <= ?")
            params.append(max_sqft)
        if min_year_built is not None:
            clauses.append("p.year_built >= ?")
            params.append(min_year_built)
        if max_year_built is not None:
            clauses.append("p.year_built <= ?")
            params.append(max_year_built)

        where = (" AND ".join(clauses)) if clauses else "1=1"
        return where, params

    def search_properties_advanced(
        self,
        *,
        neighborhoods: list[str] | None = None,
        zoning_classes: list[str] | None = None,
        zoning_pattern: str | None = None,
        property_type: str | None = None,
        property_category: str | None = None,
        record_type: str | None = None,
        ownership_type: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        min_beds: float | None = None,
        max_beds: float | None = None,
        min_baths: float | None = None,
        max_baths: float | None = None,
        min_lot_sqft: int | None = None,
        max_lot_sqft: int | None = None,
        min_sqft: int | None = None,
        max_sqft: int | None = None,
        min_year_built: int | None = None,
        max_year_built: int | None = None,
        limit: int = 25,
    ) -> list[dict]:
        """Search properties by multiple criteria with precomputed data."""
        where, params = self._build_property_filter_clause(
            neighborhoods=neighborhoods, zoning_classes=zoning_classes,
            zoning_pattern=zoning_pattern, property_type=property_type,
            property_category=property_category, record_type=record_type,
            ownership_type=ownership_type, min_price=min_price,
            max_price=max_price, min_beds=min_beds, max_beds=max_beds,
            min_baths=min_baths, max_baths=max_baths,
            min_lot_sqft=min_lot_sqft, max_lot_sqft=max_lot_sqft,
            min_sqft=min_sqft, max_sqft=max_sqft,
            min_year_built=min_year_built, max_year_built=max_year_built,
        )
        params.append(min(limit, 100))

        sql = f"""
            SELECT p.*,
                   ps.prediction_json,
                   ps.potential_json
            FROM properties p
            LEFT JOIN precomputed_scenarios ps
                ON ps.property_id = p.id AND ps.scenario_type = 'buyer'
            WHERE {where}
            ORDER BY p.last_sale_price DESC NULLS LAST
            LIMIT ?
        """
        return self.fetchall(sql, params)

    def count_properties_advanced(
        self,
        *,
        neighborhoods: list[str] | None = None,
        zoning_classes: list[str] | None = None,
        zoning_pattern: str | None = None,
        property_type: str | None = None,
        property_category: str | None = None,
        record_type: str | None = None,
        ownership_type: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        min_beds: float | None = None,
        max_beds: float | None = None,
        min_baths: float | None = None,
        max_baths: float | None = None,
        min_lot_sqft: int | None = None,
        max_lot_sqft: int | None = None,
        min_sqft: int | None = None,
        max_sqft: int | None = None,
        min_year_built: int | None = None,
        max_year_built: int | None = None,
    ) -> int:
        """Count properties matching criteria."""
        where, params = self._build_property_filter_clause(
            neighborhoods=neighborhoods, zoning_classes=zoning_classes,
            zoning_pattern=zoning_pattern, property_type=property_type,
            property_category=property_category, record_type=record_type,
            ownership_type=ownership_type, min_price=min_price,
            max_price=max_price, min_beds=min_beds, max_beds=max_beds,
            min_baths=min_baths, max_baths=max_baths,
            min_lot_sqft=min_lot_sqft, max_lot_sqft=max_lot_sqft,
            min_sqft=min_sqft, max_sqft=max_sqft,
            min_year_built=min_year_built, max_year_built=max_year_built,
        )
        sql = f"SELECT COUNT(*) FROM properties p WHERE {where}"
        val = self.fetchval(sql, params)
        return val if val else 0

    def search_properties_lightweight(
        self,
        *,
        neighborhoods: list[str] | None = None,
        zoning_classes: list[str] | None = None,
        zoning_pattern: str | None = None,
        property_type: str | None = None,
        property_category: str | None = None,
        record_type: str | None = None,
        ownership_type: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        min_beds: float | None = None,
        max_beds: float | None = None,
        min_baths: float | None = None,
        max_baths: float | None = None,
        min_lot_sqft: int | None = None,
        max_lot_sqft: int | None = None,
        min_sqft: int | None = None,
        max_sqft: int | None = None,
        min_year_built: int | None = None,
        max_year_built: int | None = None,
        max_results: int = 5000,
    ) -> list[dict]:
        """Return lightweight property records for ALL matches (working set)."""
        where, params = self._build_property_filter_clause(
            neighborhoods=neighborhoods, zoning_classes=zoning_classes,
            zoning_pattern=zoning_pattern, property_type=property_type,
            property_category=property_category, record_type=record_type,
            ownership_type=ownership_type, min_price=min_price,
            max_price=max_price, min_beds=min_beds, max_beds=max_beds,
            min_baths=min_baths, max_baths=max_baths,
            min_lot_sqft=min_lot_sqft, max_lot_sqft=max_lot_sqft,
            min_sqft=min_sqft, max_sqft=max_sqft,
            min_year_built=min_year_built, max_year_built=max_year_built,
        )
        params.append(min(max_results, 5000))

        sql = f"""
            SELECT p.id, p.address, p.neighborhood, p.beds, p.baths,
                   p.sqft, p.building_sqft, p.lot_size_sqft, p.zoning_class,
                   p.property_type, p.last_sale_price, p.year_built,
                   p.latitude, p.longitude, p.property_category,
                   p.record_type, p.lot_group_key, p.situs_unit
            FROM properties p
            WHERE {where}
            ORDER BY p.last_sale_price DESC NULLS LAST
            LIMIT ?
        """
        return self.fetchall(sql, params)

    def get_property_by_id(self, property_id: int) -> dict | None:
        """Get a single property by its database ID."""
        return self.fetchone(
            "SELECT * FROM properties WHERE id = ?",
            (property_id,),
        )

    # ------------------------------------------------------------------
    # Predictions cache
    # ------------------------------------------------------------------

    def get_cached_prediction(
        self,
        latitude: float,
        longitude: float,
        beds: float | None = None,
        baths: float | None = None,
        sqft: int | None = None,
        year_built: int | None = None,
        lot_size_sqft: int | None = None,
        property_type: str | None = None,
        max_age_hours: int = 168,  # 7 days default
    ) -> dict | None:
        """Look up a cached prediction for the given property parameters."""
        lat_tol = 0.0001
        lon_tol = 0.0001

        # Use Python-computed cutoff instead of SQLite datetime() modifier
        cutoff = self._now_cutoff(max_age_hours)
        conditions = [
            "ABS(latitude - ?) < ?",
            "ABS(longitude - ?) < ?",
            "created_at > ?",
        ]
        params: list = [latitude, lat_tol, longitude, lon_tol, cutoff]

        for col, val in [
            ("beds", beds),
            ("baths", baths),
            ("sqft", sqft),
            ("year_built", year_built),
            ("lot_size_sqft", lot_size_sqft),
            ("property_type", property_type),
        ]:
            if val is not None:
                conditions.append(f"{col} = ?")
                params.append(val)
            else:
                conditions.append(f"{col} IS NULL")

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT * FROM predictions
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT 1
        """
        result = self.fetchone(sql, params)
        if not result:
            return None

        # Deserialize feature_contributions from JSON
        if result.get("feature_contributions"):
            try:
                result["feature_contributions"] = json.loads(result["feature_contributions"])
            except (json.JSONDecodeError, TypeError):
                result["feature_contributions"] = None
        return result

    def store_prediction(
        self,
        latitude: float,
        longitude: float,
        predicted_price: int,
        price_lower: int,
        price_upper: int,
        neighborhood: str | None = None,
        zip_code: str | None = None,
        beds: float | None = None,
        baths: float | None = None,
        sqft: int | None = None,
        year_built: int | None = None,
        lot_size_sqft: int | None = None,
        property_type: str | None = None,
        list_price: int | None = None,
        hoa_per_month: int | None = None,
        base_value: int | None = None,
        predicted_premium_pct: float | None = None,
        feature_contributions: list[dict] | None = None,
        source: str = "chat",
    ) -> int:
        """Store a prediction result in the cache."""
        fc_json = json.dumps(feature_contributions) if feature_contributions else None

        sql = """
            INSERT INTO predictions (
                latitude, longitude, neighborhood, zip_code,
                beds, baths, sqft, year_built, lot_size_sqft,
                property_type, list_price, hoa_per_month,
                predicted_price, price_lower, price_upper,
                base_value, predicted_premium_pct, feature_contributions,
                source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            latitude, longitude, neighborhood, zip_code,
            beds, baths, sqft, year_built, lot_size_sqft,
            property_type, list_price, hoa_per_month,
            predicted_price, price_lower, price_upper,
            base_value, predicted_premium_pct, fc_json,
            source,
        )
        row_id = self._insert_returning_id(sql, params)
        self.commit()
        logger.info(
            "Stored prediction #%d: $%s for (%s, %s) via %s",
            row_id, f"{predicted_price:,}", latitude, longitude, source,
        )
        return row_id

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
        self.execute(sql, (name, aliases_json, geometry_wkt, centroid_lat, centroid_lon, area_sqmi))
        self.commit()

    # ------------------------------------------------------------------
    # Collection Runs (audit trail)
    # ------------------------------------------------------------------

    def start_collection_run(self, source: str, parameters: dict | None = None) -> int:
        """Record the start of a collection run. Returns the run ID."""
        params_json = json.dumps(parameters) if parameters else None
        sql = "INSERT INTO collection_runs (source, started_at, parameters) VALUES (?, ?, ?)"
        params = (source, datetime.now().isoformat(), params_json)
        row_id = self._insert_returning_id(sql, params)
        self.commit()
        return row_id

    def complete_collection_run(self, run_id: int, result: CollectionResult) -> None:
        """Record the completion of a collection run."""
        error_msg = "; ".join(result.errors) if result.errors else None
        status = "success" if result.success else "failed"
        self.execute(
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
        self.commit()

    # ------------------------------------------------------------------
    # Statistics / Status
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def create_user(
        self,
        email: str,
        password_hash: str | None = None,
        full_name: str | None = None,
    ) -> dict:
        """Create a new user and return the user row (without password_hash).

        password_hash may be None for OAuth-only users who don't set a password.
        """
        user_id = self._insert_returning_id(
            "INSERT INTO users (email, password_hash, full_name) VALUES (?, ?, ?)",
            (email, password_hash, full_name),
        )
        self.commit()
        return {"id": user_id, "email": email, "full_name": full_name, "is_active": 1}

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Fetch a user by email address, or None if not found."""
        return self.fetchone(
            "SELECT id, email, password_hash, full_name, is_active, created_at "
            "FROM users WHERE email = ?",
            (email,),
        )

    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        """Fetch a user by ID (without password_hash), or None if not found."""
        return self.fetchone(
            "SELECT id, email, full_name, is_active, created_at "
            "FROM users WHERE id = ?",
            (user_id,),
        )

    def get_user_with_password_by_id(self, user_id: int) -> Optional[dict]:
        """Fetch a user by ID including password_hash, or None if not found."""
        return self.fetchone(
            "SELECT id, email, password_hash, full_name, is_active, created_at "
            "FROM users WHERE id = ?",
            (user_id,),
        )

    # ------------------------------------------------------------------
    # Terms of Service acceptance
    # ------------------------------------------------------------------

    def create_tos_acceptance(
        self, user_id: int, tos_version: str, ip_address: str | None = None
    ) -> dict:
        """Record that a user accepted a specific version of the Terms."""
        row_id = self._insert_returning_id(
            "INSERT INTO tos_acceptances (user_id, tos_version, ip_address) VALUES (?, ?, ?)",
            (user_id, tos_version, ip_address),
        )
        self.commit()
        return {"id": row_id, "user_id": user_id, "tos_version": tos_version}

    def get_latest_tos_acceptance(self, user_id: int) -> Optional[dict]:
        """Return the most recent TOS acceptance for a user, or None."""
        return self.fetchone(
            "SELECT id, user_id, tos_version, ip_address, accepted_at "
            "FROM tos_acceptances WHERE user_id = ? ORDER BY accepted_at DESC LIMIT 1",
            (user_id,),
        )

    # ------------------------------------------------------------------
    # Refresh tokens
    # ------------------------------------------------------------------

    def create_refresh_token(
        self, user_id: int, token_hash: str, expires_at: str
    ) -> int:
        """Store a hashed refresh token. Returns the row id."""
        row_id = self._insert_returning_id(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, token_hash, expires_at),
        )
        self.commit()
        return row_id

    def get_refresh_token_by_hash(self, token_hash: str) -> Optional[dict]:
        """Look up a refresh token by its hash."""
        return self.fetchone(
            "SELECT id, user_id, token_hash, expires_at, revoked, created_at "
            "FROM refresh_tokens WHERE token_hash = ?",
            (token_hash,),
        )

    def revoke_refresh_token(self, token_id: int) -> None:
        """Mark a single refresh token as revoked."""
        self.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE id = ?", (token_id,)
        )
        self.commit()

    def revoke_all_user_refresh_tokens(self, user_id: int) -> None:
        """Revoke all refresh tokens for a user (e.g. on password change or logout-all)."""
        self.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        )
        self.commit()

    def update_user_password(self, user_id: int, password_hash: str) -> None:
        """Update a user's password hash."""
        self.execute(
            "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
            (password_hash, user_id),
        )
        self.commit()

    def deactivate_user(self, user_id: int) -> None:
        """Set is_active = 0 for a user."""
        self.execute(
            "UPDATE users SET is_active = 0, updated_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
        self.commit()

    def delete_user_cascade(self, user_id: int) -> None:
        """Permanently delete a user and all associated data."""
        self.execute("DELETE FROM conversation_messages WHERE conversation_id IN "
                     "(SELECT id FROM conversations WHERE user_id = ?)", (user_id,))
        self.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        self.execute("DELETE FROM tos_acceptances WHERE user_id = ?", (user_id,))
        self.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (user_id,))
        self.execute("DELETE FROM auth_activity_log WHERE user_id = ?", (user_id,))
        self.execute("DELETE FROM email_verification_tokens WHERE user_id = ?", (user_id,))
        self.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        self.execute("DELETE FROM oauth_accounts WHERE user_id = ?", (user_id,))
        self.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.commit()

    # ------------------------------------------------------------------
    # OAuth accounts
    # ------------------------------------------------------------------

    def create_oauth_account(
        self,
        user_id: int,
        provider: str,
        provider_user_id: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> int:
        """Link an OAuth provider account to a local user. Returns the row id."""
        row_id = self._insert_returning_id(
            "INSERT INTO oauth_accounts "
            "(user_id, provider, provider_user_id, email, display_name) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, provider, provider_user_id, email, display_name),
        )
        self.commit()
        return row_id

    def get_oauth_account(
        self, provider: str, provider_user_id: str
    ) -> Optional[dict]:
        """Look up an OAuth account by provider + provider_user_id."""
        return self.fetchone(
            "SELECT id, user_id, provider, provider_user_id, email, display_name, created_at "
            "FROM oauth_accounts WHERE provider = ? AND provider_user_id = ?",
            (provider, provider_user_id),
        )

    def get_user_oauth_accounts(self, user_id: int) -> list[dict]:
        """Return all linked OAuth accounts for a user."""
        return self.fetchall(
            "SELECT id, provider, provider_user_id, email, display_name, created_at "
            "FROM oauth_accounts WHERE user_id = ?",
            (user_id,),
        )

    def delete_oauth_account(self, user_id: int, provider: str) -> bool:
        """Unlink an OAuth provider from a user. Returns True if a row was deleted."""
        cursor = self.execute(
            "DELETE FROM oauth_accounts WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        )
        self.commit()
        return cursor.rowcount > 0

    def user_has_password(self, user_id: int) -> bool:
        """Check whether a user has a password set (vs OAuth-only)."""
        row = self.fetchone(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        )
        return row is not None and row.get("password_hash") is not None

    # ------------------------------------------------------------------
    # Active sessions (for session management UI)
    # ------------------------------------------------------------------

    def get_active_sessions(self, user_id: int) -> list[dict]:
        """Return non-revoked, non-expired refresh tokens for a user (active sessions)."""
        return self.fetchall(
            "SELECT rt.id, rt.created_at, "
            "  (SELECT aal.ip_address FROM auth_activity_log aal "
            "   WHERE aal.user_id = rt.user_id AND aal.event_type = 'login_success' "
            "   ORDER BY aal.created_at DESC LIMIT 1) AS ip_address, "
            "  (SELECT aal.user_agent FROM auth_activity_log aal "
            "   WHERE aal.user_id = rt.user_id AND aal.event_type = 'login_success' "
            "   ORDER BY aal.created_at DESC LIMIT 1) AS user_agent "
            "FROM refresh_tokens rt "
            "WHERE rt.user_id = ? AND rt.revoked = 0 AND rt.expires_at > datetime('now') "
            "ORDER BY rt.created_at DESC",
            (user_id,),
        )

    def revoke_other_sessions(self, user_id: int, keep_token_id: int) -> int:
        """Revoke all refresh tokens for a user EXCEPT the specified one. Returns count revoked."""
        cursor = self.execute(
            "UPDATE refresh_tokens SET revoked = 1 "
            "WHERE user_id = ? AND id != ? AND revoked = 0",
            (user_id, keep_token_id),
        )
        self.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Auth activity logging
    # ------------------------------------------------------------------

    def log_auth_event(
        self,
        event_type: str,
        user_id: int | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
        detail: str | None = None,
    ) -> int:
        """Record an authentication event. Returns the row id."""
        row_id = self._insert_returning_id(
            "INSERT INTO auth_activity_log "
            "(user_id, event_type, ip_address, user_agent, success, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, event_type, ip_address, user_agent, 1 if success else 0, detail),
        )
        self.commit()
        return row_id

    def get_auth_activity(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        """Return recent auth activity for a user, most recent first."""
        return self.fetchall(
            "SELECT id, event_type, ip_address, user_agent, success, detail, created_at "
            "FROM auth_activity_log WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )

    # ------------------------------------------------------------------
    # Email verification tokens
    # ------------------------------------------------------------------

    def create_email_verification_token(
        self, user_id: int, token_hash: str, expires_at: str
    ) -> int:
        """Store a hashed email verification token. Returns the row id."""
        # Invalidate any existing unused tokens for this user
        self.execute(
            "UPDATE email_verification_tokens SET used = 1 "
            "WHERE user_id = ? AND used = 0",
            (user_id,),
        )
        row_id = self._insert_returning_id(
            "INSERT INTO email_verification_tokens (user_id, token_hash, expires_at) "
            "VALUES (?, ?, ?)",
            (user_id, token_hash, expires_at),
        )
        self.commit()
        return row_id

    def get_email_verification_token_by_hash(self, token_hash: str) -> Optional[dict]:
        """Look up an email verification token by its hash."""
        return self.fetchone(
            "SELECT id, user_id, token_hash, expires_at, used, created_at "
            "FROM email_verification_tokens WHERE token_hash = ?",
            (token_hash,),
        )

    def mark_email_verification_used(self, token_id: int) -> None:
        """Mark an email verification token as used."""
        self.execute(
            "UPDATE email_verification_tokens SET used = 1 WHERE id = ?",
            (token_id,),
        )
        self.commit()

    def activate_user(self, user_id: int) -> None:
        """Set is_active = 1 for a user (used after email verification)."""
        self.execute(
            "UPDATE users SET is_active = 1, updated_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
        self.commit()

    # ------------------------------------------------------------------
    # Password reset tokens
    # ------------------------------------------------------------------

    def create_password_reset_token(
        self, user_id: int, token_hash: str, expires_at: str
    ) -> int:
        """Store a hashed password reset token. Invalidates existing tokens for the user."""
        self.execute(
            "UPDATE password_reset_tokens SET used = 1 "
            "WHERE user_id = ? AND used = 0",
            (user_id,),
        )
        row_id = self._insert_returning_id(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
            "VALUES (?, ?, ?)",
            (user_id, token_hash, expires_at),
        )
        self.commit()
        return row_id

    def get_password_reset_token_by_hash(self, token_hash: str) -> Optional[dict]:
        """Look up a password reset token by its hash."""
        return self.fetchone(
            "SELECT id, user_id, token_hash, expires_at, used, created_at "
            "FROM password_reset_tokens WHERE token_hash = ?",
            (token_hash,),
        )

    def mark_password_reset_used(self, token_id: int) -> None:
        """Mark a password reset token as used."""
        self.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE id = ?",
            (token_id,),
        )
        self.commit()

    # ------------------------------------------------------------------
    # Conversation management
    # ------------------------------------------------------------------

    def create_conversation(
        self, user_id: int, session_id: str, title: str | None = None
    ) -> dict:
        """Create a new conversation and return the row."""
        conv_id = self._insert_returning_id(
            "INSERT INTO conversations (user_id, session_id, title) VALUES (?, ?, ?)",
            (user_id, session_id, title),
        )
        self.commit()
        return {
            "id": conv_id,
            "user_id": user_id,
            "session_id": session_id,
            "title": title,
        }

    def get_conversation(self, conversation_id: int, user_id: int) -> Optional[dict]:
        """Fetch a single conversation, enforcing user ownership."""
        return self.fetchone(
            "SELECT id, user_id, session_id, title, created_at, updated_at "
            "FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )

    def get_conversation_by_session(
        self, session_id: str, user_id: int
    ) -> Optional[dict]:
        """Fetch a conversation by session_id, enforcing user ownership."""
        return self.fetchone(
            "SELECT id, user_id, session_id, title, created_at, updated_at "
            "FROM conversations WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )

    def list_conversations(
        self, user_id: int, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """List conversations for a user, ordered by most recent first."""
        rows = self.fetchall(
            "SELECT c.id, c.session_id, c.title, c.created_at, c.updated_at, "
            "  (SELECT COUNT(*) FROM conversation_messages cm "
            "   WHERE cm.conversation_id = c.id) AS message_count "
            "FROM conversations c "
            "WHERE c.user_id = ? "
            "ORDER BY c.updated_at DESC "
            "LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )
        return rows

    def update_conversation_title(
        self, conversation_id: int, user_id: int, title: str
    ) -> bool:
        """Update a conversation's title. Returns True if the row was found."""
        self.execute(
            "UPDATE conversations SET title = ? WHERE id = ? AND user_id = ?",
            (title, conversation_id, user_id),
        )
        self.commit()
        return True

    def delete_conversation(self, conversation_id: int, user_id: int) -> bool:
        """Delete a conversation and its messages. Returns True if deleted."""
        # Delete messages first (SQLite doesn't always enforce ON DELETE CASCADE)
        self.execute(
            "DELETE FROM conversation_messages WHERE conversation_id = ? "
            "AND conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)",
            (conversation_id, user_id),
        )
        self.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        self.commit()
        return True

    def save_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        blocks_json: str | None = None,
        tools_used_json: str | None = None,
        tool_events_json: str | None = None,
        message_index: int = 0,
    ) -> int:
        """Insert a message into a conversation and return its ID."""
        msg_id = self._insert_returning_id(
            "INSERT INTO conversation_messages "
            "(conversation_id, role, content, blocks_json, tools_used_json, "
            "tool_events_json, message_index) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                blocks_json,
                tools_used_json,
                tool_events_json,
                message_index,
            ),
        )
        self.commit()
        return msg_id

    def get_messages(self, conversation_id: int, user_id: int) -> list[dict]:
        """Fetch all messages for a conversation, enforcing user ownership."""
        return self.fetchall(
            "SELECT cm.id, cm.role, cm.content, cm.blocks_json, "
            "cm.tools_used_json, cm.tool_events_json, cm.message_index, cm.created_at "
            "FROM conversation_messages cm "
            "JOIN conversations c ON cm.conversation_id = c.id "
            "WHERE cm.conversation_id = ? AND c.user_id = ? "
            "ORDER BY cm.message_index ASC",
            (conversation_id, user_id),
        )

    def touch_conversation(self, conversation_id: int) -> None:
        """Update the updated_at timestamp on a conversation."""
        self.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        self.commit()

    def get_statistics(self) -> dict:
        """Return row counts and date ranges for all tables."""
        stats: dict = {}

        # Property sales
        row = self.fetchone(
            "SELECT COUNT(*) AS cnt, MIN(sale_date) AS min_date, "
            "MAX(sale_date) AS max_date FROM property_sales"
        )
        if row:
            stats["property_sales"] = {
                "count": row["cnt"],
                "min_date": row["min_date"],
                "max_date": row["max_date"],
            }
        else:
            stats["property_sales"] = {"count": 0, "min_date": None, "max_date": None}

        # Neighborhood coverage
        total = stats["property_sales"]["count"]
        geocoded = self.fetchval(
            "SELECT COUNT(*) FROM property_sales WHERE neighborhood IS NOT NULL"
        ) or 0
        stats["neighborhood_coverage"] = {
            "geocoded": geocoded,
            "total": total,
            "pct": round(geocoded / total * 100, 1) if total > 0 else 0,
        }

        # Zoning coverage
        zoned = self.fetchval(
            "SELECT COUNT(*) FROM property_sales WHERE zoning_class IS NOT NULL"
        ) or 0
        stats["zoning_coverage"] = {
            "zoned": zoned,
            "total": total,
            "pct": round(zoned / total * 100, 1) if total > 0 else 0,
        }

        # Market metrics
        row = self.fetchone(
            "SELECT COUNT(*) AS cnt, MIN(period_begin) AS min_date, "
            "MAX(period_begin) AS max_date FROM market_metrics"
        )
        if row:
            stats["market_metrics"] = {"count": row["cnt"], "min_date": row["min_date"], "max_date": row["max_date"]}
        else:
            stats["market_metrics"] = {"count": 0}

        # Mortgage rates
        row = self.fetchone(
            "SELECT COUNT(*) AS cnt, MIN(observation_date) AS min_date, "
            "MAX(observation_date) AS max_date FROM mortgage_rates"
        )
        if row:
            stats["mortgage_rates"] = {"count": row["cnt"], "min_date": row["min_date"], "max_date": row["max_date"]}
        else:
            stats["mortgage_rates"] = {"count": 0}

        # Economic indicators
        row = self.fetchone(
            "SELECT COUNT(*) AS cnt, MIN(observation_date) AS min_date, "
            "MAX(observation_date) AS max_date FROM economic_indicators"
        )
        if row:
            stats["economic_indicators"] = {"count": row["cnt"], "min_date": row["min_date"], "max_date": row["max_date"]}
        else:
            stats["economic_indicators"] = {"count": 0}

        # Series breakdown
        series_rows = self.fetchall(
            "SELECT series_id, COUNT(*) as cnt FROM economic_indicators "
            "GROUP BY series_id ORDER BY series_id"
        )
        stats["economic_series"] = {r["series_id"]: r["cnt"] for r in series_rows}

        # Census income
        row = self.fetchone(
            "SELECT COUNT(*) AS cnt, COUNT(DISTINCT zip_code) AS zip_codes, "
            "MIN(acs_year) AS min_year, MAX(acs_year) AS max_year FROM census_income"
        )
        if row:
            stats["census_income"] = {
                "count": row["cnt"], "zip_codes": row["zip_codes"],
                "min_year": row["min_year"], "max_year": row["max_year"],
            }
        else:
            stats["census_income"] = {"count": 0}

        # BESO records
        if self.table_exists("beso_records"):
            row = self.fetchone(
                "SELECT COUNT(*) AS cnt, COUNT(DISTINCT UPPER(TRIM(building_address))) AS addrs, "
                "MIN(reporting_year) AS min_year, MAX(reporting_year) AS max_year FROM beso_records"
            )
            if row:
                stats["beso_records"] = {
                    "count": row["cnt"], "addresses": row["addrs"],
                    "min_year": row["min_year"], "max_year": row["max_year"],
                }
            else:
                stats["beso_records"] = {"count": 0, "addresses": 0}
        else:
            stats["beso_records"] = {"count": 0, "addresses": 0}

        # Building permits
        if self.table_exists("building_permits"):
            row = self.fetchone(
                "SELECT COUNT(*) AS cnt, COUNT(DISTINCT UPPER(TRIM(address))) AS addrs, "
                "MIN(filed_date) AS min_date, MAX(filed_date) AS max_date FROM building_permits"
            )
            if row:
                stats["building_permits"] = {
                    "count": row["cnt"], "addresses": row["addrs"],
                    "min_date": row["min_date"], "max_date": row["max_date"],
                }
            else:
                stats["building_permits"] = {"count": 0, "addresses": 0}
        else:
            stats["building_permits"] = {"count": 0, "addresses": 0}

        # Properties (parcels)
        if self.table_exists("properties"):
            stats["properties"] = self.get_properties_count()
        else:
            stats["properties"] = {"total": 0}

        # Neighborhoods
        nbhd_count = self.fetchval("SELECT COUNT(*) FROM neighborhoods")
        stats["neighborhoods"] = {"count": nbhd_count or 0}

        # Last collection run
        last_run = self.fetchone(
            "SELECT source, completed_at, status FROM collection_runs ORDER BY id DESC LIMIT 1"
        )
        if last_run:
            stats["last_run"] = {
                "source": last_run["source"],
                "completed_at": last_run["completed_at"],
                "status": last_run["status"],
            }

        return stats

    # ------------------------------------------------------------------
    # Processing helpers
    # ------------------------------------------------------------------

    def find_nearest_sale(
        self,
        lat: float,
        lon: float,
        max_distance_m: float = 50.0,
    ) -> Optional[dict]:
        """Find the nearest property sale within *max_distance_m* of (lat, lon)."""
        delta = max_distance_m / 111_139.0
        rows = self.fetchall(
            """
            SELECT * FROM property_sales
            WHERE latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
            ORDER BY sale_date DESC
            """,
            (lat - delta, lat + delta, lon - delta, lon + delta),
        )

        if not rows:
            return None

        best: Optional[dict] = None
        best_dist = float("inf")
        for d in rows:
            dist = _haversine(lat, lon, d["latitude"], d["longitude"])
            if dist < best_dist and dist <= max_distance_m:
                best = d
                best_dist = dist

        return best

    # ------------------------------------------------------------------
    # Processing helpers (additional)
    # ------------------------------------------------------------------

    def get_sales_missing_neighborhood(self) -> list[dict]:
        """Get all sales where neighborhood is NULL, with lat/long."""
        return self.fetchall(
            "SELECT id, latitude, longitude, neighborhood_raw FROM property_sales WHERE neighborhood IS NULL"
        )

    def update_neighborhood(self, sale_id: int, neighborhood: str) -> None:
        """Set the normalized neighborhood for a property sale."""
        self.execute(
            "UPDATE property_sales SET neighborhood = ? WHERE id = ?",
            (neighborhood, sale_id),
        )

    def update_neighborhoods_batch(self, updates: list[tuple[str, int]]) -> None:
        """Batch update neighborhoods. Each tuple is (neighborhood, sale_id)."""
        with self.conn:
            self.executemany(
                "UPDATE property_sales SET neighborhood = ? WHERE id = ?",
                updates,
            )

    def update_zoning_batch(self, updates: list[tuple[str, int]]) -> None:
        """Batch update zoning_class. Each tuple is (zoning_class, sale_id)."""
        with self.conn:
            self.executemany(
                "UPDATE property_sales SET zoning_class = ? WHERE id = ?",
                updates,
            )

    def get_unique_redfin_addresses(self) -> list[dict]:
        """Get unique addresses from property_sales with coordinates."""
        return self.fetchall(
            "SELECT DISTINCT address, city, state, zip_code, latitude, longitude "
            "FROM property_sales"
        )
