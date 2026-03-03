"""Reusable SQL query builders for common data access patterns."""

from datetime import date
from typing import Optional


def sales_by_neighborhood(
    neighborhood: Optional[str] = None,
    min_date: Optional[date] = None,
    max_date: Optional[date] = None,
) -> tuple[str, list]:
    """Build a query for sales filtered by neighborhood and date range."""
    clauses = []
    params: list = []

    if neighborhood:
        clauses.append("neighborhood = ?")
        params.append(neighborhood)
    if min_date:
        clauses.append("sale_date >= ?")
        params.append(min_date.isoformat())
    if max_date:
        clauses.append("sale_date <= ?")
        params.append(max_date.isoformat())

    where = " AND ".join(clauses) if clauses else "1=1"
    sql = f"""
        SELECT * FROM property_sales
        WHERE {where}
        ORDER BY sale_date DESC
    """
    return sql, params


def neighborhood_summary(min_date: Optional[date] = None) -> tuple[str, list]:
    """Build a query for per-neighborhood aggregated statistics."""
    params: list = []
    where = ""
    if min_date:
        where = "WHERE sale_date >= ?"
        params.append(min_date.isoformat())

    sql = f"""
        SELECT
            neighborhood,
            COUNT(*) as sale_count,
            ROUND(AVG(sale_price)) as avg_price,
            ROUND(AVG(price_per_sqft), 2) as avg_ppsf,
            MIN(sale_price) as min_price,
            MAX(sale_price) as max_price,
            ROUND(AVG(sqft)) as avg_sqft,
            ROUND(AVG(beds), 1) as avg_beds,
            ROUND(AVG(baths), 1) as avg_baths,
            MIN(sale_date) as earliest_sale,
            MAX(sale_date) as latest_sale
        FROM property_sales
        {where}
        GROUP BY neighborhood
        ORDER BY avg_price DESC
    """
    return sql, params


def price_trends_by_quarter(neighborhood: Optional[str] = None) -> tuple[str, list]:
    """Build a query for quarterly price trends."""
    params: list = []
    where = ""
    if neighborhood:
        where = "AND neighborhood = ?"
        params.append(neighborhood)

    sql = f"""
        SELECT
            SUBSTR(sale_date, 1, 4) || '-Q' ||
                CASE
                    WHEN CAST(SUBSTR(sale_date, 6, 2) AS INTEGER) <= 3 THEN '1'
                    WHEN CAST(SUBSTR(sale_date, 6, 2) AS INTEGER) <= 6 THEN '2'
                    WHEN CAST(SUBSTR(sale_date, 6, 2) AS INTEGER) <= 9 THEN '3'
                    ELSE '4'
                END as quarter,
            COUNT(*) as sale_count,
            ROUND(AVG(sale_price)) as avg_price,
            ROUND(AVG(price_per_sqft), 2) as avg_ppsf
        FROM property_sales
        WHERE sale_price > 0 {where}
        GROUP BY quarter
        ORDER BY quarter
    """
    return sql, params
