"""Generate fun facts about the Berkeley real estate market.

Pre-computes witty, data-driven one-liners from the database and stores
them in the ``fun_facts`` table.  The Faketor welcome screen picks a
random fact on each page load.

Usage::

    homebuyer generate-facts   # CLI command
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import TYPE_CHECKING

from homebuyer.utils.formatting import fmt_price as _fmt_price

if TYPE_CHECKING:
    from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Residential property types from Redfin — used to exclude commercial
# and large multifamily buildings from fun facts that assume single-family
# scale (anomaly detection, neighborhood price spreads, etc.).
_RESIDENTIAL_TYPES = (
    "Single Family Residential",
    "Condo/Co-op",
    "Townhouse",
    "Multi-Family (2-4 Unit)",
)

_RESIDENTIAL_FILTER = (
    "property_type IN ("
    + ", ".join(f"'{t}'" for t in _RESIDENTIAL_TYPES)
    + ")"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_val(col: str, path: str, *, db: Database, cast: str = "INTEGER") -> str:
    """Return a json extraction expression, dialect-aware."""
    if db.is_postgres:
        # PostgreSQL: col::json->>'key' and cast
        pg_cast = {"INTEGER": "::bigint", "REAL": "::double precision", "TEXT": ""}
        return f"({col}::json->>'{path}'){pg_cast.get(cast, '')}"
    return f"CAST(json_extract({col}, '$.{path}') AS {cast})"


def _date_diff_days(col: str, *, db: Database) -> str:
    """Expression for days between a date column and today."""
    if db.is_postgres:
        return f"EXTRACT(DAY FROM (CURRENT_DATE - {col}::date))"
    return f"CAST(julianday('now') - julianday({col}) AS INTEGER)"


def _date_ago(years: int, *, db: Database) -> str:
    """Expression for a date N years ago."""
    if db.is_postgres:
        return f"(CURRENT_DATE - INTERVAL '{years} years')"
    return f"date('now', '-{years} years')"


def _date_col_ge(col: str, cutoff_expr: str, *, db: Database) -> str:
    """Compare a TEXT date column >= a cutoff expression, dialect-aware.

    In PostgreSQL the column must be explicitly cast to ``date`` because
    TEXT cannot be compared to a ``timestamp`` / ``date`` value.  In SQLite
    the ISO-8601 text representation sorts correctly as-is.
    """
    if db.is_postgres:
        return f"{col}::date >= {cutoff_expr}"
    return f"{col} >= {cutoff_expr}"


# ---------------------------------------------------------------------------
# Fact generators
# ---------------------------------------------------------------------------

def _gen_most_expensive(db: Database) -> dict | None:
    """Most expensive property by ML predicted price."""
    pred = _json_val("ps.prediction_json", "predicted_price", db=db)
    row = db.fetchone(f"""
        SELECT p.address, p.neighborhood, {pred} as predicted
        FROM properties p
        JOIN precomputed_scenarios ps ON p.id = ps.property_id
            AND ps.scenario_type = 'buyer'
        WHERE {pred} IS NOT NULL
          AND p.street_number IS NOT NULL AND p.street_number != ''
          AND p.sqft IS NOT NULL AND p.sqft > 0
        ORDER BY predicted DESC LIMIT 1
    """)
    if not row:
        return None
    addr = row["address"]
    hood = row["neighborhood"] or "Berkeley"
    price = _fmt_price(row["predicted"])
    return {
        "category": "price",
        "stat_key": "most_expensive_predicted",
        "stat_value": str(row["predicted"]),
        "display_text": (
            f"The crown jewel of Berkeley? {addr} in {hood} — our ML model "
            f"thinks you'd need {price} to call it home. Start saving now."
        ),
        "detail_json": json.dumps({"address": addr, "neighborhood": hood}),
    }


def _gen_least_expensive(db: Database) -> dict | None:
    """Least expensive property by ML predicted price."""
    pred = _json_val("ps.prediction_json", "predicted_price", db=db)
    row = db.fetchone(f"""
        SELECT p.address, p.neighborhood, {pred} as predicted
        FROM properties p
        JOIN precomputed_scenarios ps ON p.id = ps.property_id
            AND ps.scenario_type = 'buyer'
        WHERE {pred} IS NOT NULL AND {pred} > 0
          AND p.street_number IS NOT NULL AND p.street_number != ''
          AND p.sqft IS NOT NULL AND p.sqft > 0
        ORDER BY predicted ASC LIMIT 1
    """)
    if not row:
        return None
    addr = row["address"]
    hood = row["neighborhood"] or "Berkeley"
    price = _fmt_price(row["predicted"])
    return {
        "category": "price",
        "stat_key": "least_expensive_predicted",
        "stat_value": str(row["predicted"]),
        "display_text": (
            f"Berkeley's best-kept secret might be {addr} in {hood} — "
            f"our model pegs it at just {price}. "
            f"In Berkeley, that practically counts as free."
        ),
        "detail_json": json.dumps({"address": addr, "neighborhood": hood}),
    }


def _gen_biggest_anomaly(db: Database) -> dict | None:
    """Most anomalous recent sale (biggest delta vs neighborhood average).

    Only considers residential sales so that commercial or large
    multifamily buildings don't dominate the result.
    """
    cutoff = _date_ago(2, db=db)
    date_filter = _date_col_ge("s.sale_date", cutoff, db=db)
    res_outer = _RESIDENTIAL_FILTER.replace("property_type", "s.property_type")
    row = db.fetchone(f"""
        SELECT s.address, s.sale_price, s.neighborhood,
               nm.avg_price,
               s.sale_price - nm.avg_price as delta
        FROM property_sales s
        JOIN (
            SELECT neighborhood, CAST(AVG(sale_price) AS INTEGER) as avg_price
            FROM property_sales
            WHERE sale_price IS NOT NULL AND neighborhood IS NOT NULL
              AND {_RESIDENTIAL_FILTER}
            GROUP BY neighborhood HAVING COUNT(*) >= 5
        ) nm ON s.neighborhood = nm.neighborhood
        WHERE s.sale_price IS NOT NULL
          AND {date_filter}
          AND {res_outer}
        ORDER BY ABS(s.sale_price - nm.avg_price) DESC
        LIMIT 1
    """)
    if not row or row["delta"] is None:
        return None
    addr = row["address"]
    hood = row["neighborhood"]
    sale = _fmt_price(row["sale_price"])
    avg = _fmt_price(row["avg_price"])
    delta = int(row["delta"])
    if delta > 0:
        text = (
            f"{addr} sold for {sale} — that's {_fmt_price(abs(delta))} above "
            f"the {hood} average of {avg}. Someone really wanted that house."
        )
        key = "biggest_overpay"
    else:
        text = (
            f"{addr} sold for {sale} vs. the {hood} average of {avg}. "
            f"Either a steal or there's something the listing didn't mention."
        )
        key = "biggest_underpay"
    return {
        "category": "anomaly",
        "stat_key": key,
        "stat_value": str(abs(delta)),
        "display_text": text,
        "detail_json": json.dumps({"address": addr, "neighborhood": hood,
                                    "sale_price": row["sale_price"],
                                    "avg_price": row["avg_price"]}),
    }


def _gen_longest_unsold(db: Database) -> dict | None:
    """Property with the oldest last_sale_date."""
    row = db.fetchone("""
        SELECT address, neighborhood, last_sale_date
        FROM properties
        WHERE last_sale_date IS NOT NULL AND last_sale_date != ''
          AND neighborhood IS NOT NULL
          AND street_number IS NOT NULL AND street_number != ''
        ORDER BY last_sale_date ASC LIMIT 1
    """)
    if not row or not row["last_sale_date"]:
        return None
    addr = row["address"]
    hood = row["neighborhood"]
    sale_date = row["last_sale_date"]
    try:
        sale_year = int(str(sale_date)[:4])
        years = date.today().year - sale_year
    except (ValueError, TypeError):
        return None
    return {
        "category": "time",
        "stat_key": "longest_unsold",
        "stat_value": str(years),
        "display_text": (
            f"{addr} in {hood} last changed hands in {sale_year} — "
            f"that's {years} years ago. Either they really love it, "
            f"or they really can't leave."
        ),
        "detail_json": json.dumps({"address": addr, "neighborhood": hood,
                                    "last_sale_date": str(sale_date)}),
    }


def _gen_oldest_neighborhood(db: Database) -> dict | None:
    """Neighborhood with the oldest average year_built."""
    row = db.fetchone("""
        SELECT neighborhood, CAST(AVG(year_built) AS INTEGER) as avg_year,
               COUNT(*) as cnt
        FROM properties
        WHERE year_built IS NOT NULL AND neighborhood IS NOT NULL
        GROUP BY neighborhood
        HAVING COUNT(*) >= 10
        ORDER BY avg_year ASC LIMIT 1
    """)
    if not row:
        return None
    hood = row["neighborhood"]
    yr = row["avg_year"]
    return {
        "category": "age",
        "stat_key": "oldest_neighborhood",
        "stat_value": str(yr),
        "display_text": (
            f"If walls could talk, {hood} would have the best stories — "
            f"its average home was built in {yr}. That's vintage, not old."
        ),
        "detail_json": json.dumps({"neighborhood": hood}),
    }


def _gen_zone_largest_by_area(db: Database) -> dict | None:
    """Zone covering the most residential land area (from zones.json metadata)."""
    # This fact comes from official city data, not our sales dataset.
    # R-1 (including R-1H) covers ~49% of Berkeley's residential land —
    # the single largest residential zone by area.
    from homebuyer.utils.file_utils import load_json_data as _load
    from homebuyer.config import REGULATIONS_DIR

    zones_path = REGULATIONS_DIR / "zones.json"
    if not zones_path.exists():
        return None
    zones = _load(zones_path)
    r1 = zones.get("R-1")
    if not r1:
        return None
    return {
        "category": "zone",
        "stat_key": "largest_zone_by_area",
        "stat_value": "R-1: ~49%",
        "display_text": (
            "R-1 (Single Family Residential) covers roughly 49% of "
            "Berkeley's residential land — by far the largest zone by area. "
            "The hills alone account for most of it."
        ),
        "detail_json": json.dumps({
            "zoning_class": "R-1",
            "pct_of_residential_land": 49,
            "source": "Berkeley Municipal Code Title 23",
        }),
    }


def _gen_zone_most_properties(db: Database) -> dict | None:
    """Zone with the most tracked properties in our database."""
    if db.is_postgres:
        pct_expr = ("ROUND((100.0 * COUNT(*) / "
                    "(SELECT COUNT(*) FROM properties "
                    "WHERE zoning_class IS NOT NULL))::numeric, 1)")
    else:
        pct_expr = ("ROUND(100.0 * COUNT(*) / "
                    "(SELECT COUNT(*) FROM properties "
                    "WHERE zoning_class IS NOT NULL), 1)")
    row = db.fetchone(f"""
        SELECT zoning_class, COUNT(*) as cnt,
               {pct_expr} as pct
        FROM properties
        WHERE zoning_class IS NOT NULL
        GROUP BY zoning_class
        ORDER BY cnt DESC LIMIT 1
    """)
    if not row:
        return None
    zone = row["zoning_class"]
    pct = float(row["pct"])
    cnt = int(row["cnt"])
    return {
        "category": "zone",
        "stat_key": "most_properties_zone",
        "stat_value": f"{zone}: {cnt} properties ({pct}%)",
        "display_text": (
            f"{zone} has the most tracked properties in Berkeley — "
            f"{cnt} homes ({pct}% of our database). "
            f"Smaller flatland lots mean more properties per acre."
        ),
        "detail_json": json.dumps({
            "zoning_class": zone, "count": cnt, "pct": pct,
        }),
    }


def _gen_zone_most_sales(db: Database) -> dict | None:
    """Zone with the highest sales turnover in the last 2 years."""
    cutoff = _date_ago(2, db=db)
    date_filter = _date_col_ge("s.sale_date", cutoff, db=db)
    if db.is_postgres:
        pct_expr = ("ROUND((100.0 * COUNT(*) / "
                    f"(SELECT COUNT(*) FROM property_sales s "
                    f"JOIN properties p ON s.address = p.address "
                    f"WHERE p.zoning_class IS NOT NULL "
                    f"AND {date_filter.replace('s.sale_date', 's.sale_date')}))::numeric, 1)")
    else:
        pct_expr = ("ROUND(100.0 * COUNT(*) / "
                    f"(SELECT COUNT(*) FROM property_sales s "
                    f"JOIN properties p ON s.address = p.address "
                    f"WHERE p.zoning_class IS NOT NULL "
                    f"AND {date_filter.replace('s.sale_date', 's.sale_date')}), 1)")
    row = db.fetchone(f"""
        SELECT p.zoning_class, COUNT(*) as sale_cnt,
               {pct_expr} as pct
        FROM property_sales s
        JOIN properties p ON s.address = p.address
        WHERE p.zoning_class IS NOT NULL
          AND {date_filter}
        GROUP BY p.zoning_class
        ORDER BY sale_cnt DESC LIMIT 1
    """)
    if not row:
        return None
    zone = row["zoning_class"]
    cnt = int(row["sale_cnt"])
    pct = float(row["pct"])
    return {
        "category": "zone",
        "stat_key": "most_sales_zone",
        "stat_value": f"{zone}: {cnt} sales ({pct}%)",
        "display_text": (
            f"{zone} zones see the most action — {cnt} sales in the "
            f"last 2 years ({pct}% of all Berkeley transactions). "
            f"That's where the market moves fastest."
        ),
        "detail_json": json.dumps({
            "zoning_class": zone, "sale_count": cnt, "pct": pct,
        }),
    }


def _gen_vacant_lot_count(db: Database) -> dict | None:
    """How many vacant lots exist in our database."""
    if db.is_postgres:
        pct_expr = ("ROUND((100.0 * COUNT(*) / "
                    "(SELECT COUNT(*) FROM properties))::numeric, 1)")
        total_expr = "ROUND((SUM(lot_size_sqft) / 43560.0)::numeric, 1)"
    else:
        pct_expr = ("ROUND(100.0 * COUNT(*) / "
                    "(SELECT COUNT(*) FROM properties), 1)")
        total_expr = "ROUND(SUM(lot_size_sqft) / 43560.0, 1)"
    row = db.fetchone(f"""
        SELECT COUNT(*) as cnt,
               {pct_expr} as pct,
               {total_expr} as total_acres
        FROM properties
        WHERE property_category = 'land'
          AND lot_size_sqft IS NOT NULL AND lot_size_sqft > 0
    """)
    if not row or row["cnt"] == 0:
        return None
    cnt = int(row["cnt"])
    pct = float(row["pct"])
    acres = float(row["total_acres"])
    return {
        "category": "land",
        "stat_key": "vacant_lot_count",
        "stat_value": f"{cnt} lots ({acres} acres)",
        "display_text": (
            f"Berkeley has {cnt} vacant lots in our database — "
            f"about {pct}% of all tracked parcels, totaling {acres} acres. "
            f"That's a lot of potential in a city where every sqft counts."
        ),
        "detail_json": json.dumps({
            "count": cnt, "pct": pct, "total_acres": acres,
        }),
    }


def _gen_vacant_lot_largest(db: Database) -> dict | None:
    """Largest vacant lot."""
    row = db.fetchone("""
        SELECT address, neighborhood, lot_size_sqft, zoning_class
        FROM properties
        WHERE property_category = 'land'
          AND lot_size_sqft IS NOT NULL AND lot_size_sqft > 0
          AND street_number IS NOT NULL AND street_number != ''
        ORDER BY lot_size_sqft DESC LIMIT 1
    """)
    if not row:
        return None
    addr = row["address"]
    hood = row["neighborhood"] or "Berkeley"
    sqft = int(row["lot_size_sqft"])
    acres = round(sqft / 43560, 2)
    zone = row["zoning_class"] or "unknown"
    return {
        "category": "land",
        "stat_key": "largest_vacant_lot",
        "stat_value": f"{sqft:,} sqft ({acres} acres)",
        "display_text": (
            f"The biggest vacant lot we track is {addr} in {hood} — "
            f"{sqft:,} sqft ({acres} acres) of undeveloped {zone} land. "
            f"Someone's sitting on serious potential."
        ),
        "detail_json": json.dumps({
            "address": addr, "neighborhood": hood,
            "lot_size_sqft": sqft, "zoning_class": zone,
        }),
    }


def _gen_vacant_lot_smallest(db: Database) -> dict | None:
    """Smallest buildable vacant lot (>= 1,000 sqft to skip slivers)."""
    row = db.fetchone("""
        SELECT address, neighborhood, lot_size_sqft, zoning_class
        FROM properties
        WHERE property_category = 'land'
          AND lot_size_sqft IS NOT NULL AND lot_size_sqft >= 1000
          AND street_number IS NOT NULL AND street_number != ''
        ORDER BY lot_size_sqft ASC LIMIT 1
    """)
    if not row:
        return None
    addr = row["address"]
    hood = row["neighborhood"] or "Berkeley"
    sqft = int(row["lot_size_sqft"])
    zone = row["zoning_class"] or "unknown"
    return {
        "category": "land",
        "stat_key": "smallest_vacant_lot",
        "stat_value": f"{sqft:,} sqft",
        "display_text": (
            f"The tiniest buildable vacant lot? {addr} in {hood} at just "
            f"{sqft:,} sqft ({zone} zoning). In Berkeley, even a postage "
            f"stamp of land is an opportunity."
        ),
        "detail_json": json.dumps({
            "address": addr, "neighborhood": hood,
            "lot_size_sqft": sqft, "zoning_class": zone,
        }),
    }


def _gen_median_price(db: Database) -> dict | None:
    """Current median sale price from market metrics."""
    row = db.fetchone("""
        SELECT median_sale_price, period_end
        FROM market_metrics
        WHERE median_sale_price IS NOT NULL AND period_duration = '30'
        ORDER BY period_end DESC LIMIT 1
    """)
    if not row:
        return None
    price = _fmt_price(row["median_sale_price"])
    period = str(row["period_end"])[:7]  # YYYY-MM
    return {
        "category": "market",
        "stat_key": "median_price",
        "stat_value": str(row["median_sale_price"]),
        "display_text": (
            f"Berkeley's median home price is {price} as of {period}. "
            f"Your morning coffee costs less, but not by as much as you'd think."
        ),
        "detail_json": json.dumps({"period": period}),
    }


def _gen_median_dom(db: Database) -> dict | None:
    """Current median days on market."""
    row = db.fetchone("""
        SELECT median_dom, period_end
        FROM market_metrics
        WHERE median_dom IS NOT NULL AND period_duration = '30'
        ORDER BY period_end DESC LIMIT 1
    """)
    if not row:
        return None
    dom = int(row["median_dom"])
    return {
        "category": "market",
        "stat_key": "median_dom",
        "stat_value": str(dom),
        "display_text": (
            f"The median Berkeley home sells in {dom} days. "
            f"Blink and you might miss your dream house. No pressure."
        ),
        "detail_json": None,
    }


def _gen_sale_to_list(db: Database) -> dict | None:
    """Current sale-to-list ratio."""
    row = db.fetchone("""
        SELECT avg_sale_to_list, period_end
        FROM market_metrics
        WHERE avg_sale_to_list IS NOT NULL AND period_duration = '30'
        ORDER BY period_end DESC LIMIT 1
    """)
    if not row or not row["avg_sale_to_list"]:
        return None
    ratio = float(row["avg_sale_to_list"])
    pct = round(ratio * 100, 1)
    if ratio >= 1.0:
        text = (
            f"Homes are selling at {pct}% of asking price. Yes, that's above "
            f"100%. Welcome to Berkeley, where list prices are just opening bids."
        )
    else:
        text = (
            f"Homes are selling at {pct}% of asking price. Sellers aren't "
            f"quite getting everything they wish for — but close."
        )
    return {
        "category": "market",
        "stat_key": "sale_to_list",
        "stat_value": str(pct),
        "display_text": text,
        "detail_json": None,
    }


def _gen_price_spread(db: Database) -> dict | None:
    """Gap between priciest and cheapest neighborhoods.

    Restricted to residential sales so that a single large commercial
    transaction doesn't skew an entire neighborhood's average.
    """
    cutoff = _date_ago(2, db=db)
    date_filter = _date_col_ge("sale_date", cutoff, db=db)
    rows = db.fetchall(f"""
        SELECT neighborhood, CAST(AVG(sale_price) AS INTEGER) as avg_price
        FROM property_sales
        WHERE sale_price IS NOT NULL AND neighborhood IS NOT NULL
          AND {date_filter}
          AND {_RESIDENTIAL_FILTER}
        GROUP BY neighborhood HAVING COUNT(*) >= 5
        ORDER BY avg_price DESC
    """)
    if not rows or len(rows) < 2:
        return None
    expensive = rows[0]
    cheap = rows[-1]
    delta = expensive["avg_price"] - cheap["avg_price"]
    return {
        "category": "neighborhood",
        "stat_key": "price_spread",
        "stat_value": str(delta),
        "display_text": (
            f"The gap between {expensive['neighborhood']} "
            f"({_fmt_price(expensive['avg_price'])} avg) and "
            f"{cheap['neighborhood']} ({_fmt_price(cheap['avg_price'])} avg) "
            f"is {_fmt_price(delta)}. Same city, different universes."
        ),
        "detail_json": json.dumps({
            "expensive": expensive["neighborhood"],
            "cheap": cheap["neighborhood"],
        }),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_GENERATORS = [
    _gen_most_expensive,
    _gen_least_expensive,
    _gen_biggest_anomaly,
    _gen_longest_unsold,
    _gen_oldest_neighborhood,
    _gen_zone_largest_by_area,
    _gen_zone_most_properties,
    _gen_zone_most_sales,
    _gen_vacant_lot_count,
    _gen_vacant_lot_largest,
    _gen_vacant_lot_smallest,
    _gen_median_price,
    _gen_median_dom,
    _gen_sale_to_list,
    _gen_price_spread,
]


def generate_fun_facts(db: Database) -> list[dict]:
    """Run all fact generators and store results in the database.

    Returns the list of generated fact dicts.
    """
    results: list[dict] = []
    for gen_fn in _GENERATORS:
        name = gen_fn.__name__
        try:
            fact = gen_fn(db)
            if fact:
                db.upsert_fun_fact(
                    category=fact["category"],
                    stat_key=fact["stat_key"],
                    stat_value=fact["stat_value"],
                    display_text=fact["display_text"],
                    detail_json=fact.get("detail_json"),
                )
                results.append(fact)
                logger.info("Generated fact: [%s] %s", fact["category"], fact["stat_key"])
            else:
                logger.info("No data for fact generator %s — skipped", name)
        except Exception:
            logger.warning("Fact generator %s failed", name, exc_info=True)
            # PostgreSQL aborts the entire transaction on error — rollback so
            # subsequent generators can still run.
            db.rollback()
    db.commit()
    return results
