"""CLI entry point for the HomeBuyer application.

Usage:
    homebuyer init              Create directories and initialize database
    homebuyer collect sales     Fetch property sales from Redfin
    homebuyer collect market    Download Redfin Data Center market metrics
    homebuyer collect rates     Fetch FRED mortgage rates
    homebuyer collect all       Run all three collectors
    homebuyer process all       Normalize, geocode, and deduplicate
    homebuyer status            Show database statistics
    homebuyer export            Export data to CSV
"""

import csv
import sys
import logging
from pathlib import Path

import click

from homebuyer.config import DATA_DIR, DB_PATH, GEO_DIR, RAW_DIR, PROCESSED_DIR
from homebuyer.storage.database import Database
from homebuyer.utils.logging import setup_logging

logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.option("--db-path", type=click.Path(), default=None, help="Override database path.")
@click.pass_context
def main(ctx: click.Context, verbose: bool, db_path: str | None) -> None:
    """HomeBuyer — Berkeley CA home sales data collector and analyzer."""
    ctx.ensure_object(dict)
    level = "DEBUG" if verbose else "INFO"
    setup_logging(level=level, log_file=DATA_DIR / "homebuyer.log")
    ctx.obj["db_path"] = Path(db_path) if db_path else DB_PATH


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@main.command()
@click.option("--force", is_flag=True, help="Recreate database even if it exists.")
@click.pass_context
def init(ctx: click.Context, force: bool) -> None:
    """Create directories, initialize database, and verify geo boundaries."""
    db_path = ctx.obj["db_path"]

    # Create directory structure
    for d in [RAW_DIR / "redfin_sales", RAW_DIR / "redfin_market", RAW_DIR / "fred",
              RAW_DIR / "geo", PROCESSED_DIR, GEO_DIR]:
        d.mkdir(parents=True, exist_ok=True)
        click.echo(f"  Directory: {d}")

    # Initialize database
    if force and db_path.exists():
        db_path.unlink()
        click.echo(f"  Removed existing database: {db_path}")

    with Database(db_path) as db:
        db.initialize_schema()
    click.echo(f"  Database initialized: {db_path}")

    # Check for boundary file
    from homebuyer.collectors.neighborhoods import BOUNDARY_FILE
    if BOUNDARY_FILE.exists():
        from homebuyer.collectors.neighborhoods import get_neighborhood_names
        names = get_neighborhood_names()
        click.echo(f"  Neighborhood boundaries: {len(names)} neighborhoods loaded")
    else:
        click.echo(
            f"  WARNING: No neighborhood boundary file at {BOUNDARY_FILE}\n"
            f"  Geocoding will not work until this file is created.\n"
            f"  Place a GeoJSON file with neighborhood polygons at the path above."
        )

    click.echo("\nInitialization complete.")


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------

@main.group()
def collect() -> None:
    """Collect data from external sources."""
    pass


@collect.command("sales")
@click.option("--days", default=1825, help="Number of days back to query (default: 1825 = ~5 years).")
@click.pass_context
def collect_sales(ctx: click.Context, days: int) -> None:
    """Fetch individual property sales from Redfin."""
    from homebuyer.collectors.redfin_sales import RedfinSalesCollector

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        collector = RedfinSalesCollector(db)
        result = collector.collect(sold_within_days=days)

    click.echo(str(result))
    if not result.success:
        sys.exit(1)


@collect.command("market")
@click.option("--force-download", is_flag=True, help="Re-download even if file exists.")
@click.pass_context
def collect_market(ctx: click.Context, force_download: bool) -> None:
    """Download Redfin Data Center market metrics for Berkeley."""
    from homebuyer.collectors.redfin_market import RedfinMarketCollector

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        collector = RedfinMarketCollector(db)
        result = collector.collect(force_download=force_download)

    click.echo(str(result))
    if not result.success:
        sys.exit(1)


@collect.command("rates")
@click.option("--start", default="2018-01-01", help="Start date (YYYY-MM-DD).")
@click.pass_context
def collect_rates(ctx: click.Context, start: str) -> None:
    """Fetch FRED mortgage rate data."""
    from datetime import date as date_type
    from homebuyer.collectors.fred import FredCollector

    start_date = date_type.fromisoformat(start)
    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        collector = FredCollector(db)
        result = collector.collect(start_date=start_date)

    click.echo(str(result))
    if not result.success:
        sys.exit(1)


@collect.command("all")
@click.option("--days", default=1825, help="Number of days back for sales (default: 1825).")
@click.pass_context
def collect_all(ctx: click.Context, days: int) -> None:
    """Run all three collectors in sequence."""
    click.echo("=" * 60)
    click.echo("Step 1/3: Collecting property sales from Redfin...")
    click.echo("=" * 60)
    ctx.invoke(collect_sales, days=days)

    click.echo()
    click.echo("=" * 60)
    click.echo("Step 2/3: Collecting market metrics from Redfin Data Center...")
    click.echo("=" * 60)
    ctx.invoke(collect_market)

    click.echo()
    click.echo("=" * 60)
    click.echo("Step 3/3: Collecting mortgage rates from FRED...")
    click.echo("=" * 60)
    ctx.invoke(collect_rates)

    click.echo()
    click.echo("All collections complete.")


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------

@main.group()
def process() -> None:
    """Process and enrich collected data."""
    pass


@process.command("normalize")
@click.pass_context
def process_normalize(ctx: click.Context) -> None:
    """Normalize neighborhood names using alias mapping and fuzzy matching."""
    from homebuyer.processing.normalize import normalize_all

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        normalized, remaining = normalize_all(db)

    click.echo(f"Normalized: {normalized}, Still missing: {remaining}")


@process.command("geocode")
@click.pass_context
def process_geocode(ctx: click.Context) -> None:
    """Geocode properties with missing neighborhoods using boundary polygons."""
    from homebuyer.processing.geocode import NeighborhoodGeocoder

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        geocoder = NeighborhoodGeocoder()
        geocoded, unresolved = geocoder.geocode_batch(db)

    click.echo(f"Geocoded: {geocoded}, Unresolved: {unresolved}")


@process.command("deduplicate")
@click.pass_context
def process_deduplicate(ctx: click.Context) -> None:
    """Remove duplicate property sale records."""
    from homebuyer.processing.dedup import deduplicate_sales

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        removed, remaining = deduplicate_sales(db)

    click.echo(f"Removed: {removed} duplicates, Remaining: {remaining} records")


@process.command("validate")
@click.pass_context
def process_validate(ctx: click.Context) -> None:
    """Validate data ranges and report outliers."""
    from homebuyer.processing.clean import validate_sales

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        outliers = validate_sales(db)

    if outliers:
        click.echo("Outliers found:")
        for field, count in outliers.items():
            click.echo(f"  {field}: {count} out-of-range values")
    else:
        click.echo("All data within expected ranges.")


@process.command("all")
@click.pass_context
def process_all(ctx: click.Context) -> None:
    """Run normalize, geocode, and deduplicate in sequence."""
    click.echo("Step 1/3: Normalizing neighborhood names...")
    ctx.invoke(process_normalize)

    click.echo("\nStep 2/3: Geocoding missing neighborhoods...")
    try:
        ctx.invoke(process_geocode)
    except FileNotFoundError as e:
        click.echo(f"  Skipping geocode: {e}")

    click.echo("\nStep 3/3: Deduplicating records...")
    ctx.invoke(process_deduplicate)

    click.echo("\nStep 4/3: Validating data ranges...")
    ctx.invoke(process_validate)

    click.echo("\nAll processing complete.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show database statistics and data freshness."""
    db_path = ctx.obj["db_path"]

    if not db_path.exists():
        click.echo("Database not found. Run 'homebuyer init' first.")
        sys.exit(1)

    with Database(db_path) as db:
        stats = db.get_statistics()

    click.echo()
    click.echo("HomeBuyer Database Status")
    click.echo("=" * 50)

    ps = stats["property_sales"]
    click.echo(f"Property Sales:    {ps['count']:,} records")
    if ps["count"] > 0:
        click.echo(f"  Date range:      {ps['min_date']} to {ps['max_date']}")

    nc = stats["neighborhood_coverage"]
    click.echo(f"  Neighborhoods:   {nc['geocoded']:,}/{nc['total']:,} assigned ({nc['pct']}%)")

    mm = stats["market_metrics"]
    click.echo(f"\nMarket Metrics:    {mm['count']:,} records")
    if mm["count"] > 0:
        click.echo(f"  Date range:      {mm['min_date']} to {mm['max_date']}")

    mr = stats["mortgage_rates"]
    click.echo(f"\nMortgage Rates:    {mr['count']:,} observations")
    if mr["count"] > 0:
        click.echo(f"  Date range:      {mr['min_date']} to {mr['max_date']}")

    nb = stats["neighborhoods"]
    click.echo(f"\nNeighborhoods:     {nb['count']:,} defined")

    if "last_run" in stats:
        lr = stats["last_run"]
        click.echo(f"\nLast Collection:   {lr['source']} ({lr['status']}) at {lr['completed_at']}")

    click.echo()


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@main.command()
@click.option("--table", type=click.Choice(["sales", "market", "rates"]), default="sales")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output CSV file path.")
@click.pass_context
def export(ctx: click.Context, table: str, output: str | None) -> None:
    """Export data to CSV."""
    db_path = ctx.obj["db_path"]

    table_map = {
        "sales": "property_sales",
        "market": "market_metrics",
        "rates": "mortgage_rates",
    }
    sql_table = table_map[table]

    if output is None:
        output = str(PROCESSED_DIR / f"{sql_table}_export.csv")

    with Database(db_path) as db:
        rows = db.conn.execute(f"SELECT * FROM {sql_table}").fetchall()

        if not rows:
            click.echo(f"No data in {sql_table}.")
            return

        # Get column names from the first row
        columns = rows[0].keys()
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                writer.writerow(tuple(row))

    click.echo(f"Exported {len(rows):,} rows to {output_path}")


if __name__ == "__main__":
    main()
