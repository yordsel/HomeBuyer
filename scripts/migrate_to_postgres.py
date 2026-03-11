#!/usr/bin/env python3
"""Migrate data from SQLite to PostgreSQL.

Usage:
    python scripts/migrate_to_postgres.py [--sqlite-path PATH] [--database-url URL]

By default:
    - SQLite path: data/berkeley_homebuyer.db (from config)
    - PostgreSQL URL: from DATABASE_URL environment variable
"""

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Tables in dependency order (referenced tables first)
TABLES_IN_ORDER = [
    "schema_version",
    "use_codes",
    "neighborhoods",
    "properties",
    "property_sales",
    "market_metrics",
    "mortgage_rates",
    "economic_indicators",
    "census_income",
    "building_permits",
    "beso_records",
    "collection_runs",
    "predictions",
    "api_response_cache",
    "precomputed_scenarios",
]

# Batch size for inserts
BATCH_SIZE = 500


def get_sqlite_tables(sqlite_conn: sqlite3.Connection) -> list[str]:
    """Get all user tables from SQLite."""
    cursor = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in cursor.fetchall()]


def get_table_columns(sqlite_conn: sqlite3.Connection, table: str) -> list[str]:
    """Get column names for a table."""
    cursor = sqlite_conn.execute(f"PRAGMA table_info({table})")  # noqa: S608
    return [row[1] for row in cursor.fetchall()]


def get_row_count(conn, table: str, is_postgres: bool = False) -> int:
    """Get row count for a table."""
    if is_postgres:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        return cursor.fetchone()[0]
    else:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    table: str,
    columns: list[str],
) -> int:
    """Migrate a single table from SQLite to PostgreSQL.

    Returns the number of rows migrated.
    """
    import psycopg2.extras

    # Read all rows from SQLite
    col_list = ", ".join(columns)
    cursor = sqlite_conn.execute(f"SELECT {col_list} FROM {table}")  # noqa: S608
    rows = cursor.fetchall()

    if not rows:
        logger.info("  %s: 0 rows (empty table)", table)
        return 0

    # Build INSERT statement with ON CONFLICT DO NOTHING to handle duplicates
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"  # noqa: S608

    pg_cursor = pg_conn.cursor()

    # Insert in batches
    total_inserted = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        # Convert sqlite3.Row tuples to plain tuples
        batch_values = [tuple(row) for row in batch]
        try:
            psycopg2.extras.execute_batch(pg_cursor, insert_sql, batch_values)
            pg_conn.commit()
            total_inserted += len(batch)
        except Exception as e:
            pg_conn.rollback()
            logger.error("  %s: batch %d failed: %s", table, i // BATCH_SIZE, e)
            # Try row-by-row for this batch
            for row_values in batch_values:
                try:
                    pg_cursor.execute(insert_sql, row_values)
                    pg_conn.commit()
                    total_inserted += 1
                except Exception as row_err:
                    pg_conn.rollback()
                    logger.debug("  %s: row insert failed: %s", table, row_err)

    logger.info("  %s: %d/%d rows migrated", table, total_inserted, len(rows))
    return total_inserted


def reset_sequences(pg_conn, table: str, columns: list[str]) -> None:
    """Reset PostgreSQL sequences to match max ID values."""
    if "id" not in columns:
        return

    pg_cursor = pg_conn.cursor()
    try:
        # Find the sequence name
        pg_cursor.execute(
            "SELECT pg_get_serial_sequence(%s, 'id')",
            (table,),
        )
        seq_row = pg_cursor.fetchone()
        if seq_row and seq_row[0]:
            seq_name = seq_row[0]
            pg_cursor.execute(f"SELECT MAX(id) FROM {table}")  # noqa: S608
            max_id = pg_cursor.fetchone()[0]
            if max_id:
                pg_cursor.execute(f"SELECT setval('{seq_name}', %s)", (max_id,))
                pg_conn.commit()
                logger.info("  %s: sequence reset to %d", table, max_id)
    except Exception as e:
        pg_conn.rollback()
        logger.warning("  %s: could not reset sequence: %s", table, e)


def main():
    parser = argparse.ArgumentParser(description="Migrate HomeBuyer data from SQLite to PostgreSQL")
    parser.add_argument(
        "--sqlite-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: data/berkeley_homebuyer.db)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="PostgreSQL connection URL (default: DATABASE_URL env var)",
    )
    parser.add_argument(
        "--skip-tables",
        type=str,
        nargs="*",
        default=[],
        help="Tables to skip (e.g., --skip-tables precomputed_scenarios api_response_cache)",
    )
    parser.add_argument(
        "--only-tables",
        type=str,
        nargs="*",
        default=None,
        help="Only migrate these tables",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without actually doing it",
    )
    args = parser.parse_args()

    # Resolve SQLite path
    if args.sqlite_path:
        sqlite_path = Path(args.sqlite_path)
    else:
        from homebuyer.config import DB_PATH
        sqlite_path = DB_PATH

    if not sqlite_path.exists():
        logger.error("SQLite database not found: %s", sqlite_path)
        sys.exit(1)

    # Resolve PostgreSQL URL
    import os
    database_url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error(
            "No PostgreSQL URL provided. Set DATABASE_URL env var or use --database-url"
        )
        sys.exit(1)

    logger.info("Source: %s", sqlite_path)
    logger.info("Target: %s", database_url.split("@")[-1] if "@" in database_url else database_url)

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    # Connect to PostgreSQL
    try:
        import psycopg2
    except ImportError:
        logger.error("psycopg2 is not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    pg_conn = psycopg2.connect(database_url)

    # Initialize schema on PostgreSQL
    logger.info("Initializing PostgreSQL schema...")
    from homebuyer.storage.database import Database
    pg_db = Database(database_url)
    pg_db.connect()
    pg_db.initialize_schema()
    logger.info("Schema initialized.")

    # Determine tables to migrate
    sqlite_tables = get_sqlite_tables(sqlite_conn)
    tables_to_migrate = []
    for t in TABLES_IN_ORDER:
        if t not in sqlite_tables:
            logger.info("Skipping %s (not in SQLite)", t)
            continue
        if args.only_tables and t not in args.only_tables:
            continue
        if t in args.skip_tables:
            logger.info("Skipping %s (--skip-tables)", t)
            continue
        tables_to_migrate.append(t)

    # Also handle any tables not in the predefined order
    for t in sqlite_tables:
        if t not in TABLES_IN_ORDER and t not in args.skip_tables:
            if args.only_tables and t not in args.only_tables:
                continue
            tables_to_migrate.append(t)

    logger.info("Tables to migrate: %s", ", ".join(tables_to_migrate))

    if args.dry_run:
        logger.info("--- DRY RUN ---")
        for table in tables_to_migrate:
            count = get_row_count(sqlite_conn, table)
            logger.info("  %s: %d rows", table, count)
        sqlite_conn.close()
        pg_conn.close()
        return

    # Migrate each table
    start_time = time.time()
    results = {}

    for table in tables_to_migrate:
        columns = get_table_columns(sqlite_conn, table)
        logger.info("Migrating %s (%d columns)...", table, len(columns))

        migrated = migrate_table(sqlite_conn, pg_conn, table, columns)
        results[table] = migrated

        # Reset sequences after migration
        reset_sequences(pg_conn, table, columns)

    elapsed = time.time() - start_time

    # Verification
    logger.info("")
    logger.info("=== Migration Summary ===")
    logger.info("Elapsed: %.1f seconds", elapsed)
    logger.info("")
    logger.info("%-30s %10s %10s %s", "Table", "SQLite", "Postgres", "Status")
    logger.info("-" * 65)

    all_ok = True
    for table in tables_to_migrate:
        sqlite_count = get_row_count(sqlite_conn, table)
        pg_count = get_row_count(pg_conn, table, is_postgres=True)
        status = "OK" if pg_count >= sqlite_count else f"MISMATCH ({pg_count} < {sqlite_count})"
        if pg_count < sqlite_count:
            all_ok = False
        logger.info("%-30s %10d %10d %s", table, sqlite_count, pg_count, status)

    logger.info("")
    if all_ok:
        logger.info("Migration completed successfully!")
    else:
        logger.warning("Some tables have mismatched counts. Check logs for details.")

    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()
