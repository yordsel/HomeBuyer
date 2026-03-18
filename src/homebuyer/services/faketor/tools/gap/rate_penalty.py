"""Mortgage rate penalty calculator for equity-trapped upgraders.

Takes an existing mortgage (balance, rate) and a proposed new purchase,
then computes:
  - Current payment vs. new payment at market rate
  - Monthly/annual dollar penalty
  - Penalty as % of gross income
  - Rate scenarios: at what rate does the penalty become "tolerable"?
  - Breakeven: rate at which new payment equals current payment

All computation is pure — no DB access, no I/O.

Phase F-4 (#57) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass

from homebuyer.utils.mortgage import calc_monthly_payment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOAN_TERM_MONTHS = 360  # 30-year fixed
_TOLERABLE_INCOME_PCT = 5.0  # penalty < 5% of gross monthly income


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class RatePenaltyParams:
    """Inputs for the rate penalty analysis."""

    # Existing mortgage
    existing_balance: int          # remaining balance on current loan
    existing_rate: float           # current rate as percent (e.g., 3.25)
    existing_remaining_months: int = _LOAN_TERM_MONTHS  # months left

    # Proposed new purchase
    new_purchase_price: int = 0
    new_down_payment_pct: float = 20.0  # percent
    new_rate: float = 7.0              # current market rate as percent

    # Income for affordability context
    annual_gross_income: int | None = None

    # Rate scenario range
    scenario_rate_start: float | None = None  # defaults to new_rate - 2.0
    scenario_rate_end: float | None = None    # defaults to new_rate + 1.0
    scenario_rate_step: float = 0.25          # step size in percent


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _monthly_payment(balance: int, rate_pct: float, term_months: int) -> int:
    """Compute monthly P&I payment, returning whole dollars."""
    if balance <= 0 or rate_pct <= 0:
        return int(round(balance / term_months)) if term_months > 0 else 0
    return int(round(calc_monthly_payment(balance, rate_pct, term_months)))


def _find_breakeven_rate(
    new_loan: int,
    target_payment: int,
    term_months: int = _LOAN_TERM_MONTHS,
) -> float | None:
    """Find the rate at which new_loan's payment equals target_payment.

    Uses binary search. Returns rate as percent (e.g., 4.25) or None if
    no rate in [0.5%, 15%] achieves the target.
    """
    if new_loan <= 0 or target_payment <= 0:
        return None

    lo, hi = 0.5, 15.0
    for _ in range(50):  # ~50 iterations gives sub-0.001% precision
        mid = (lo + hi) / 2
        payment = calc_monthly_payment(new_loan, mid, term_months)
        if payment < target_payment:
            lo = mid
        else:
            hi = mid

    result = round((lo + hi) / 2, 2)
    # Verify the result is within 1% of the target payment
    check = calc_monthly_payment(new_loan, result, term_months)
    if target_payment > 0 and abs(check - target_payment) / target_payment > 0.01:
        return None
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_rate_penalty(params: RatePenaltyParams) -> dict:
    """Compute the rate penalty for moving from an existing low-rate mortgage.

    Returns a dict with payment comparison, income-relative penalty,
    rate scenarios, and breakeven rate.
    """
    # --- Existing mortgage ---
    existing_payment = _monthly_payment(
        params.existing_balance, params.existing_rate,
        params.existing_remaining_months,
    )

    # --- New mortgage ---
    new_down_pct = params.new_down_payment_pct / 100.0
    new_down_amount = int(round(params.new_purchase_price * new_down_pct))
    new_loan = params.new_purchase_price - new_down_amount

    new_payment = _monthly_payment(new_loan, params.new_rate, _LOAN_TERM_MONTHS)

    # --- Penalty ---
    monthly_penalty = new_payment - existing_payment
    annual_penalty = monthly_penalty * 12

    # Income-relative
    monthly_income = None
    penalty_pct_of_income = None
    is_tolerable = None
    if params.annual_gross_income is not None and params.annual_gross_income > 0:
        monthly_income = params.annual_gross_income // 12
        if monthly_income > 0:
            penalty_pct_of_income = round(
                abs(monthly_penalty) / monthly_income * 100, 1
            )
            is_tolerable = penalty_pct_of_income <= _TOLERABLE_INCOME_PCT

    # --- Breakeven rate ---
    breakeven_rate = _find_breakeven_rate(new_loan, existing_payment)

    # --- Rate scenarios ---
    rate_start = params.scenario_rate_start
    if rate_start is None:
        rate_start = max(1.0, params.new_rate - 2.0)
    rate_end = params.scenario_rate_end
    if rate_end is None:
        rate_end = params.new_rate + 1.0
    step = params.scenario_rate_step

    scenarios: list[dict] = []
    rate = rate_start
    while rate <= rate_end + 0.001:  # floating point tolerance
        scenario_payment = _monthly_payment(new_loan, rate, _LOAN_TERM_MONTHS)
        scenario_penalty = scenario_payment - existing_payment
        scenario_pct = None
        scenario_tolerable = None
        if monthly_income and monthly_income > 0:
            scenario_pct = round(abs(scenario_penalty) / monthly_income * 100, 1)
            scenario_tolerable = scenario_pct <= _TOLERABLE_INCOME_PCT

        scenarios.append({
            "rate": round(rate, 2),
            "monthly_payment": scenario_payment,
            "monthly_penalty": scenario_penalty,
            "annual_penalty": scenario_penalty * 12,
            "penalty_pct_of_income": scenario_pct,
            "is_tolerable": scenario_tolerable,
        })
        rate += step

    # Find the tolerable rate (highest rate where penalty is still tolerable)
    tolerable_rate = None
    if monthly_income and monthly_income > 0:
        for s in scenarios:
            if s["is_tolerable"]:
                tolerable_rate = s["rate"]

    # --- Penalty description ---
    if monthly_penalty > 0:
        direction = "more"
    elif monthly_penalty < 0:
        direction = "less"
    else:
        direction = "same"

    penalty_desc = (
        f"New payment is ${abs(monthly_penalty):,}/mo {direction} than current "
        f"(${new_payment:,} vs ${existing_payment:,})"
    )

    return {
        # Inputs echoed
        "existing_balance": params.existing_balance,
        "existing_rate": params.existing_rate,
        "existing_remaining_months": params.existing_remaining_months,
        "new_purchase_price": params.new_purchase_price,
        "new_down_payment_pct": params.new_down_payment_pct,
        "new_down_payment_amount": new_down_amount,
        "new_loan_amount": new_loan,
        "new_rate": params.new_rate,
        # Payment comparison
        "existing_monthly_payment": existing_payment,
        "new_monthly_payment": new_payment,
        "monthly_penalty": monthly_penalty,
        "annual_penalty": annual_penalty,
        "penalty_description": penalty_desc,
        # Income context
        "annual_gross_income": params.annual_gross_income,
        "monthly_gross_income": monthly_income,
        "penalty_pct_of_income": penalty_pct_of_income,
        "is_tolerable": is_tolerable,
        "tolerable_threshold_pct": _TOLERABLE_INCOME_PCT,
        # Breakeven
        "breakeven_rate": breakeven_rate,
        "breakeven_description": (
            f"New payment matches current at {breakeven_rate}% rate"
            if breakeven_rate
            else "No feasible rate matches current payment"
        ),
        # Rate scenarios
        "rate_scenarios": scenarios,
        "tolerable_rate": tolerable_rate,
    }
