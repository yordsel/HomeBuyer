"""True monthly ownership cost calculator.

Computes the all-in monthly cost of owning a Berkeley property:
  P&I + property tax + hazard insurance + earthquake insurance +
  maintenance reserve + PMI (if applicable) + HOA

Optionally compares to the buyer's current rent.

All computation is pure — no DB access, no I/O. The executor in api.py
resolves mortgage rates from the database before calling this module.

Note: The property tax rate here (1.18%) differs slightly from
rental_analysis.py (1.17%). This module uses the owner-occupier effective
rate including Berkeley's parcel tax assessments; the rental module uses
the investor rate. Both are reasonable approximations of the actual
Alameda County + City of Berkeley combined rate.

Phase F-1 (#54) of Epic #23.
"""

from __future__ import annotations

import datetime

import math
from dataclasses import dataclass

from homebuyer.utils.mortgage import calc_monthly_payment

# ---------------------------------------------------------------------------
# Berkeley-specific constants
# ---------------------------------------------------------------------------

# Effective property tax rate (base 1% + Alameda County + Berkeley specials)
PROPERTY_TAX_RATE = 0.0118  # 1.18% annual

# Hazard / homeowner's insurance (HOI)
_HOI_RATE = 0.0035  # 0.35% of value annually

# Earthquake insurance rates by construction type (annual % of dwelling coverage)
# Dwelling coverage ≈ purchase_price × _EQ_DWELLING_COVERAGE_RATIO (land excluded)
_EQ_RATES: dict[str, float] = {
    "wood_frame": 0.0025,   # ~0.25% — most Berkeley SFH
    "masonry": 0.0060,      # ~0.60% — higher risk
    "soft_story": 0.0080,   # ~0.80% — worst risk class
    "concrete": 0.0040,     # ~0.40%
}
_EQ_DWELLING_COVERAGE_RATIO = 0.80  # land excluded from dwelling coverage

# PMI (private mortgage insurance) — uses tiered rates consistent with pmi_model.py
_PMI_LTV_THRESHOLD = 0.80   # PMI required when LTV > 80%
# Tiered rate table: (ltv_min_exclusive, ltv_max_inclusive, annual_rate)
_PMI_RATE_TABLE: list[tuple[float, float, float]] = [
    (0.850, 0.950, 0.0110),  # 85.01–95% LTV: 1.10%
    (0.800, 0.850, 0.0075),  # 80.01–85% LTV: 0.75%
]

# Maintenance reserve — age brackets (max_age, annual rate)
_MAINTENANCE_RATES: list[tuple[int, float]] = [
    (10, 0.0075),    # < 10 years old: 0.75%
    (20, 0.0100),    # 10–19 years: 1.0%
    (40, 0.0125),    # 20–39 years: 1.25%
    (9999, 0.0150),  # 40+ years: 1.5%
]
_MAINTENANCE_DEFAULT = 0.0100  # when year_built is unknown

_LOAN_TERM_MONTHS = 360  # 30-year fixed


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class TrueCostParams:
    """All inputs for the true cost computation.

    The executor resolves mortgage_rate from the DB before constructing this.
    """

    purchase_price: int
    down_payment_pct: float = 20.0      # percent (e.g., 20.0 = 20%)
    mortgage_rate: float = 6.5          # annual rate as percent (e.g., 7.25)
    year_built: int | None = None
    construction_type: str = "wood_frame"
    hoa_monthly: int = 0
    current_rent: int | None = None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _calc_monthly_pi(loan_amount: int, annual_rate_pct: float) -> int:
    """Monthly principal & interest payment."""
    if loan_amount <= 0:
        return 0
    return int(math.ceil(calc_monthly_payment(loan_amount, annual_rate_pct, _LOAN_TERM_MONTHS)))


def _pmi_rate_for_ltv(ltv: float) -> float:
    """Return annual PMI rate for a given LTV, using tiered table."""
    for ltv_min, ltv_max, rate in _PMI_RATE_TABLE:
        if ltv_min < ltv <= ltv_max:
            return rate
    return 0.0


def _calc_monthly_pmi(loan_amount: int, purchase_price: int) -> int:
    """Monthly PMI cost using tiered rates. Returns 0 if LTV <= 80%."""
    if purchase_price <= 0:
        return 0
    ltv = loan_amount / purchase_price
    rate = _pmi_rate_for_ltv(ltv)
    if rate <= 0:
        return 0
    return int(round(loan_amount * rate / 12))


def calc_pmi_dropoff_month(
    loan_amount: int,
    purchase_price: int,
    annual_rate_pct: float,
) -> int | None:
    """Find the month when LTV drops to 80% via amortization.

    Returns None if PMI is not applicable or loan is too small.
    """
    if purchase_price <= 0 or loan_amount <= 0:
        return None
    ltv = loan_amount / purchase_price
    if ltv <= _PMI_LTV_THRESHOLD:
        return None

    target_balance = purchase_price * _PMI_LTV_THRESHOLD
    monthly_rate = (annual_rate_pct / 100) / 12
    if monthly_rate <= 0:
        # Zero-rate edge case: straight-line principal paydown
        monthly_principal = loan_amount / _LOAN_TERM_MONTHS
        if monthly_principal <= 0:
            return None
        months = math.ceil((loan_amount - target_balance) / monthly_principal)
        return max(1, months)

    balance = float(loan_amount)
    monthly_payment = calc_monthly_payment(loan_amount, annual_rate_pct, _LOAN_TERM_MONTHS)

    for month in range(1, _LOAN_TERM_MONTHS + 1):
        interest = balance * monthly_rate
        principal = monthly_payment - interest
        balance -= principal
        if balance <= target_balance:
            return month

    return _LOAN_TERM_MONTHS  # shouldn't happen, but safety fallback


def _calc_monthly_earthquake(purchase_price: int, construction_type: str) -> int:
    """Monthly earthquake insurance estimate."""
    rate = _EQ_RATES.get(construction_type, _EQ_RATES["wood_frame"])
    dwelling_coverage = purchase_price * _EQ_DWELLING_COVERAGE_RATIO
    return int(round(dwelling_coverage * rate / 12))


def _calc_monthly_maintenance(purchase_price: int, year_built: int | None) -> int:
    """Monthly maintenance reserve based on property age."""
    if year_built is None:
        rate = _MAINTENANCE_DEFAULT
    else:
        age = max(0, datetime.date.today().year - year_built)
        rate = _MAINTENANCE_DEFAULT
        for max_age, bracket_rate in _MAINTENANCE_RATES:
            if age < max_age:
                rate = bracket_rate
                break
    return int(round(purchase_price * rate / 12))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_true_cost(params: TrueCostParams) -> dict:
    """Compute the all-in monthly ownership cost for a Berkeley property.

    Returns a dict with component breakdown, totals, and optional rent
    comparison. All monetary values are whole-dollar integers.
    """
    purchase_price = params.purchase_price
    down_pct = params.down_payment_pct / 100.0
    down_amount = int(round(purchase_price * down_pct))
    loan_amount = purchase_price - down_amount

    # --- Component costs ---
    monthly_pi = _calc_monthly_pi(loan_amount, params.mortgage_rate)
    monthly_tax = int(round(purchase_price * PROPERTY_TAX_RATE / 12))
    monthly_hoi = int(round(purchase_price * _HOI_RATE / 12))
    monthly_eq = _calc_monthly_earthquake(purchase_price, params.construction_type)
    monthly_maintenance = _calc_monthly_maintenance(purchase_price, params.year_built)
    monthly_pmi = _calc_monthly_pmi(loan_amount, purchase_price)
    monthly_hoa = params.hoa_monthly

    # --- Totals ---
    total = (
        monthly_pi
        + monthly_tax
        + monthly_hoi
        + monthly_eq
        + monthly_maintenance
        + monthly_pmi
        + monthly_hoa
    )
    total_no_eq = total - monthly_eq

    # --- PMI note ---
    is_pmi_applicable = monthly_pmi > 0
    pmi_note: str | None = None
    if is_pmi_applicable:
        dropoff = calc_pmi_dropoff_month(loan_amount, purchase_price, params.mortgage_rate)
        if dropoff:
            target_balance = int(round(purchase_price * _PMI_LTV_THRESHOLD))
            years = dropoff // 12
            months = dropoff % 12
            time_str = f"{years}y {months}m" if months else f"{years}y"
            pmi_note = (
                f"PMI drops when balance reaches ${target_balance:,} "
                f"(approx. {time_str} at current payment)"
            )

    # --- Rent comparison ---
    current_rent = params.current_rent
    monthly_delta: int | None = None
    delta_direction: str | None = None
    if current_rent is not None:
        monthly_delta = total - current_rent
        if monthly_delta > 0:
            delta_direction = "more_than_rent"
        elif monthly_delta < 0:
            delta_direction = "less_than_rent"
        else:
            delta_direction = "equal"

    return {
        # Inputs echoed
        "purchase_price": purchase_price,
        "down_payment_pct": params.down_payment_pct,
        "down_payment_amount": down_amount,
        "loan_amount": loan_amount,
        "mortgage_rate": params.mortgage_rate,
        "is_pmi_applicable": is_pmi_applicable,
        # Monthly breakdown
        "monthly_principal_and_interest": monthly_pi,
        "monthly_property_tax": monthly_tax,
        "monthly_hoi": monthly_hoi,
        "monthly_earthquake_insurance": monthly_eq,
        "monthly_maintenance_reserve": monthly_maintenance,
        "monthly_pmi": monthly_pmi,
        "monthly_hoa": monthly_hoa,
        # Totals
        "total_monthly_cost": total,
        "total_monthly_cost_no_eq": total_no_eq,
        # Rent comparison
        "current_rent": current_rent,
        "monthly_delta_vs_rent": monthly_delta,
        "delta_direction": delta_direction,
        # Metadata
        "construction_type": params.construction_type,
        "year_built": params.year_built,
        "pmi_note": pmi_note,
    }
