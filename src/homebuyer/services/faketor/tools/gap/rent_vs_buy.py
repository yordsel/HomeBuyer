"""Rent vs. buy breakeven analysis.

Compares the total cost of renting vs. buying over a multi-year horizon:
  - Ownership side: monthly cost (from true_cost components), equity buildup
    via appreciation + principal paydown, tax benefits (mortgage interest +
    property tax deduction), PMI drop-off
  - Renting side: current rent with annual escalation, opportunity cost of
    investing the down payment in the market

Produces a crossover point (year when buying becomes cheaper than renting
on a cumulative net-cost basis) and year-by-year comparison table.

All computation is pure — no DB access, no I/O.

Phase F-2 (#55) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass

from homebuyer.utils.mortgage import calc_monthly_payment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_HORIZON_YEARS = 30
_LOAN_TERM_MONTHS = 360

# Tax benefit assumptions (federal, Berkeley/CA context)
_MARGINAL_TAX_RATE = 0.32          # Federal marginal rate (24% + ~8% CA state)
_STANDARD_DEDUCTION = 29_200       # 2024 MFJ standard deduction
_PROPERTY_TAX_DEDUCTION_CAP = 10_000  # SALT cap

# Opportunity cost: what the down payment could earn invested elsewhere
_MARKET_RETURN_RATE = 0.07         # 7% nominal annual return (S&P historical)

# Transaction costs when selling
_SELLING_COST_PCT = 0.06           # 6% of sale price (agent fees + transfer tax + closing)


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class RentVsBuyParams:
    """All inputs for the rent-vs-buy analysis."""

    # Property / purchase
    purchase_price: int
    down_payment_pct: float = 20.0      # percent
    mortgage_rate: float = 6.5          # annual rate as percent
    annual_appreciation_pct: float = 3.0  # percent

    # Ownership costs (monthly, from true_cost output or manual)
    monthly_ownership_cost: int = 0     # total_monthly_cost from true_cost
    monthly_pmi: int = 0                # PMI component (drops off)
    pmi_dropoff_month: int | None = None  # month when PMI drops

    # Property tax (annual, for tax benefit calc)
    annual_property_tax: int = 0

    # Renting
    current_rent: int = 3_000
    annual_rent_increase_pct: float = 4.0  # percent

    # Analysis
    horizon_years: int = 15
    marginal_tax_rate: float = _MARGINAL_TAX_RATE


# ---------------------------------------------------------------------------
# Year-by-year analysis
# ---------------------------------------------------------------------------


@dataclass
class YearSnapshot:
    """One year's rent-vs-buy comparison."""

    year: int
    # Renting
    annual_rent: int
    cumulative_rent: int
    opportunity_gain: int       # cumulative gain on invested down payment
    cumulative_rent_net: int    # cumulative_rent - opportunity_gain
    # Buying
    annual_ownership_cost: int
    cumulative_ownership: int
    home_equity: int            # appreciation + principal paydown
    tax_benefit_cumulative: int
    cumulative_buy_net: int     # cumulative_ownership - equity - tax_benefits + selling_costs
    # Comparison
    buy_advantage: int          # cumulative_rent_net - cumulative_buy_net (positive = buying wins)


def compute_rent_vs_buy(params: RentVsBuyParams) -> dict:
    """Run the full rent-vs-buy breakeven analysis.

    Returns a dict with year-by-year snapshots, crossover point, and
    summary metrics.
    """
    horizon = min(params.horizon_years, _MAX_HORIZON_YEARS)
    down_pct = params.down_payment_pct / 100.0
    down_amount = int(round(params.purchase_price * down_pct))
    loan_amount = params.purchase_price - down_amount
    monthly_rate = (params.mortgage_rate / 100) / 12
    appreciation_rate = params.annual_appreciation_pct / 100
    rent_increase_rate = params.annual_rent_increase_pct / 100
    market_return_rate = _MARKET_RETURN_RATE

    # Monthly P&I for amortization tracking
    if loan_amount > 0 and params.mortgage_rate > 0:
        monthly_payment = calc_monthly_payment(
            loan_amount, params.mortgage_rate, _LOAN_TERM_MONTHS
        )
    else:
        monthly_payment = 0.0

    # Track loan balance for interest/principal split and equity
    balance = float(loan_amount)

    # Cumulative trackers
    cumulative_rent = 0
    cumulative_ownership = 0
    cumulative_tax_benefit = 0
    snapshots: list[dict] = []
    crossover_year: int | None = None

    for year in range(1, horizon + 1):
        # --- Renting side ---
        annual_rent = int(round(params.current_rent * 12 * (1 + rent_increase_rate) ** (year - 1)))
        cumulative_rent += annual_rent

        # Opportunity cost: down payment invested at market return
        opportunity_gain = int(round(down_amount * ((1 + market_return_rate) ** year - 1)))
        cumulative_rent_net = cumulative_rent - opportunity_gain

        # --- Buying side ---
        # Ownership cost for this year (adjust for PMI drop-off mid-year)
        year_start_month = (year - 1) * 12 + 1
        year_end_month = year * 12
        if (
            params.pmi_dropoff_month is not None
            and params.monthly_pmi > 0
            and year_end_month > params.pmi_dropoff_month
            and year_start_month <= params.pmi_dropoff_month
        ):
            # PMI drops partway through this year
            pmi_months = params.pmi_dropoff_month - year_start_month + 1
            no_pmi_months = 12 - pmi_months
            annual_own = (
                pmi_months * params.monthly_ownership_cost
                + no_pmi_months * (params.monthly_ownership_cost - params.monthly_pmi)
            )
        elif (
            params.pmi_dropoff_month is not None
            and params.monthly_pmi > 0
            and year_start_month > params.pmi_dropoff_month
        ):
            # PMI already dropped for full year
            annual_own = (params.monthly_ownership_cost - params.monthly_pmi) * 12
        else:
            annual_own = params.monthly_ownership_cost * 12
        cumulative_ownership += annual_own

        # Home equity: appreciation
        home_value = int(round(params.purchase_price * (1 + appreciation_rate) ** year))

        # Principal paydown this year
        annual_interest = 0.0
        for _ in range(12):
            if balance <= 0:
                break
            interest = balance * monthly_rate
            principal = monthly_payment - interest
            if principal > balance:
                principal = balance
            balance -= principal
            annual_interest += interest

        remaining_balance = max(0, int(round(balance)))
        home_equity = home_value - remaining_balance

        # Tax benefit: mortgage interest + property tax deductions
        # Only beneficial if itemized deductions exceed standard deduction
        annual_prop_tax_deductible = min(
            params.annual_property_tax, _PROPERTY_TAX_DEDUCTION_CAP
        )
        total_itemized = int(round(annual_interest)) + annual_prop_tax_deductible
        marginal_benefit = max(0, total_itemized - _STANDARD_DEDUCTION)
        annual_tax_benefit = int(round(marginal_benefit * params.marginal_tax_rate))
        cumulative_tax_benefit += annual_tax_benefit

        # Net cost of buying: down payment + cumulative ongoing costs + selling
        # costs - equity gained - tax benefits.
        # The down payment is a sunk cost the renter avoids (the renter's
        # opportunity cost on that same money is captured on the renting side).
        selling_costs = int(round(home_value * _SELLING_COST_PCT))
        cumulative_buy_net = (
            down_amount
            + cumulative_ownership
            + selling_costs
            - home_equity
            - cumulative_tax_benefit
        )

        # Comparison
        buy_advantage = cumulative_rent_net - cumulative_buy_net

        if crossover_year is None and buy_advantage > 0:
            crossover_year = year

        snapshots.append({
            "year": year,
            "annual_rent": annual_rent,
            "cumulative_rent": cumulative_rent,
            "opportunity_gain": opportunity_gain,
            "cumulative_rent_net": cumulative_rent_net,
            "annual_ownership_cost": annual_own,
            "cumulative_ownership": cumulative_ownership,
            "home_value": home_value,
            "home_equity": home_equity,
            "remaining_balance": remaining_balance,
            "tax_benefit_cumulative": cumulative_tax_benefit,
            "selling_costs": selling_costs,
            "cumulative_buy_net": cumulative_buy_net,
            "buy_advantage": buy_advantage,
        })

    # Summary
    final = snapshots[-1] if snapshots else {}

    return {
        # Inputs echoed
        "purchase_price": params.purchase_price,
        "down_payment_pct": params.down_payment_pct,
        "down_payment_amount": down_amount,
        "current_rent": params.current_rent,
        "mortgage_rate": params.mortgage_rate,
        "annual_appreciation_pct": params.annual_appreciation_pct,
        "annual_rent_increase_pct": params.annual_rent_increase_pct,
        "horizon_years": horizon,
        # Key results
        "crossover_year": crossover_year,
        "crossover_description": (
            f"Buying becomes cheaper than renting after year {crossover_year}"
            if crossover_year
            else f"Renting is cheaper than buying over the full {horizon}-year horizon"
        ),
        # Final year summary
        "final_annual_rent": final.get("annual_rent"),
        "final_home_value": final.get("home_value"),
        "final_home_equity": final.get("home_equity"),
        "final_buy_advantage": final.get("buy_advantage"),
        "total_rent_paid": final.get("cumulative_rent"),
        "total_ownership_paid": final.get("cumulative_ownership"),
        "total_tax_benefit": final.get("tax_benefit_cumulative"),
        "opportunity_cost_of_down_payment": final.get("opportunity_gain"),
        # Year-by-year (for detailed analysis)
        "yearly_comparison": snapshots,
    }
