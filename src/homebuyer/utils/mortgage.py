"""Shared mortgage calculation utilities."""


def get_current_mortgage_rate(db) -> float:
    """Get the latest 30-year mortgage rate from the database. Returns rate as percentage."""
    row = db.fetchone(
        """SELECT rate_30yr FROM mortgage_rates
           WHERE rate_30yr IS NOT NULL
           ORDER BY observation_date DESC LIMIT 1"""
    )
    return row["rate_30yr"] if row else 6.5  # reasonable default


def calc_monthly_payment(principal: float, annual_rate_pct: float, n_payments: int = 360) -> float:
    """Calculate monthly mortgage payment using standard amortization formula.

    Args:
        principal: Loan amount
        annual_rate_pct: Annual interest rate as percentage (e.g. 6.5 for 6.5%)
        n_payments: Total number of monthly payments (default 360 for 30-year)
    """
    if principal <= 0 or annual_rate_pct <= 0:
        return 0.0
    monthly_rate = (annual_rate_pct / 100) / 12
    return principal * (monthly_rate * (1 + monthly_rate) ** n_payments) / (
        (1 + monthly_rate) ** n_payments - 1
    )
