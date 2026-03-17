"""Appreciation stress test for appreciation bettors.

Models breakeven between negative carry and appreciation under multiple
scenarios. Includes downside modeling and exit analysis at configurable
horizons.

All computation is pure — no DB access, no I/O.

Phase F-8 (#61) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from homebuyer.utils.mortgage import calc_monthly_payment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOAN_TERM_MONTHS = 360
_SELLING_COST_PCT = 0.06   # 6% of sale price
_PROPERTY_TAX_RATE = 0.0118
_INSURANCE_RATE = 0.0040
_MAINTENANCE_PCT = 0.01

# Default scenarios
_DEFAULT_SCENARIOS = [
    {"name": "Bull (+5%/yr)", "annual_appreciation_pct": 5.0},
    {"name": "Base (+3%/yr)", "annual_appreciation_pct": 3.0},
    {"name": "Flat (0%/yr)", "annual_appreciation_pct": 0.0},
    {"name": "Bear (-5%/yr)", "annual_appreciation_pct": -5.0},
    {"name": "Crash (-15%/yr)", "annual_appreciation_pct": -15.0},
]


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class AppreciationScenario:
    """One appreciation scenario."""

    name: str = ""
    annual_appreciation_pct: float = 0.0


@dataclass
class AppreciationStressParams:
    """Inputs for the appreciation stress test."""

    purchase_price: int
    down_payment_pct: float = 20.0
    mortgage_rate: float = 7.0
    monthly_rental_income: int = 0       # if held as rental
    monthly_ownership_cost: int | None = None  # total monthly cost
    exit_years: list[int] = field(default_factory=lambda: [3, 5, 7, 10])
    scenarios: list[AppreciationScenario] = field(default_factory=list)
    refi_rate: float | None = None       # potential refinance rate


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _monthly_cost(purchase_price: int, loan_amount: int, rate_pct: float) -> int:
    """Estimate total monthly ownership cost."""
    if loan_amount > 0 and rate_pct > 0:
        pi = int(round(calc_monthly_payment(loan_amount, rate_pct, _LOAN_TERM_MONTHS)))
    else:
        pi = 0
    tax = int(round(purchase_price * _PROPERTY_TAX_RATE / 12))
    ins = int(round(purchase_price * _INSURANCE_RATE / 12))
    maint = int(round(purchase_price * _MAINTENANCE_PCT / 12))
    return pi + tax + ins + maint


def _compute_exit(
    purchase_price: int,
    down_amount: int,
    loan_amount: int,
    rate_pct: float,
    monthly_cost: int,
    monthly_rental: int,
    year: int,
    appreciation_pct: float,
) -> dict:
    """Compute exit analysis at a specific year."""
    appreciation_rate = appreciation_pct / 100.0

    # Home value at exit
    home_value = int(round(purchase_price * (1 + appreciation_rate) ** year))

    # Remaining balance via amortization
    if loan_amount > 0 and rate_pct > 0:
        monthly_rate = (rate_pct / 100) / 12
        monthly_payment = calc_monthly_payment(loan_amount, rate_pct, _LOAN_TERM_MONTHS)
        balance = float(loan_amount)
        for _ in range(year * 12):
            if balance <= 0:
                break
            interest = balance * monthly_rate
            principal = monthly_payment - interest
            if principal > balance:
                principal = balance
            balance -= principal
        remaining_balance = max(0, int(round(balance)))
    else:
        remaining_balance = 0

    # Selling costs
    selling_costs = int(round(home_value * _SELLING_COST_PCT))

    # Net proceeds
    net_proceeds = home_value - remaining_balance - selling_costs

    # Total cost of carry
    monthly_carry = monthly_cost - monthly_rental
    total_carry = monthly_carry * year * 12

    # Total investment = down payment + carry
    total_invested = down_amount + total_carry

    # Profit/loss
    profit = net_proceeds - total_invested

    # Annualized ROI — guard against negative ratio (complex power)
    if total_invested > 0 and year > 0 and net_proceeds > 0:
        annualized_roi = round(
            ((net_proceeds / total_invested) ** (1 / year) - 1) * 100, 2
        )
    elif total_invested > 0 and year > 0:
        # Total loss scenario: express as simple annualized loss
        annualized_roi = round(profit / total_invested / year * 100, 2)
    else:
        annualized_roi = 0.0

    return {
        "year": year,
        "home_value": home_value,
        "remaining_balance": remaining_balance,
        "selling_costs": selling_costs,
        "net_proceeds": net_proceeds,
        "total_carry_cost": total_carry,
        "total_invested": total_invested,
        "profit": profit,
        "annualized_roi_pct": annualized_roi,
        "is_profitable": profit > 0,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_appreciation_stress(params: AppreciationStressParams) -> dict:
    """Run appreciation stress test across scenarios and exit horizons."""
    down_pct = params.down_payment_pct / 100.0
    down_amount = int(round(params.purchase_price * down_pct))
    loan_amount = params.purchase_price - down_amount

    # Monthly cost
    if params.monthly_ownership_cost is not None:
        monthly_cost = params.monthly_ownership_cost
    else:
        monthly_cost = _monthly_cost(
            params.purchase_price, loan_amount, params.mortgage_rate
        )

    monthly_rental = params.monthly_rental_income
    monthly_carry = monthly_cost - monthly_rental

    # Scenarios
    scenarios = params.scenarios or [
        AppreciationScenario(**s) for s in _DEFAULT_SCENARIOS
    ]

    results: list[dict] = []
    for scenario in scenarios:
        exits: list[dict] = []
        for year in params.exit_years:
            exit_result = _compute_exit(
                params.purchase_price, down_amount, loan_amount,
                params.mortgage_rate, monthly_cost, monthly_rental,
                year, scenario.annual_appreciation_pct,
            )
            exits.append(exit_result)

        # Find breakeven year (first profitable exit)
        breakeven_year = None
        for e in exits:
            if e["is_profitable"]:
                breakeven_year = e["year"]
                break

        results.append({
            "scenario_name": scenario.name,
            "annual_appreciation_pct": scenario.annual_appreciation_pct,
            "exits": exits,
            "breakeven_year": breakeven_year,
            "best_exit": max(exits, key=lambda e: e["profit"]),
            "worst_exit": min(exits, key=lambda e: e["profit"]),
        })

    # Refi scenario
    refi_analysis = None
    if params.refi_rate is not None and loan_amount > 0:
        current_pi = int(round(
            calc_monthly_payment(loan_amount, params.mortgage_rate, _LOAN_TERM_MONTHS)
        )) if params.mortgage_rate > 0 else 0
        refi_pi = int(round(
            calc_monthly_payment(loan_amount, params.refi_rate, _LOAN_TERM_MONTHS)
        )) if params.refi_rate > 0 else 0
        monthly_savings = current_pi - refi_pi
        refi_analysis = {
            "current_rate": params.mortgage_rate,
            "refi_rate": params.refi_rate,
            "current_monthly_pi": current_pi,
            "refi_monthly_pi": refi_pi,
            "monthly_savings": monthly_savings,
            "annual_savings": monthly_savings * 12,
            "new_monthly_carry": monthly_carry - monthly_savings,
        }

    # Summary across all scenarios
    all_profitable = all(
        any(e["is_profitable"] for e in s["exits"]) for s in results
    )
    any_profitable = any(
        any(e["is_profitable"] for e in s["exits"]) for s in results
    )

    return {
        # Inputs
        "purchase_price": params.purchase_price,
        "down_payment_pct": params.down_payment_pct,
        "down_payment_amount": down_amount,
        "mortgage_rate": params.mortgage_rate,
        "monthly_ownership_cost": monthly_cost,
        "monthly_rental_income": monthly_rental,
        "monthly_carry_cost": monthly_carry,
        "exit_years": params.exit_years,
        # Results
        "scenarios": results,
        "refi_analysis": refi_analysis,
        # Summary
        "all_scenarios_profitable": all_profitable,
        "any_scenario_profitable": any_profitable,
        "scenario_count": len(results),
    }
