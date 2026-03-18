"""PMI cost model with tiered rates, drop-off timeline, and buy-now-vs-wait.

Computes:
  - Monthly PMI at buyer's LTV using tiered rate brackets (85-95% vs 80-85%)
  - PMI drop-off month via combined appreciation + principal paydown
  - Total PMI cost over the life of the loan
  - Buy-now-vs-wait comparison: does saving more down payment beat market
    appreciation?

All computation is pure — no DB access, no I/O.

Phase F-3 (#56) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass

from homebuyer.utils.mortgage import calc_monthly_payment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOAN_TERM_MONTHS = 360
_PMI_LTV_THRESHOLD = 0.80

# Tiered PMI rate table — conventional BPMI by LTV bracket.
# (ltv_min_exclusive, ltv_max_inclusive, annual_rate)
_PMI_RATE_TABLE: list[tuple[float, float, float]] = [
    (0.850, 0.950, 0.0110),  # 85.01–95% LTV: high risk — 1.10%
    (0.800, 0.850, 0.0075),  # 80.01–85% LTV: mid risk — 0.75%
]

# Buy-now-vs-wait: inconclusive when PMI savings and price increase are
# within this fraction of each other.
_WAIT_INCONCLUSIVE_BAND = 0.05


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class PmiModelParams:
    """All inputs for the PMI model analysis."""

    purchase_price: int
    down_payment_pct: float = 10.0          # percent (e.g., 10.0 = 10%)
    mortgage_rate: float = 6.5              # annual rate as percent
    annual_appreciation_pct: float = 3.0    # expected annual appreciation

    # Buy-now-vs-wait inputs
    monthly_savings: int | None = None      # how much buyer saves per month
    wait_months: int = 12                   # candidate wait period


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _pmi_rate_for_ltv(ltv: float) -> float:
    """Return the annual PMI rate for a given LTV ratio."""
    for ltv_min, ltv_max, rate in _PMI_RATE_TABLE:
        if ltv_min < ltv <= ltv_max:
            return rate
    return 0.0


def _monthly_pmi_for_ltv(loan_balance: float, ltv: float) -> int:
    """Return monthly PMI amount for the given balance and LTV."""
    rate = _pmi_rate_for_ltv(ltv)
    if rate <= 0:
        return 0
    return int(round(loan_balance * rate / 12))


def _simulate_pmi_timeline(
    loan_amount: int,
    purchase_price: int,
    annual_rate_pct: float,
    annual_appreciation_pct: float,
) -> list[dict]:
    """Month-by-month simulation until PMI drops off or loan term ends.

    Returns a list of monthly snapshots with balance, home_value, ltv,
    monthly_pmi, and pmi_rate.
    """
    if loan_amount <= 0 or purchase_price <= 0:
        return []

    initial_ltv = loan_amount / purchase_price
    if initial_ltv <= _PMI_LTV_THRESHOLD:
        return []

    monthly_rate = (annual_rate_pct / 100) / 12
    monthly_appreciation = (1 + annual_appreciation_pct / 100) ** (1 / 12) - 1

    if annual_rate_pct > 0 and loan_amount > 0:
        monthly_payment = calc_monthly_payment(
            loan_amount, annual_rate_pct, _LOAN_TERM_MONTHS
        )
    else:
        monthly_payment = loan_amount / _LOAN_TERM_MONTHS if loan_amount > 0 else 0.0

    balance = float(loan_amount)
    home_value = float(purchase_price)
    snapshots: list[dict] = []

    for month in range(1, _LOAN_TERM_MONTHS + 1):
        # Amortization
        if monthly_rate > 0:
            interest = balance * monthly_rate
            principal = monthly_payment - interest
        else:
            principal = monthly_payment
        if principal > balance:
            principal = balance
        balance -= principal

        # Appreciation
        home_value *= (1 + monthly_appreciation)

        ltv = balance / home_value if home_value > 0 else 0.0
        pmi_rate = _pmi_rate_for_ltv(ltv)
        pmi = int(round(balance * pmi_rate / 12)) if pmi_rate > 0 else 0

        snapshots.append({
            "month": month,
            "balance": int(round(balance)),
            "home_value": int(round(home_value)),
            "ltv": round(ltv, 4),
            "monthly_pmi": pmi,
            "pmi_rate": pmi_rate,
        })

        if ltv <= _PMI_LTV_THRESHOLD:
            break

    return snapshots


def _compute_ltv_brackets(snapshots: list[dict]) -> list[dict]:
    """Walk snapshots and group into LTV bracket periods."""
    if not snapshots:
        return []

    brackets: list[dict] = []
    current_rate = snapshots[0]["pmi_rate"]
    entry_month = snapshots[0]["month"]
    bracket_cost = 0
    bracket_months = 0

    for snap in snapshots:
        if snap["pmi_rate"] != current_rate:
            # Close current bracket
            brackets.append({
                "bracket": _bracket_label(current_rate),
                "pmi_rate_pct": round(current_rate * 100, 2),
                "months_in_bracket": bracket_months,
                "total_cost_in_bracket": bracket_cost,
                "entry_month": entry_month,
                "exit_month": snap["month"] - 1,
            })
            # Start new bracket
            current_rate = snap["pmi_rate"]
            entry_month = snap["month"]
            bracket_cost = 0
            bracket_months = 0

        if snap["pmi_rate"] > 0:
            bracket_cost += snap["monthly_pmi"]
            bracket_months += 1

    # Close final bracket
    if bracket_months > 0:
        brackets.append({
            "bracket": _bracket_label(current_rate),
            "pmi_rate_pct": round(current_rate * 100, 2),
            "months_in_bracket": bracket_months,
            "total_cost_in_bracket": bracket_cost,
            "entry_month": entry_month,
            "exit_month": snapshots[-1]["month"],
        })

    return brackets


def _bracket_label(rate: float) -> str:
    """Return human-readable bracket label for a PMI rate."""
    for ltv_min, ltv_max, r in _PMI_RATE_TABLE:
        if abs(r - rate) < 1e-6:
            return f"{ltv_min * 100:.2f}%–{ltv_max * 100:.2f}%"
    return "0%–80.00%"


def _compute_wait_race(
    purchase_price: int,
    down_payment_pct: float,
    monthly_savings: int,
    wait_months: int,
    annual_appreciation_pct: float,
    mortgage_rate: float,
) -> dict:
    """Compare buying now vs. waiting to save more down payment."""
    down_pct = down_payment_pct / 100.0
    current_down = int(round(purchase_price * down_pct))
    appreciation_rate = annual_appreciation_pct / 100.0

    # Projected price after waiting
    projected_price = int(round(
        purchase_price * (1 + appreciation_rate) ** (wait_months / 12)
    ))
    price_increase = projected_price - purchase_price

    # New down payment after saving
    savings_gained = monthly_savings * wait_months
    new_down = current_down + savings_gained
    new_down_pct = (new_down / projected_price * 100) if projected_price > 0 else 0.0
    new_loan = projected_price - new_down
    new_ltv = new_loan / projected_price if projected_price > 0 else 0.0

    new_monthly_pmi = _monthly_pmi_for_ltv(float(new_loan), new_ltv)

    # Simulate both scenarios to get total PMI costs
    current_loan = purchase_price - current_down
    buy_now_snapshots = _simulate_pmi_timeline(
        current_loan, purchase_price, mortgage_rate, annual_appreciation_pct
    )
    wait_snapshots = _simulate_pmi_timeline(
        new_loan, projected_price, mortgage_rate, annual_appreciation_pct
    )

    total_pmi_now = sum(s["monthly_pmi"] for s in buy_now_snapshots)
    total_pmi_wait = sum(s["monthly_pmi"] for s in wait_snapshots)
    pmi_savings = total_pmi_now - total_pmi_wait

    # Net cost of waiting: price increase minus PMI savings
    # Negative means waiting is better overall
    net_cost = price_increase - pmi_savings

    # Determine verdict
    if price_increase > 0 and abs(pmi_savings - price_increase) / price_increase < _WAIT_INCONCLUSIVE_BAND:
        verdict = "inconclusive"
    elif net_cost > 0:
        verdict = "buy_now"
    else:
        verdict = "wait"

    # Build description
    if verdict == "buy_now":
        desc = (
            f"Waiting {wait_months} months saves ${pmi_savings:,} in PMI "
            f"but the market rises an estimated ${price_increase:,} — "
            f"buying now costs ${net_cost:,} less overall."
        )
    elif verdict == "wait":
        desc = (
            f"Waiting {wait_months} months costs ${price_increase:,} more in home price "
            f"but saves ${pmi_savings:,} in PMI — "
            f"waiting saves ${abs(net_cost):,} overall."
        )
    else:
        desc = (
            f"Waiting {wait_months} months produces roughly equal costs: "
            f"${price_increase:,} price increase vs ${pmi_savings:,} PMI savings "
            f"(within 5%)."
        )

    # Drop-off month for the wait scenario
    wait_dropoff = wait_snapshots[-1]["month"] if wait_snapshots else None
    if wait_snapshots and wait_snapshots[-1]["ltv"] > _PMI_LTV_THRESHOLD:
        wait_dropoff = None  # never dropped off within term

    return {
        "wait_months": wait_months,
        "monthly_savings": monthly_savings,
        "savings_gained": savings_gained,
        "projected_purchase_price": projected_price,
        "price_increase": price_increase,
        "new_down_payment_amount": new_down,
        "new_down_payment_pct": round(new_down_pct, 1),
        "new_monthly_pmi": new_monthly_pmi,
        "new_pmi_dropoff_month": wait_dropoff,
        "total_pmi_cost_buy_now": total_pmi_now,
        "total_pmi_cost_after_wait": total_pmi_wait,
        "pmi_savings_from_waiting": pmi_savings,
        "net_cost_of_waiting": net_cost,
        "verdict": verdict,
        "verdict_description": desc,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_pmi_model(params: PmiModelParams) -> dict:
    """Run the full PMI analysis.

    Returns a dict with PMI cost, drop-off timeline, LTV brackets,
    and optional buy-now-vs-wait comparison.
    """
    down_pct = params.down_payment_pct / 100.0
    down_amount = int(round(params.purchase_price * down_pct))
    loan_amount = params.purchase_price - down_amount
    initial_ltv = loan_amount / params.purchase_price if params.purchase_price > 0 else 0.0
    pmi_applicable = initial_ltv > _PMI_LTV_THRESHOLD

    # Handle no-PMI case cleanly
    if not pmi_applicable:
        return {
            "purchase_price": params.purchase_price,
            "down_payment_pct": params.down_payment_pct,
            "down_payment_amount": down_amount,
            "loan_amount": loan_amount,
            "mortgage_rate": params.mortgage_rate,
            "annual_appreciation_pct": params.annual_appreciation_pct,
            "initial_ltv": round(initial_ltv, 4),
            "initial_ltv_pct": round(initial_ltv * 100, 1),
            "pmi_applicable": False,
            "current_pmi_rate_pct": 0.0,
            "monthly_pmi": 0,
            "annual_pmi": 0,
            "pmi_dropoff_month": None,
            "pmi_dropoff_years": None,
            "pmi_dropoff_description": None,
            "pmi_dropoff_via_amortization_only_month": None,
            "appreciation_acceleration_months": None,
            "total_pmi_cost": 0,
            "total_pmi_cost_description": "No PMI: down payment covers 20%+ of purchase price.",
            "ltv_brackets": [],
            "wait_analysis": None,
            "no_pmi_note": (
                f"No PMI: down payment of {params.down_payment_pct}% "
                f"exceeds the 80% LTV threshold."
            ),
        }

    # --- PMI simulation with appreciation ---
    snapshots = _simulate_pmi_timeline(
        loan_amount, params.purchase_price,
        params.mortgage_rate, params.annual_appreciation_pct,
    )

    # --- Amortization-only baseline ---
    amort_only_snapshots = _simulate_pmi_timeline(
        loan_amount, params.purchase_price,
        params.mortgage_rate, 0.0,
    )

    # Current PMI
    current_pmi_rate = _pmi_rate_for_ltv(initial_ltv)
    monthly_pmi = int(round(loan_amount * current_pmi_rate / 12))
    annual_pmi = monthly_pmi * 12

    # Drop-off months
    pmi_dropoff_month = snapshots[-1]["month"] if snapshots else None
    if snapshots and snapshots[-1]["ltv"] > _PMI_LTV_THRESHOLD:
        pmi_dropoff_month = None

    amort_only_dropoff = amort_only_snapshots[-1]["month"] if amort_only_snapshots else None
    if amort_only_snapshots and amort_only_snapshots[-1]["ltv"] > _PMI_LTV_THRESHOLD:
        amort_only_dropoff = None

    # Appreciation acceleration
    acceleration = None
    if amort_only_dropoff is not None and pmi_dropoff_month is not None:
        acceleration = amort_only_dropoff - pmi_dropoff_month

    # Drop-off description
    dropoff_desc = None
    dropoff_years = None
    if pmi_dropoff_month is not None:
        years = pmi_dropoff_month // 12
        months = pmi_dropoff_month % 12
        time_str = f"{years}y {months}m" if months else f"{years}y"
        dropoff_desc = f"PMI drops after {time_str}"
        dropoff_years = round(pmi_dropoff_month / 12, 1)

    # Total PMI cost
    total_pmi_cost = sum(s["monthly_pmi"] for s in snapshots)
    total_desc = f"${total_pmi_cost:,} total PMI paid before drop-off"

    # LTV brackets
    ltv_brackets = _compute_ltv_brackets(snapshots)

    # Buy-now-vs-wait
    wait_analysis = None
    if params.monthly_savings is not None:
        wait_analysis = _compute_wait_race(
            params.purchase_price,
            params.down_payment_pct,
            params.monthly_savings,
            params.wait_months,
            params.annual_appreciation_pct,
            params.mortgage_rate,
        )

    return {
        # Inputs echoed
        "purchase_price": params.purchase_price,
        "down_payment_pct": params.down_payment_pct,
        "down_payment_amount": down_amount,
        "loan_amount": loan_amount,
        "mortgage_rate": params.mortgage_rate,
        "annual_appreciation_pct": params.annual_appreciation_pct,
        # Current LTV and PMI
        "initial_ltv": round(initial_ltv, 4),
        "initial_ltv_pct": round(initial_ltv * 100, 1),
        "pmi_applicable": True,
        "current_pmi_rate_pct": round(current_pmi_rate * 100, 2),
        "monthly_pmi": monthly_pmi,
        "annual_pmi": annual_pmi,
        # Drop-off timeline
        "pmi_dropoff_month": pmi_dropoff_month,
        "pmi_dropoff_years": dropoff_years,
        "pmi_dropoff_description": dropoff_desc,
        "pmi_dropoff_via_amortization_only_month": amort_only_dropoff,
        "appreciation_acceleration_months": acceleration,
        # Total PMI cost
        "total_pmi_cost": total_pmi_cost,
        "total_pmi_cost_description": total_desc,
        # LTV bracket breakdown
        "ltv_brackets": ltv_brackets,
        # Buy-now-vs-wait
        "wait_analysis": wait_analysis,
        # Metadata
        "no_pmi_note": None,
    }
