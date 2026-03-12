"""Market analysis for Berkeley home sales.

Provides trend analysis, neighborhood comparisons, and price estimation tools
to help buyers understand realistic sale prices vs. list prices.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


@dataclass
class NeighborhoodStats:
    """Aggregated statistics for a single neighborhood."""

    name: str
    sale_count: int = 0
    median_price: Optional[float] = None
    avg_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    median_ppsf: Optional[float] = None
    avg_ppsf: Optional[float] = None
    median_sqft: Optional[float] = None
    avg_year_built: Optional[int] = None
    # Price change year-over-year
    yoy_price_change_pct: Optional[float] = None
    # API / zoning enrichment
    median_lot_size: Optional[int] = None
    property_type_breakdown: dict[str, float] = field(default_factory=dict)
    dominant_zoning: list[str] = field(default_factory=list)
    zoning_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class MarketSnapshot:
    """Point-in-time snapshot of market conditions."""

    period: str  # e.g., "2025-Q4" or "2025-12"
    median_sale_price: Optional[int] = None
    median_list_price: Optional[int] = None
    sale_to_list_ratio: Optional[float] = None
    sold_above_list_pct: Optional[float] = None
    homes_sold: Optional[int] = None
    inventory: Optional[int] = None
    median_dom: Optional[int] = None
    mortgage_rate_30yr: Optional[float] = None


@dataclass
class ComparableProperty:
    """A comparable property sale for price estimation."""

    address: str
    sale_date: date
    sale_price: int
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    year_built: Optional[int] = None
    neighborhood: Optional[str] = None
    price_per_sqft: Optional[float] = None
    similarity_score: float = 0.0  # similarity to target
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class PriceEstimate:
    """Estimated realistic sale price with supporting data."""

    estimated_price: int
    confidence: str  # "high", "medium", "low"
    price_range_low: int
    price_range_high: int
    comparable_count: int
    comparables: list[ComparableProperty] = field(default_factory=list)
    methodology_notes: list[str] = field(default_factory=list)
    market_adjustment_pct: Optional[float] = None
    sale_to_list_ratio: Optional[float] = None


# ---------------------------------------------------------------------------
# Analysis class
# ---------------------------------------------------------------------------


class MarketAnalyzer:
    """Analyzes Berkeley home sales data for pricing insights."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # -------------------------------------------------------------------
    # Neighborhood analysis
    # -------------------------------------------------------------------

    def get_neighborhood_stats(
        self,
        neighborhood: str,
        lookback_years: int = 2,
    ) -> NeighborhoodStats:
        """Get aggregated statistics for a specific neighborhood.

        Args:
            neighborhood: The canonical neighborhood name.
            lookback_years: How many years of data to consider.

        Returns:
            NeighborhoodStats with median/avg prices, price per sqft, etc.
        """
        cutoff = date.today() - timedelta(days=lookback_years * 365)

        row = self.db.execute(
            """
            SELECT
                COUNT(*) as cnt,
                CAST(AVG(sale_price) AS INTEGER) as avg_price,
                CAST(MIN(sale_price) AS INTEGER) as min_price,
                CAST(MAX(sale_price) AS INTEGER) as max_price,
                AVG(price_per_sqft) as avg_ppsf,
                AVG(sqft) as avg_sqft,
                CAST(AVG(year_built) AS INTEGER) as avg_year_built
            FROM property_sales
            WHERE neighborhood = ?
              AND sale_date >= ?
              AND sale_price IS NOT NULL
            """,
            (neighborhood, cutoff.isoformat()),
        ).fetchone()

        stats = NeighborhoodStats(name=neighborhood)
        if not row or row["cnt"] == 0:
            return stats

        stats.sale_count = row["cnt"]
        stats.avg_price = row["avg_price"]
        stats.min_price = row["min_price"]
        stats.max_price = row["max_price"]
        stats.avg_ppsf = round(row["avg_ppsf"], 2) if row["avg_ppsf"] else None
        stats.median_sqft = row["avg_sqft"]  # approx
        stats.avg_year_built = row["avg_year_built"]

        # Calculate median sale price
        prices = self.db.execute(
            """
            SELECT sale_price FROM property_sales
            WHERE neighborhood = ? AND sale_date >= ? AND sale_price IS NOT NULL
            ORDER BY sale_price
            """,
            (neighborhood, cutoff.isoformat()),
        ).fetchall()
        if prices:
            mid = len(prices) // 2
            stats.median_price = prices[mid]["sale_price"]

        # Median price per sqft
        ppsf_rows = self.db.execute(
            """
            SELECT price_per_sqft FROM property_sales
            WHERE neighborhood = ? AND sale_date >= ?
              AND price_per_sqft IS NOT NULL
            ORDER BY price_per_sqft
            """,
            (neighborhood, cutoff.isoformat()),
        ).fetchall()
        if ppsf_rows:
            mid = len(ppsf_rows) // 2
            stats.median_ppsf = round(ppsf_rows[mid]["price_per_sqft"], 2)

        # Year-over-year price change
        stats.yoy_price_change_pct = self._calc_yoy_change(neighborhood)

        # API / zoning enrichment
        self._enrich_neighborhood_stats(stats, lookback_years)

        return stats

    def get_all_neighborhood_rankings(
        self,
        lookback_years: int = 2,
        min_sales: int = 5,
    ) -> list[NeighborhoodStats]:
        """Rank all neighborhoods by median sale price.

        Args:
            lookback_years: How many years of data to consider.
            min_sales: Minimum number of sales to include a neighborhood.

        Returns:
            List of NeighborhoodStats sorted by median price descending.
        """
        cutoff = date.today() - timedelta(days=lookback_years * 365)

        neighborhoods = self.db.execute(
            """
            SELECT DISTINCT neighborhood
            FROM property_sales
            WHERE neighborhood IS NOT NULL
              AND sale_date >= ?
            """,
            (cutoff.isoformat(),),
        ).fetchall()

        results = []
        for row in neighborhoods:
            stats = self.get_neighborhood_stats(row["neighborhood"], lookback_years)
            if stats.sale_count >= min_sales:
                results.append(stats)

        results.sort(key=lambda s: s.median_price or 0, reverse=True)
        return results

    # -------------------------------------------------------------------
    # Market trends
    # -------------------------------------------------------------------

    def get_market_trend(
        self,
        months: int = 24,
        property_type: str = "All Residential",
    ) -> list[MarketSnapshot]:
        """Get monthly market trend data for Berkeley.

        Args:
            months: Number of months to look back.
            property_type: Filter by property type from market_metrics.

        Returns:
            List of MarketSnapshot objects, chronologically ordered.
        """
        cutoff = date.today() - timedelta(days=months * 30)

        rows = self.db.execute(
            """
            SELECT
                period_begin,
                median_sale_price,
                median_list_price,
                avg_sale_to_list,
                sold_above_list_pct,
                homes_sold,
                inventory,
                median_dom
            FROM market_metrics
            WHERE period_begin >= ?
              AND property_type = ?
              AND period_duration = '30'
            ORDER BY period_begin
            """,
            (cutoff.isoformat(), property_type),
        ).fetchall()

        snapshots = []
        for row in rows:
            period = row["period_begin"][:7]  # "2025-01"

            # Find closest mortgage rate
            rate = self._get_mortgage_rate_for_date(row["period_begin"])

            snapshots.append(
                MarketSnapshot(
                    period=period,
                    median_sale_price=row["median_sale_price"],
                    median_list_price=row["median_list_price"],
                    sale_to_list_ratio=round(row["avg_sale_to_list"], 4)
                    if row["avg_sale_to_list"]
                    else None,
                    sold_above_list_pct=round(row["sold_above_list_pct"] * 100, 1)
                    if row["sold_above_list_pct"]
                    else None,
                    homes_sold=row["homes_sold"],
                    inventory=row["inventory"],
                    median_dom=row["median_dom"],
                    mortgage_rate_30yr=rate,
                )
            )

        return snapshots

    def get_current_market_conditions(self) -> MarketSnapshot:
        """Get the most recent market snapshot.

        Returns:
            MarketSnapshot for the latest month with data.
        """
        trend = self.get_market_trend(months=3)
        if trend:
            return trend[-1]
        return MarketSnapshot(period="unknown")

    # -------------------------------------------------------------------
    # Comparable sales & price estimation
    # -------------------------------------------------------------------

    def find_comparables(
        self,
        neighborhood: str,
        beds: Optional[float] = None,
        baths: Optional[float] = None,
        sqft: Optional[int] = None,
        year_built: Optional[int] = None,
        lookback_months: int = 24,
        max_results: int = 10,
        property_type: Optional[str] = None,
    ) -> list[ComparableProperty]:
        """Find comparable property sales matching given criteria.

        Args:
            neighborhood: Target neighborhood name.
            beds: Number of bedrooms (exact or ±1).
            baths: Number of bathrooms (exact or ±1).
            sqft: Square footage (within ±20%).
            year_built: Year built (within ±15 years).
            lookback_months: How far back to search.
            max_results: Maximum comparables to return.
            property_type: Property type string to filter comps
                (e.g. "Single Family Residential", "Condo/Co-op").
                Ensures condo comps are compared to other condos, etc.

        Returns:
            List of ComparableProperty sorted by similarity score.
        """
        cutoff = date.today() - timedelta(days=lookback_months * 30)

        # Build flexible query with wider net, then score
        query = """
            SELECT
                address, sale_date, sale_price, beds, baths, sqft,
                lot_size_sqft, year_built, neighborhood, price_per_sqft,
                latitude, longitude
            FROM property_sales
            WHERE neighborhood = ?
              AND sale_date >= ?
              AND sale_price IS NOT NULL
        """
        params: list = [neighborhood, cutoff.isoformat()]

        # Filter by property type for better comps (SFR vs condo vs multi-family)
        if property_type:
            query += " AND property_type = ?"
            params.append(property_type)

        # Add soft filters (wider range, we'll score later)
        if beds is not None:
            query += " AND beds BETWEEN ? AND ?"
            params.extend([beds - 1, beds + 1])

        if baths is not None:
            query += " AND baths BETWEEN ? AND ?"
            params.extend([baths - 1, baths + 1])

        if sqft is not None:
            query += " AND sqft BETWEEN ? AND ?"
            params.extend([int(sqft * 0.7), int(sqft * 1.3)])

        query += " ORDER BY sale_date DESC LIMIT 50"

        rows = self.db.execute(query, params).fetchall()

        # Fallback: if property_type filter yielded too few results, retry without it
        if property_type and len(rows) < 3:
            logger.info(
                "Only %d comps with property_type=%s, retrying without filter",
                len(rows), property_type,
            )
            fallback_query = """
                SELECT
                    address, sale_date, sale_price, beds, baths, sqft,
                    lot_size_sqft, year_built, neighborhood, price_per_sqft,
                    latitude, longitude
                FROM property_sales
                WHERE neighborhood = ?
                  AND sale_date >= ?
                  AND sale_price IS NOT NULL
            """
            fb_params: list = [neighborhood, cutoff.isoformat()]
            if beds is not None:
                fallback_query += " AND beds BETWEEN ? AND ?"
                fb_params.extend([beds - 1, beds + 1])
            if baths is not None:
                fallback_query += " AND baths BETWEEN ? AND ?"
                fb_params.extend([baths - 1, baths + 1])
            if sqft is not None:
                fallback_query += " AND sqft BETWEEN ? AND ?"
                fb_params.extend([int(sqft * 0.7), int(sqft * 1.3)])
            fallback_query += " ORDER BY sale_date DESC LIMIT 50"
            rows = self.db.execute(fallback_query, fb_params).fetchall()

        # Score comparables by similarity
        comps = []
        for row in rows:
            score = self._similarity_score(
                row, beds=beds, baths=baths, sqft=sqft, year_built=year_built
            )
            comps.append(
                ComparableProperty(
                    address=row["address"],
                    sale_date=date.fromisoformat(row["sale_date"]),
                    sale_price=row["sale_price"],
                    beds=row["beds"],
                    baths=row["baths"],
                    sqft=row["sqft"],
                    lot_size_sqft=row["lot_size_sqft"],
                    year_built=row["year_built"],
                    neighborhood=row["neighborhood"],
                    price_per_sqft=row["price_per_sqft"],
                    similarity_score=score,
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                )
            )

        # Sort by similarity (lower is more similar)
        comps.sort(key=lambda c: c.similarity_score)
        return comps[:max_results]

    def estimate_price(
        self,
        neighborhood: str,
        beds: Optional[float] = None,
        baths: Optional[float] = None,
        sqft: Optional[int] = None,
        year_built: Optional[int] = None,
        lot_size_sqft: Optional[int] = None,
        lookback_months: int = 24,
    ) -> PriceEstimate:
        """Estimate realistic sale price for a hypothetical property.

        Uses comparable sales analysis adjusted for current market conditions.

        Args:
            neighborhood: Target neighborhood.
            beds: Bedrooms.
            baths: Bathrooms.
            sqft: Square footage.
            year_built: Year built.
            lot_size_sqft: Lot size in sqft.
            lookback_months: How far back for comparables.

        Returns:
            PriceEstimate with price range, comparables, and methodology.
        """
        notes: list[str] = []

        # Step 1: Find comparables
        comps = self.find_comparables(
            neighborhood=neighborhood,
            beds=beds,
            baths=baths,
            sqft=sqft,
            year_built=year_built,
            lookback_months=lookback_months,
            max_results=15,
        )

        if len(comps) < 3:
            # Widen search to adjacent neighborhoods
            notes.append(
                f"Only {len(comps)} comps in {neighborhood}; "
                f"expanding to nearby neighborhoods."
            )
            wider_comps = self._find_wider_comps(
                neighborhood, beds, baths, sqft, year_built, lookback_months
            )
            comps.extend(wider_comps)

        if not comps:
            return PriceEstimate(
                estimated_price=0,
                confidence="low",
                price_range_low=0,
                price_range_high=0,
                comparable_count=0,
                methodology_notes=["No comparable sales found."],
            )

        # Step 2: Calculate base price from comps
        prices = [c.sale_price for c in comps[:10]]
        prices.sort()

        # Use trimmed mean (remove top and bottom) for robustness
        if len(prices) >= 5:
            trimmed = prices[1:-1]
            notes.append(
                f"Using trimmed mean of {len(trimmed)} comps "
                f"(removed lowest and highest)."
            )
        else:
            trimmed = prices

        base_price = int(sum(trimmed) / len(trimmed))

        # Step 3: Adjust for sqft difference if we have data
        if sqft and comps[0].sqft:
            avg_comp_sqft = sum(c.sqft for c in comps[:5] if c.sqft) / max(
                1, sum(1 for c in comps[:5] if c.sqft)
            )
            avg_comp_ppsf = sum(c.price_per_sqft for c in comps[:5] if c.price_per_sqft) / max(
                1, sum(1 for c in comps[:5] if c.price_per_sqft)
            )
            if avg_comp_sqft > 0 and avg_comp_ppsf > 0:
                sqft_diff = sqft - avg_comp_sqft
                sqft_adjustment = int(sqft_diff * avg_comp_ppsf * 0.8)
                base_price += sqft_adjustment
                if abs(sqft_adjustment) > 10000:
                    notes.append(
                        f"Sqft adjustment: {sqft_diff:+.0f} sqft × "
                        f"${avg_comp_ppsf:.0f}/sqft = ${sqft_adjustment:+,}"
                    )

        # Step 4: Market trend adjustment
        market = self.get_current_market_conditions()
        market_adj_pct = None
        if market.sale_to_list_ratio:
            market_adj_pct = (market.sale_to_list_ratio - 1.0) * 100
            notes.append(
                f"Current market: homes selling at "
                f"{market.sale_to_list_ratio:.1%} of list price "
                f"({market.sold_above_list_pct:.0f}% sell above list)."
            )

        # Step 5: Determine confidence and range
        if len(comps) >= 8:
            confidence = "high"
            range_pct = 0.07  # ±7%
        elif len(comps) >= 4:
            confidence = "medium"
            range_pct = 0.12  # ±12%
        else:
            confidence = "low"
            range_pct = 0.18  # ±18%

        notes.append(
            f"Confidence: {confidence} (based on {len(comps)} comparables)."
        )

        price_low = int(base_price * (1 - range_pct))
        price_high = int(base_price * (1 + range_pct))

        return PriceEstimate(
            estimated_price=base_price,
            confidence=confidence,
            price_range_low=price_low,
            price_range_high=price_high,
            comparable_count=len(comps),
            comparables=comps[:10],
            methodology_notes=notes,
            market_adjustment_pct=market_adj_pct,
            sale_to_list_ratio=market.sale_to_list_ratio,
        )

    # -------------------------------------------------------------------
    # Sale-to-list analysis (key for the user's problem)
    # -------------------------------------------------------------------

    def get_sale_to_list_by_neighborhood(
        self,
        months: int = 12,
    ) -> list[dict]:
        """How much above list price do homes sell in each neighborhood?

        This is the core metric for the user's problem: understanding
        how much above (or below) list price homes actually sell for.

        Args:
            months: Lookback period.

        Returns:
            List of dicts with neighborhood, avg_sale_to_list, count.
        """
        cutoff = date.today() - timedelta(days=months * 30)

        # Use market_metrics data for city-wide
        city_row = self.db.execute(
            """
            SELECT
                AVG(avg_sale_to_list) as avg_ratio,
                AVG(sold_above_list_pct) as avg_above_pct
            FROM market_metrics
            WHERE period_begin >= ?
              AND property_type = 'All Residential'
              AND avg_sale_to_list IS NOT NULL
            """,
            (cutoff.isoformat(),),
        ).fetchone()

        city_ratio = city_row["avg_ratio"] if city_row else None
        city_above_pct = city_row["avg_above_pct"] if city_row else None

        results = []
        if city_ratio:
            results.append(
                {
                    "neighborhood": "ALL BERKELEY (city-wide)",
                    "avg_sale_to_list_ratio": round(city_ratio, 4),
                    "pct_above_list": round(city_above_pct * 100, 1) if city_above_pct else None,
                    "sale_count": None,
                    "note": "From Redfin aggregated market data",
                }
            )

        return results

    def get_price_trends_by_neighborhood(
        self,
        neighborhoods: Optional[list[str]] = None,
        lookback_years: int = 3,
    ) -> dict[str, list[dict]]:
        """Get quarterly price trends for specified neighborhoods.

        Args:
            neighborhoods: List of neighborhood names (or None for top 10).
            lookback_years: Years to look back.

        Returns:
            Dict of neighborhood name → list of {quarter, median_price, count}.
        """
        cutoff = date.today() - timedelta(days=lookback_years * 365)

        if neighborhoods is None:
            # Get top 10 by sale count
            top = self.db.execute(
                """
                SELECT neighborhood, COUNT(*) as cnt
                FROM property_sales
                WHERE neighborhood IS NOT NULL AND sale_date >= ?
                GROUP BY neighborhood
                ORDER BY cnt DESC
                LIMIT 10
                """,
                (cutoff.isoformat(),),
            ).fetchall()
            neighborhoods = [r["neighborhood"] for r in top]

        result = {}
        for hood in neighborhoods:
            quarters = self.db.execute(
                """
                SELECT
                    SUBSTR(sale_date, 1, 4) || '-Q' ||
                    CASE
                        WHEN CAST(SUBSTR(sale_date, 6, 2) AS INTEGER) <= 3 THEN '1'
                        WHEN CAST(SUBSTR(sale_date, 6, 2) AS INTEGER) <= 6 THEN '2'
                        WHEN CAST(SUBSTR(sale_date, 6, 2) AS INTEGER) <= 9 THEN '3'
                        ELSE '4'
                    END as quarter,
                    COUNT(*) as count,
                    CAST(AVG(sale_price) AS INTEGER) as avg_price
                FROM property_sales
                WHERE neighborhood = ? AND sale_date >= ? AND sale_price IS NOT NULL
                GROUP BY quarter
                ORDER BY quarter
                """,
                (hood, cutoff.isoformat()),
            ).fetchall()

            # Calculate median per quarter using a subquery approach
            quarterly_data = []
            for q in quarters:
                quarterly_data.append(
                    {
                        "quarter": q["quarter"],
                        "avg_price": q["avg_price"],
                        "count": q["count"],
                    }
                )

            result[hood] = quarterly_data

        return result

    # -------------------------------------------------------------------
    # Affordability analysis
    # -------------------------------------------------------------------

    def assess_affordability(
        self,
        monthly_budget: int,
        down_payment_pct: float = 20.0,
        property_tax_rate: float = 1.17,
        insurance_annual: int = 2400,
        hoa_monthly: int = 0,
    ) -> dict:
        """Determine what price range is affordable.

        Args:
            monthly_budget: Maximum monthly housing payment (PITI).
            down_payment_pct: Down payment as percentage.
            property_tax_rate: Annual property tax rate (%).
            insurance_annual: Annual homeowner's insurance.
            hoa_monthly: Monthly HOA dues.

        Returns:
            Dict with affordable price range and neighborhood options.
        """
        # Get current mortgage rate
        rate_row = self.db.execute(
            """
            SELECT rate_30yr FROM mortgage_rates
            WHERE rate_30yr IS NOT NULL
            ORDER BY observation_date DESC LIMIT 1
            """
        ).fetchone()

        rate_30yr = rate_row["rate_30yr"] if rate_row else 6.5
        monthly_rate = (rate_30yr / 100) / 12
        n_payments = 360  # 30 years

        # Subtract fixed costs from budget
        monthly_insurance = insurance_annual / 12
        available_for_pi = (
            monthly_budget - monthly_insurance - hoa_monthly
        )

        # Work backwards: available_for_pi = PI + property tax
        # PI = P * [r(1+r)^n] / [(1+r)^n - 1]
        # Property tax = (home_price * tax_rate / 100) / 12

        # Iterative solve for home price
        max_price = 0
        for price in range(100_000, 5_000_001, 10_000):
            loan_amount = price * (1 - down_payment_pct / 100)

            # Monthly P&I
            if monthly_rate > 0:
                pi = loan_amount * (
                    monthly_rate * (1 + monthly_rate) ** n_payments
                ) / ((1 + monthly_rate) ** n_payments - 1)
            else:
                pi = loan_amount / n_payments

            monthly_tax = (price * property_tax_rate / 100) / 12
            total_monthly = pi + monthly_tax + monthly_insurance + hoa_monthly

            if total_monthly <= monthly_budget:
                max_price = price
            else:
                break

        # Check jumbo loan threshold
        jumbo_threshold = 766_550  # 2024 conforming loan limit for Alameda County
        loan_at_max = max_price * (1 - down_payment_pct / 100)
        is_jumbo = loan_at_max > jumbo_threshold

        # Find affordable neighborhoods
        two_years_ago = Database.date_cutoff(years=2)
        affordable_neighborhoods = self.db.execute(
            """
            SELECT
                neighborhood,
                COUNT(*) as recent_sales,
                CAST(AVG(sale_price) AS INTEGER) as avg_price,
                MIN(sale_price) as min_price
            FROM property_sales
            WHERE neighborhood IS NOT NULL
              AND sale_price <= ?
              AND sale_date >= ?
            GROUP BY neighborhood
            HAVING COUNT(*) >= 3
            ORDER BY avg_price
            """,
            (max_price, two_years_ago),
        ).fetchall()

        # Enrich each neighborhood with property type and zoning breakdown
        enriched = []
        for r in affordable_neighborhoods:
            hood = r["neighborhood"]
            ptypes = self.db.execute(
                """
                SELECT property_type, COUNT(*) as cnt FROM property_sales
                WHERE neighborhood = ? AND sale_price <= ?
                  AND sale_date >= ?
                  AND property_type IS NOT NULL
                GROUP BY property_type ORDER BY cnt DESC
                """,
                (hood, max_price, two_years_ago),
            ).fetchall()
            pt_total = sum(p["cnt"] for p in ptypes)
            pt_breakdown = {
                p["property_type"]: round(p["cnt"] / pt_total * 100, 1)
                for p in ptypes
            } if pt_total > 0 else {}

            zones = self.db.execute(
                """
                SELECT zoning_class, COUNT(*) as cnt FROM property_sales
                WHERE neighborhood = ? AND sale_price <= ?
                  AND sale_date >= ?
                  AND zoning_class IS NOT NULL
                GROUP BY zoning_class ORDER BY cnt DESC LIMIT 2
                """,
                (hood, max_price, two_years_ago),
            ).fetchall()

            enriched.append({
                "name": hood,
                "recent_sales_in_range": r["recent_sales"],
                "avg_price": r["avg_price"],
                "lowest_recent_sale": r["min_price"],
                "property_type_breakdown": pt_breakdown,
                "dominant_zoning": [z["zoning_class"] for z in zones],
            })

        return {
            "monthly_budget": monthly_budget,
            "mortgage_rate_30yr": rate_30yr,
            "max_affordable_price": max_price,
            "down_payment_amount": int(max_price * down_payment_pct / 100),
            "loan_amount": int(loan_at_max),
            "is_jumbo_loan": is_jumbo,
            "jumbo_threshold": jumbo_threshold,
            "affordable_neighborhoods": enriched,
        }

    # -------------------------------------------------------------------
    # Summary report
    # -------------------------------------------------------------------

    def generate_summary_report(self) -> dict:
        """Generate a comprehensive market summary.

        Returns:
            Dict with all key metrics for Berkeley home buying.
        """
        # Current market conditions
        market = self.get_current_market_conditions()

        # Overall stats
        total_sales = self.db.fetchval(
            "SELECT COUNT(*) FROM property_sales WHERE sale_price IS NOT NULL"
        )

        date_range = self.db.fetchone(
            "SELECT MIN(sale_date) AS min_date, MAX(sale_date) AS max_date FROM property_sales"
        )

        # Neighborhood rankings
        rankings = self.get_all_neighborhood_rankings(lookback_years=2, min_sales=10)

        # Price distribution
        two_yr_cutoff = Database.date_cutoff(years=2)
        price_dist = self.db.execute(
            """
            SELECT
                CASE
                    WHEN sale_price < 500000 THEN 'Under $500K'
                    WHEN sale_price < 750000 THEN '$500K-$750K'
                    WHEN sale_price < 1000000 THEN '$750K-$1M'
                    WHEN sale_price < 1250000 THEN '$1M-$1.25M'
                    WHEN sale_price < 1500000 THEN '$1.25M-$1.5M'
                    WHEN sale_price < 2000000 THEN '$1.5M-$2M'
                    WHEN sale_price < 3000000 THEN '$2M-$3M'
                    ELSE '$3M+'
                END as price_bracket,
                COUNT(*) as count
            FROM property_sales
            WHERE sale_price IS NOT NULL AND sale_date >= ?
            GROUP BY price_bracket
            ORDER BY MIN(sale_price)
            """,
            (two_yr_cutoff,),
        ).fetchall()

        return {
            "data_coverage": {
                "total_sales": total_sales,
                "date_range": {
                    "earliest": date_range["min_date"] if date_range else None,
                    "latest": date_range["max_date"] if date_range else None,
                },
                "neighborhoods_covered": len(rankings),
            },
            "current_market": {
                "period": market.period,
                "median_sale_price": market.median_sale_price,
                "median_list_price": market.median_list_price,
                "sale_to_list_ratio": market.sale_to_list_ratio,
                "sold_above_list_pct": market.sold_above_list_pct,
                "homes_sold_monthly": market.homes_sold,
                "median_days_on_market": market.median_dom,
                "mortgage_rate_30yr": market.mortgage_rate_30yr,
                "price_note": self._format_price_note(
                    market.median_sale_price,
                    market.median_list_price,
                ),
                "sale_to_list_note": self._format_sale_to_list_note(
                    market.sale_to_list_ratio,
                    market.sold_above_list_pct,
                ),
            },
            "price_distribution_2yr": [
                {"bracket": r["price_bracket"], "count": r["count"]}
                for r in price_dist
            ],
            "top_neighborhoods_by_price": [
                {
                    "name": s.name,
                    "median_price": s.median_price,
                    "avg_ppsf": s.avg_ppsf,
                    "sales": s.sale_count,
                    "yoy_change": s.yoy_price_change_pct,
                }
                for s in rankings[:15]
            ],
            "property_type_prices": self._get_property_type_prices(),
            "zoning_price_insights": self._get_zoning_price_insights(),
        }

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _format_price_note(
        median_sale: Optional[float], median_list: Optional[float]
    ) -> Optional[str]:
        """Human-readable note comparing sale vs list prices."""
        if median_sale is None or median_list is None or median_list == 0:
            return None
        if median_sale > median_list:
            pct = (median_sale - median_list) / median_list * 100
            return (
                f"Homes are selling above asking: median sale price "
                f"is {pct:.0f}% above median list price"
            )
        if median_sale < median_list:
            pct = (median_list - median_sale) / median_list * 100
            return (
                f"Homes are selling below asking: median sale price "
                f"is {pct:.0f}% below median list price"
            )
        return "Homes are selling at asking price on average"

    @staticmethod
    def _format_sale_to_list_note(
        ratio: Optional[float], sold_above_pct: Optional[float]
    ) -> Optional[str]:
        """Human-readable note for sale-to-list ratio and sold-above-list %.

        ``sale_to_list_ratio`` is a multiplier (e.g. 1.05 means 5% above list).
        ``sold_above_list_pct`` is already 0–100 (e.g. 87 means 87% of homes
        sold above their list price).  Pre-computing a plain-English note
        prevents the LLM from confusing the two or mis-converting the ratio.
        """
        parts: list[str] = []
        if ratio is not None:
            above = ratio >= 1.0
            pct = abs(ratio - 1.0) * 100
            if pct < 0.05:
                parts.append("sale-to-list ratio is ~1.0 (homes sell at asking)")
            elif above:
                parts.append(
                    f"sale-to-list ratio is {ratio:.3f} "
                    f"(homes sell {pct:.1f}% above asking on average)"
                )
            else:
                parts.append(
                    f"sale-to-list ratio is {ratio:.3f} "
                    f"(homes sell {pct:.1f}% below asking on average)"
                )
        if sold_above_pct is not None:
            parts.append(
                f"{sold_above_pct:.0f}% of homes sold above their list price"
            )
        return "; ".join(parts) if parts else None

    def _calc_yoy_change(self, neighborhood: str) -> Optional[float]:
        """Calculate year-over-year median price change for a neighborhood."""
        today = date.today()
        one_year_ago = today - timedelta(days=365)
        two_years_ago = today - timedelta(days=730)

        current = self.db.execute(
            """
            SELECT AVG(sale_price) as avg FROM property_sales
            WHERE neighborhood = ? AND sale_date >= ? AND sale_price IS NOT NULL
            """,
            (neighborhood, one_year_ago.isoformat()),
        ).fetchone()

        previous = self.db.execute(
            """
            SELECT AVG(sale_price) as avg FROM property_sales
            WHERE neighborhood = ?
              AND sale_date >= ? AND sale_date < ?
              AND sale_price IS NOT NULL
            """,
            (neighborhood, two_years_ago.isoformat(), one_year_ago.isoformat()),
        ).fetchone()

        if (
            current
            and previous
            and current["avg"]
            and previous["avg"]
            and previous["avg"] > 0
        ):
            return round(
                (current["avg"] - previous["avg"]) / previous["avg"] * 100, 1
            )
        return None

    def _enrich_neighborhood_stats(
        self, stats: NeighborhoodStats, lookback_years: int
    ) -> None:
        """Enrich stats with property type breakdown, lot size, and zoning."""
        cutoff = (date.today() - timedelta(days=lookback_years * 365)).isoformat()

        # Median lot size
        lot_rows = self.db.execute(
            """
            SELECT lot_size_sqft FROM property_sales
            WHERE neighborhood = ? AND sale_date >= ?
              AND lot_size_sqft IS NOT NULL AND lot_size_sqft > 0
            ORDER BY lot_size_sqft
            """,
            (stats.name, cutoff),
        ).fetchall()
        if lot_rows:
            mid = len(lot_rows) // 2
            stats.median_lot_size = lot_rows[mid]["lot_size_sqft"]

        # Property type breakdown
        type_rows = self.db.execute(
            """
            SELECT property_type, COUNT(*) as cnt
            FROM property_sales
            WHERE neighborhood = ? AND sale_date >= ?
              AND property_type IS NOT NULL AND sale_price IS NOT NULL
            GROUP BY property_type ORDER BY cnt DESC
            """,
            (stats.name, cutoff),
        ).fetchall()
        total = sum(r["cnt"] for r in type_rows)
        if total > 0:
            stats.property_type_breakdown = {
                r["property_type"]: round(r["cnt"] / total * 100, 1)
                for r in type_rows
            }

        # Zoning breakdown and dominant zoning
        zone_rows = self.db.execute(
            """
            SELECT zoning_class, COUNT(*) as cnt
            FROM property_sales
            WHERE neighborhood = ? AND sale_date >= ?
              AND zoning_class IS NOT NULL AND sale_price IS NOT NULL
            GROUP BY zoning_class ORDER BY cnt DESC
            """,
            (stats.name, cutoff),
        ).fetchall()
        zone_total = sum(r["cnt"] for r in zone_rows)
        if zone_total > 0:
            stats.zoning_breakdown = {
                r["zoning_class"]: round(r["cnt"] / zone_total * 100, 1)
                for r in zone_rows
            }
            cumulative = 0.0
            dominant: list[str] = []
            for r in zone_rows:
                dominant.append(r["zoning_class"])
                cumulative += r["cnt"] / zone_total * 100
                if cumulative >= 70 or len(dominant) >= 2:
                    break
            stats.dominant_zoning = dominant

    def _get_property_type_prices(self) -> list[dict]:
        """Average sale price by property type (last 2 years, min 5 sales)."""
        cutoff = Database.date_cutoff(years=2)
        rows = self.db.execute(
            """
            SELECT property_type, COUNT(*) as cnt,
                   CAST(AVG(sale_price) AS INTEGER) as avg_price
            FROM property_sales
            WHERE property_type IS NOT NULL AND sale_price IS NOT NULL
              AND sale_date >= ?
            GROUP BY property_type HAVING COUNT(*) >= 5
            ORDER BY avg_price DESC
            """,
            (cutoff,),
        ).fetchall()
        return [
            {"type": r["property_type"], "count": r["cnt"], "avg_price": r["avg_price"]}
            for r in rows
        ]

    def _get_zoning_price_insights(self) -> list[dict]:
        """Average price and $/sqft grouped by zone category (last 2 years)."""
        cutoff = Database.date_cutoff(years=2)
        rows = self.db.execute(
            """
            SELECT
                CASE
                    WHEN zoning_class LIKE 'R-1%' THEN 'R-1 (Single Family)'
                    WHEN zoning_class LIKE 'R-2%' THEN 'R-2 (Two-Family)'
                    WHEN zoning_class LIKE 'R-3%' THEN 'R-3 (Multiple Family)'
                    WHEN zoning_class LIKE 'R-4%' THEN 'R-4 (Multi-Family)'
                    WHEN zoning_class IN ('R-S', 'R-SMU', 'R-BMU') THEN 'R-S/Mixed (Special)'
                    WHEN zoning_class LIKE 'ES-R%' THEN 'ES-R (Hillside)'
                    WHEN zoning_class LIKE 'MUR%' OR zoning_class LIKE 'MRD%'
                        THEN 'Mixed-Use Residential'
                    ELSE 'Other'
                END as zone_category,
                COUNT(*) as cnt,
                CAST(AVG(sale_price) AS INTEGER) as avg_price,
                AVG(price_per_sqft) as avg_ppsf
            FROM property_sales
            WHERE zoning_class IS NOT NULL AND sale_price IS NOT NULL
              AND sale_date >= ?
            GROUP BY zone_category HAVING COUNT(*) >= 3
            ORDER BY avg_price DESC
            """,
            (cutoff,),
        ).fetchall()
        return [
            {
                "zone_category": r["zone_category"],
                "count": r["cnt"],
                "avg_price": r["avg_price"],
                "avg_ppsf": round(r["avg_ppsf"], 2) if r["avg_ppsf"] else None,
            }
            for r in rows
        ]

    def get_data_completeness(self) -> dict[str, dict]:
        """Return fill-rate stats for key API-enriched columns."""
        total = self.db.fetchval(
            "SELECT COUNT(*) FROM property_sales WHERE sale_price IS NOT NULL"
        )
        if total == 0:
            return {}

        columns = [
            ("property_type", "Property Type"),
            ("year_built", "Year Built"),
            ("sqft", "Square Footage"),
            ("lot_size_sqft", "Lot Size"),
            ("beds", "Bedrooms"),
            ("baths", "Bathrooms"),
            ("zoning_class", "Zoning Class"),
            ("hoa_per_month", "HOA"),
        ]
        result = {}
        for col, label in columns:
            filled = self.db.fetchval(
                f"SELECT COUNT(*) FROM property_sales WHERE {col} IS NOT NULL AND sale_price IS NOT NULL",  # noqa: S608
            )
            result[col] = {
                "label": label,
                "filled": filled,
                "total": total,
                "pct": round(filled / total * 100, 1),
            }
        return result

    def _get_mortgage_rate_for_date(self, date_str: str) -> Optional[float]:
        """Find the closest mortgage rate to a given date."""
        row = self.db.execute(
            """
            SELECT rate_30yr FROM mortgage_rates
            WHERE observation_date <= ? AND rate_30yr IS NOT NULL
            ORDER BY observation_date DESC LIMIT 1
            """,
            (date_str,),
        ).fetchone()
        return row["rate_30yr"] if row else None

    def _similarity_score(
        self,
        row: dict,
        beds: Optional[float] = None,
        baths: Optional[float] = None,
        sqft: Optional[int] = None,
        year_built: Optional[int] = None,
    ) -> float:
        """Calculate a similarity score (lower = more similar).

        Weighted distance across multiple dimensions.
        """
        score = 0.0

        if beds is not None and row["beds"] is not None:
            score += abs(beds - row["beds"]) * 0.3

        if baths is not None and row["baths"] is not None:
            score += abs(baths - row["baths"]) * 0.2

        if sqft is not None and row["sqft"] is not None and sqft > 0:
            sqft_diff_pct = abs(sqft - row["sqft"]) / sqft
            score += sqft_diff_pct * 0.35

        if year_built is not None and row["year_built"] is not None:
            year_diff = abs(year_built - row["year_built"])
            score += min(year_diff / 30.0, 1.0) * 0.15

        # Recency bonus: more recent sales get a small boost
        if row["sale_date"]:
            days_ago = (date.today() - date.fromisoformat(row["sale_date"])).days
            recency_penalty = min(days_ago / 730, 1.0) * 0.1
            score += recency_penalty

        return round(score, 4)

    def _find_wider_comps(
        self,
        neighborhood: str,
        beds: Optional[float],
        baths: Optional[float],
        sqft: Optional[int],
        year_built: Optional[int],
        lookback_months: int,
    ) -> list[ComparableProperty]:
        """Find comparables from nearby/similar neighborhoods."""
        cutoff = date.today() - timedelta(days=lookback_months * 30)

        # Get neighborhoods with similar price levels
        hood_stats = self.get_neighborhood_stats(neighborhood)
        if not hood_stats.median_price:
            return []

        price_low = int(hood_stats.median_price * 0.7)
        price_high = int(hood_stats.median_price * 1.3)

        query = """
            SELECT
                address, sale_date, sale_price, beds, baths, sqft,
                lot_size_sqft, year_built, neighborhood, price_per_sqft,
                latitude, longitude
            FROM property_sales
            WHERE neighborhood != ?
              AND neighborhood IS NOT NULL
              AND sale_date >= ?
              AND sale_price BETWEEN ? AND ?
        """
        params: list = [neighborhood, cutoff.isoformat(), price_low, price_high]

        if beds is not None:
            query += " AND beds BETWEEN ? AND ?"
            params.extend([beds - 1, beds + 1])

        if sqft is not None:
            query += " AND sqft BETWEEN ? AND ?"
            params.extend([int(sqft * 0.75), int(sqft * 1.25)])

        query += " ORDER BY sale_date DESC LIMIT 10"

        rows = self.db.execute(query, params).fetchall()

        comps = []
        for row in rows:
            score = self._similarity_score(row, beds, baths, sqft, year_built)
            # Add penalty for different neighborhood
            score += 0.2
            comps.append(
                ComparableProperty(
                    address=row["address"],
                    sale_date=date.fromisoformat(row["sale_date"]),
                    sale_price=row["sale_price"],
                    beds=row["beds"],
                    baths=row["baths"],
                    sqft=row["sqft"],
                    lot_size_sqft=row["lot_size_sqft"],
                    year_built=row["year_built"],
                    neighborhood=row["neighborhood"],
                    price_per_sqft=row["price_per_sqft"],
                    similarity_score=score,
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                )
            )

        return comps
