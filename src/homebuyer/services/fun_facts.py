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

if TYPE_CHECKING:
    from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_price(val: float | int | None) -> str:
    """Format a price as $X,XXX,XXX or $X.XXM for millions."""
    if val is None:
        return "N/A"
    val = int(val)
    if val >= 1_000_000:
        m = val / 1_000_000
        # Use one decimal if not a round number
        return f"${m:.1f}M" if val % 100_000 else f"${m:.0f}M"
    return f"${val:,}"


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
    """Most anomalous recent sale (biggest delta vs neighborhood average)."""
    cutoff = _date_ago(2, db=db)
    row = db.fetchone(f"""
        SELECT s.address, s.sale_price, s.neighborhood,
               nm.avg_price,
               s.sale_price - nm.avg_price as delta
        FROM property_sales s
        JOIN (
            SELECT neighborhood, CAST(AVG(sale_price) AS INTEGER) as avg_price
            FROM property_sales
            WHERE sale_price IS NOT NULL AND neighborhood IS NOT NULL
            GROUP BY neighborhood HAVING COUNT(*) >= 5
        ) nm ON s.neighborhood = nm.neighborhood
        WHERE s.sale_price IS NOT NULL
          AND s.sale_date >= {cutoff}
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


def _gen_zone_distribution(db: Database) -> dict | None:
    """Most common zoning class."""
    row = db.fetchone("""
        SELECT zoning_class, COUNT(*) as cnt,
               ROUND(100.0 * COUNT(*) /
                   (SELECT COUNT(*) FROM properties WHERE zoning_class IS NOT NULL), 1
               ) as pct
        FROM properties
        WHERE zoning_class IS NOT NULL
        GROUP BY zoning_class
        ORDER BY cnt DESC LIMIT 1
    """)
    if not row:
        return None
    zone = row["zoning_class"]
    pct = row["pct"]
    return {
        "category": "zone",
        "stat_key": "largest_zone",
        "stat_value": f"{zone}: {pct}%",
        "display_text": (
            f"{zone} zoning covers {pct}% of Berkeley's parcels. "
            f"It's basically the default setting for this city."
        ),
        "detail_json": json.dumps({"zoning_class": zone, "pct": pct}),
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
    """Gap between priciest and cheapest neighborhoods."""
    cutoff = _date_ago(2, db=db)
    rows = db.fetchall(f"""
        SELECT neighborhood, CAST(AVG(sale_price) AS INTEGER) as avg_price
        FROM property_sales
        WHERE sale_price IS NOT NULL AND neighborhood IS NOT NULL
          AND sale_date >= {cutoff}
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
    _gen_zone_distribution,
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
            if db.is_postgres:
                db.conn.rollback()
    db.commit()
    return results
