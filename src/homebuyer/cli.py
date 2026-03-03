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
# analyze
# ---------------------------------------------------------------------------

@main.group()
def analyze() -> None:
    """Analyze collected data for pricing insights."""
    pass


@analyze.command("summary")
@click.pass_context
def analyze_summary(ctx: click.Context) -> None:
    """Generate a comprehensive market summary report."""
    import json
    from homebuyer.analysis.market_analysis import MarketAnalyzer

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        analyzer = MarketAnalyzer(db)
        report = analyzer.generate_summary_report()

    click.echo("\n" + "=" * 60)
    click.echo("BERKELEY HOME MARKET SUMMARY")
    click.echo("=" * 60)

    cov = report["data_coverage"]
    click.echo(f"\nData: {cov['total_sales']:,} sales from {cov['date_range']['earliest']} "
               f"to {cov['date_range']['latest']} across {cov['neighborhoods_covered']} neighborhoods")

    mkt = report["current_market"]
    click.echo(f"\nCurrent Market ({mkt['period']}):")
    click.echo(f"  Median Sale Price:    ${mkt['median_sale_price']:,}" if mkt['median_sale_price'] else "  Median Sale Price:    N/A")
    click.echo(f"  Median List Price:    ${mkt['median_list_price']:,}" if mkt['median_list_price'] else "  Median List Price:    N/A")
    if mkt['sale_to_list_ratio']:
        click.echo(f"  Sale-to-List Ratio:   {mkt['sale_to_list_ratio']:.1%} "
                    f"(homes sell {(mkt['sale_to_list_ratio']-1)*100:+.1f}% vs list)")
    if mkt['sold_above_list_pct'] is not None:
        click.echo(f"  Sold Above List:      {mkt['sold_above_list_pct']:.0f}%")
    click.echo(f"  Homes Sold/Month:     {mkt['homes_sold_monthly']}" if mkt['homes_sold_monthly'] else "")
    click.echo(f"  Days on Market:       {mkt['median_days_on_market']}" if mkt['median_days_on_market'] else "")
    click.echo(f"  30yr Mortgage Rate:   {mkt['mortgage_rate_30yr']:.2f}%" if mkt['mortgage_rate_30yr'] else "")

    click.echo(f"\nPrice Distribution (last 2 years):")
    for bucket in report["price_distribution_2yr"]:
        bar = "█" * max(1, bucket["count"] // 5)
        click.echo(f"  {bucket['bracket']:>15s}: {bucket['count']:>4d} {bar}")

    click.echo(f"\nTop Neighborhoods by Median Price (last 2 years):")
    click.echo(f"  {'Neighborhood':<25s} {'Median':>12s} {'$/sqft':>8s} {'Sales':>6s} {'YoY':>7s}")
    click.echo(f"  {'-'*25} {'-'*12} {'-'*8} {'-'*6} {'-'*7}")
    for n in report["top_neighborhoods_by_price"]:
        median_str = f"${n['median_price']:,.0f}" if n['median_price'] else "N/A"
        ppsf_str = f"${n['avg_ppsf']:,.0f}" if n['avg_ppsf'] else "N/A"
        yoy_str = f"{n['yoy_change']:+.1f}%" if n['yoy_change'] is not None else "N/A"
        click.echo(f"  {n['name']:<25s} {median_str:>12s} {ppsf_str:>8s} {n['sales']:>6d} {yoy_str:>7s}")

    click.echo()


@analyze.command("neighborhood")
@click.argument("name")
@click.option("--years", default=2, help="Years of data to analyze (default: 2).")
@click.pass_context
def analyze_neighborhood(ctx: click.Context, name: str, years: int) -> None:
    """Get detailed stats for a specific neighborhood."""
    from homebuyer.analysis.market_analysis import MarketAnalyzer

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        analyzer = MarketAnalyzer(db)
        stats = analyzer.get_neighborhood_stats(name, lookback_years=years)

    if stats.sale_count == 0:
        click.echo(f"No sales found for '{name}' in the last {years} years.")
        click.echo("Run 'homebuyer analyze neighborhoods' to see available names.")
        return

    click.echo(f"\n{'=' * 50}")
    click.echo(f"NEIGHBORHOOD: {stats.name}")
    click.echo(f"{'=' * 50}")
    click.echo(f"  Sales (last {years} years):   {stats.sale_count}")
    click.echo(f"  Median Price:          ${stats.median_price:,.0f}" if stats.median_price else "")
    click.echo(f"  Average Price:         ${stats.avg_price:,.0f}" if stats.avg_price else "")
    click.echo(f"  Price Range:           ${stats.min_price:,.0f} — ${stats.max_price:,.0f}" if stats.min_price else "")
    click.echo(f"  Median $/sqft:         ${stats.median_ppsf:,.0f}" if stats.median_ppsf else "")
    click.echo(f"  Avg $/sqft:            ${stats.avg_ppsf:,.0f}" if stats.avg_ppsf else "")
    click.echo(f"  Avg Year Built:        {stats.avg_year_built}" if stats.avg_year_built else "")
    if stats.yoy_price_change_pct is not None:
        click.echo(f"  YoY Price Change:      {stats.yoy_price_change_pct:+.1f}%")
    click.echo()


@analyze.command("neighborhoods")
@click.option("--min-sales", default=5, help="Minimum sales to include (default: 5).")
@click.option("--years", default=2, help="Years of data to analyze (default: 2).")
@click.pass_context
def analyze_neighborhoods(ctx: click.Context, min_sales: int, years: int) -> None:
    """Rank all neighborhoods by median price."""
    from homebuyer.analysis.market_analysis import MarketAnalyzer

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        analyzer = MarketAnalyzer(db)
        rankings = analyzer.get_all_neighborhood_rankings(
            lookback_years=years, min_sales=min_sales
        )

    click.echo(f"\n{'=' * 70}")
    click.echo(f"BERKELEY NEIGHBORHOOD RANKINGS (last {years} years, min {min_sales} sales)")
    click.echo(f"{'=' * 70}")
    click.echo(f"  {'#':>3s} {'Neighborhood':<25s} {'Median':>12s} {'$/sqft':>8s} {'Sales':>6s} {'YoY':>7s}")
    click.echo(f"  {'─'*3} {'─'*25} {'─'*12} {'─'*8} {'─'*6} {'─'*7}")

    for i, s in enumerate(rankings, 1):
        median_str = f"${s.median_price:,.0f}" if s.median_price else "N/A"
        ppsf_str = f"${s.median_ppsf:,.0f}" if s.median_ppsf else "N/A"
        yoy_str = f"{s.yoy_price_change_pct:+.1f}%" if s.yoy_price_change_pct is not None else "N/A"
        click.echo(f"  {i:>3d} {s.name:<25s} {median_str:>12s} {ppsf_str:>8s} {s.sale_count:>6d} {yoy_str:>7s}")

    click.echo()


@analyze.command("estimate")
@click.argument("neighborhood")
@click.option("--beds", type=float, help="Number of bedrooms.")
@click.option("--baths", type=float, help="Number of bathrooms.")
@click.option("--sqft", type=int, help="Square footage.")
@click.option("--year-built", type=int, help="Year built.")
@click.option("--lot-size", type=int, help="Lot size in sqft.")
@click.pass_context
def analyze_estimate(
    ctx: click.Context,
    neighborhood: str,
    beds: float | None,
    baths: float | None,
    sqft: int | None,
    year_built: int | None,
    lot_size: int | None,
) -> None:
    """Estimate realistic sale price for a property."""
    from homebuyer.analysis.market_analysis import MarketAnalyzer

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        analyzer = MarketAnalyzer(db)
        estimate = analyzer.estimate_price(
            neighborhood=neighborhood,
            beds=beds,
            baths=baths,
            sqft=sqft,
            year_built=year_built,
            lot_size_sqft=lot_size,
        )

    if estimate.estimated_price == 0:
        click.echo(f"Could not estimate price. {estimate.methodology_notes}")
        return

    click.echo(f"\n{'=' * 60}")
    click.echo(f"PRICE ESTIMATE — {neighborhood}")
    click.echo(f"{'=' * 60}")

    criteria = []
    if beds: criteria.append(f"{beds:.0f} bed")
    if baths: criteria.append(f"{baths:.0f} bath")
    if sqft: criteria.append(f"{sqft:,} sqft")
    if year_built: criteria.append(f"built {year_built}")
    if lot_size: criteria.append(f"{lot_size:,} sqft lot")
    click.echo(f"  Criteria: {', '.join(criteria) if criteria else 'No specific criteria'}")

    click.echo(f"\n  Estimated Sale Price:  ${estimate.estimated_price:,.0f}")
    click.echo(f"  Price Range:           ${estimate.price_range_low:,.0f} — ${estimate.price_range_high:,.0f}")
    click.echo(f"  Confidence:            {estimate.confidence.upper()}")
    click.echo(f"  Based on:              {estimate.comparable_count} comparable sales")

    if estimate.sale_to_list_ratio:
        click.echo(f"  Market Sale/List:      {estimate.sale_to_list_ratio:.1%}")

    click.echo(f"\n  Methodology:")
    for note in estimate.methodology_notes:
        click.echo(f"    • {note}")

    if estimate.comparables:
        click.echo(f"\n  Top Comparable Sales:")
        click.echo(f"    {'Address':<30s} {'Date':>12s} {'Price':>12s} {'Bed':>4s} {'Sqft':>6s}")
        click.echo(f"    {'─'*30} {'─'*12} {'─'*12} {'─'*4} {'─'*6}")
        for c in estimate.comparables[:7]:
            addr = c.address[:29] if len(c.address) > 29 else c.address
            beds_s = f"{c.beds:.0f}" if c.beds else "—"
            sqft_s = f"{c.sqft:,}" if c.sqft else "—"
            click.echo(f"    {addr:<30s} {c.sale_date.isoformat():>12s} ${c.sale_price:>10,} {beds_s:>4s} {sqft_s:>6s}")

    click.echo()


@analyze.command("trend")
@click.option("--months", default=24, help="Months to look back (default: 24).")
@click.pass_context
def analyze_trend(ctx: click.Context, months: int) -> None:
    """Show monthly market trend data."""
    from homebuyer.analysis.market_analysis import MarketAnalyzer

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        analyzer = MarketAnalyzer(db)
        trend = analyzer.get_market_trend(months=months)

    if not trend:
        click.echo("No market trend data available.")
        return

    click.echo(f"\n{'=' * 90}")
    click.echo(f"BERKELEY MARKET TREND (last {months} months)")
    click.echo(f"{'=' * 90}")
    click.echo(f"  {'Month':>7s} {'Med.Sale':>12s} {'Med.List':>12s} {'S/L Ratio':>10s} "
               f"{'Above List':>10s} {'Sold':>5s} {'DOM':>4s} {'Rate':>6s}")
    click.echo(f"  {'─'*7} {'─'*12} {'─'*12} {'─'*10} {'─'*10} {'─'*5} {'─'*4} {'─'*6}")

    for s in trend:
        sale_str = f"${s.median_sale_price:,}" if s.median_sale_price else "—"
        list_str = f"${s.median_list_price:,}" if s.median_list_price else "—"
        ratio_str = f"{s.sale_to_list_ratio:.1%}" if s.sale_to_list_ratio else "—"
        above_str = f"{s.sold_above_list_pct:.0f}%" if s.sold_above_list_pct is not None else "—"
        sold_str = f"{s.homes_sold}" if s.homes_sold else "—"
        dom_str = f"{s.median_dom}" if s.median_dom else "—"
        rate_str = f"{s.mortgage_rate_30yr:.2f}%" if s.mortgage_rate_30yr else "—"
        click.echo(f"  {s.period:>7s} {sale_str:>12s} {list_str:>12s} {ratio_str:>10s} "
                    f"{above_str:>10s} {sold_str:>5s} {dom_str:>4s} {rate_str:>6s}")

    click.echo()


@analyze.command("afford")
@click.argument("monthly_budget", type=int)
@click.option("--down-pct", default=20.0, help="Down payment percentage (default: 20%).")
@click.option("--hoa", default=0, help="Monthly HOA dues (default: 0).")
@click.pass_context
def analyze_afford(ctx: click.Context, monthly_budget: int, down_pct: float, hoa: int) -> None:
    """Determine affordable price range for a given monthly budget."""
    from homebuyer.analysis.market_analysis import MarketAnalyzer

    db_path = ctx.obj["db_path"]
    with Database(db_path) as db:
        analyzer = MarketAnalyzer(db)
        result = analyzer.assess_affordability(
            monthly_budget=monthly_budget,
            down_payment_pct=down_pct,
            hoa_monthly=hoa,
        )

    click.echo(f"\n{'=' * 60}")
    click.echo(f"AFFORDABILITY ANALYSIS")
    click.echo(f"{'=' * 60}")
    click.echo(f"  Monthly Budget:        ${result['monthly_budget']:,}")
    click.echo(f"  30yr Mortgage Rate:    {result['mortgage_rate_30yr']:.2f}%")
    click.echo(f"  Down Payment:          {down_pct:.0f}% (${result['down_payment_amount']:,})")
    click.echo(f"  Max Affordable Price:  ${result['max_affordable_price']:,}")
    click.echo(f"  Loan Amount:           ${result['loan_amount']:,}")
    if result['is_jumbo_loan']:
        click.echo(f"  ⚠ JUMBO LOAN (above ${result['jumbo_threshold']:,} conforming limit)")

    if result['affordable_neighborhoods']:
        click.echo(f"\n  Neighborhoods with recent sales in your range:")
        click.echo(f"    {'Neighborhood':<25s} {'Sales':>6s} {'Avg Price':>12s} {'Lowest':>12s}")
        click.echo(f"    {'─'*25} {'─'*6} {'─'*12} {'─'*12}")
        for n in result['affordable_neighborhoods']:
            click.echo(f"    {n['name']:<25s} {n['recent_sales_in_range']:>6d} "
                        f"${n['avg_price']:>10,} ${n['lowest_recent_sale']:>10,}")
    else:
        click.echo(f"\n  No neighborhoods with recent sales under ${result['max_affordable_price']:,}")
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
