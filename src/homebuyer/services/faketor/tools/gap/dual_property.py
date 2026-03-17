"""Dual property model for equity-leveraging investors.

Models combined cash flow for a primary residence + investment property:
  - HELOC or cash-out refi cost on the primary
  - Investment property cash flow (rent - expenses - debt service)
  - Combined monthly/annual cash flow
  - Stress tests: vacancy, rate increase, maintenance spike

All computation is pure — no DB access, no I/O.

Phase F-6 (#59) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass

from homebuyer.utils.mortgage import calc_monthly_payment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOAN_TERM_MONTHS = 360  # 30-year fixed

# HELOC defaults
_HELOC_RATE_DEFAULT = 8.5      # percent, variable
_HELOC_TERM_MONTHS = 120       # 10-year draw period

# Investment property defaults
_VACANCY_RATE_DEFAULT = 0.05   # 5% annual vacancy
_MGMT_FEE_PCT = 0.08          # 8% of gross rent
_MAINTENANCE_PCT = 0.01        # 1% of property value annually
_INSURANCE_RATE = 0.0040       # 0.40% of value annually
_PROPERTY_TAX_RATE = 0.0118    # Berkeley effective rate


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class DualPropertyParams:
    """Inputs for the dual property model."""

    # Primary residence (existing)
    primary_value: int                     # current market value
    primary_mortgage_balance: int = 0      # remaining balance
    primary_mortgage_rate: float = 3.25    # current rate (percent)
    primary_mortgage_remaining_months: int = 300

    # Equity extraction method
    extraction_method: str = "heloc"       # "heloc" or "cashout_refi"
    extraction_amount: int = 0             # how much to pull out
    heloc_rate: float = _HELOC_RATE_DEFAULT
    heloc_term_months: int = _HELOC_TERM_MONTHS
    cashout_refi_rate: float | None = None  # for cash-out refi (new rate)

    # Investment property
    investment_price: int = 0
    investment_down_payment_pct: float = 25.0  # percent
    investment_rate: float = 7.5               # percent (investor rate)
    investment_monthly_rent: int = 0
    investment_hoa: int = 0

    # Overrides for investment expenses
    vacancy_rate: float = _VACANCY_RATE_DEFAULT
    management_fee_pct: float = _MGMT_FEE_PCT
    maintenance_pct: float = _MAINTENANCE_PCT


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _monthly_pi(balance: int, rate_pct: float, term_months: int) -> int:
    """Compute monthly P&I, whole dollars."""
    if balance <= 0:
        return 0
    if rate_pct <= 0:
        return int(round(balance / term_months)) if term_months > 0 else 0
    return int(round(calc_monthly_payment(balance, rate_pct, term_months)))


def _compute_extraction_cost(params: DualPropertyParams) -> dict:
    """Compute the cost of extracting equity from primary."""
    if params.extraction_amount <= 0:
        return {
            "method": params.extraction_method,
            "extraction_amount": 0,
            "monthly_cost": 0,
            "new_primary_payment": _monthly_pi(
                params.primary_mortgage_balance,
                params.primary_mortgage_rate,
                params.primary_mortgage_remaining_months,
            ),
            "original_primary_payment": _monthly_pi(
                params.primary_mortgage_balance,
                params.primary_mortgage_rate,
                params.primary_mortgage_remaining_months,
            ),
            "monthly_increase": 0,
        }

    original_payment = _monthly_pi(
        params.primary_mortgage_balance,
        params.primary_mortgage_rate,
        params.primary_mortgage_remaining_months,
    )

    if params.extraction_method == "heloc":
        # HELOC: interest-only during draw period
        heloc_monthly = int(round(
            params.extraction_amount * (params.heloc_rate / 100) / 12
        ))
        new_total = original_payment + heloc_monthly
        return {
            "method": "heloc",
            "extraction_amount": params.extraction_amount,
            "heloc_rate": params.heloc_rate,
            "heloc_monthly_payment": heloc_monthly,
            "monthly_cost": heloc_monthly,
            "new_primary_payment": new_total,
            "original_primary_payment": original_payment,
            "monthly_increase": heloc_monthly,
        }
    else:
        # Cash-out refi: new mortgage at new rate covering both
        refi_rate = params.cashout_refi_rate or params.investment_rate
        new_balance = params.primary_mortgage_balance + params.extraction_amount
        new_payment = _monthly_pi(new_balance, refi_rate, _LOAN_TERM_MONTHS)
        monthly_increase = new_payment - original_payment
        return {
            "method": "cashout_refi",
            "extraction_amount": params.extraction_amount,
            "refi_rate": refi_rate,
            "new_balance": new_balance,
            "monthly_cost": new_payment,
            "new_primary_payment": new_payment,
            "original_primary_payment": original_payment,
            "monthly_increase": monthly_increase,
        }


def _compute_investment_cashflow(params: DualPropertyParams) -> dict:
    """Compute the investment property cash flow."""
    if params.investment_price <= 0:
        return {
            "monthly_gross_rent": 0,
            "effective_gross_rent": 0,
            "monthly_expenses": 0,
            "monthly_debt_service": 0,
            "monthly_net_cash_flow": 0,
            "annual_net_cash_flow": 0,
            "cap_rate_pct": 0.0,
            "expense_breakdown": {},
        }

    down_pct = params.investment_down_payment_pct / 100.0
    down_amount = int(round(params.investment_price * down_pct))
    loan_amount = params.investment_price - down_amount

    # Revenue
    monthly_gross = params.investment_monthly_rent
    vacancy_loss = int(round(monthly_gross * params.vacancy_rate))
    effective_gross = monthly_gross - vacancy_loss

    # Expenses
    monthly_tax = int(round(params.investment_price * _PROPERTY_TAX_RATE / 12))
    monthly_insurance = int(round(params.investment_price * _INSURANCE_RATE / 12))
    monthly_maintenance = int(round(
        params.investment_price * params.maintenance_pct / 12
    ))
    monthly_mgmt = int(round(monthly_gross * params.management_fee_pct))
    monthly_hoa = params.investment_hoa

    total_expenses = (
        monthly_tax + monthly_insurance + monthly_maintenance
        + monthly_mgmt + monthly_hoa
    )

    # Debt service
    monthly_ds = _monthly_pi(loan_amount, params.investment_rate, _LOAN_TERM_MONTHS)

    # Cash flow
    monthly_noi = effective_gross - total_expenses
    monthly_cf = monthly_noi - monthly_ds
    annual_noi = monthly_noi * 12

    # Cap rate
    cap_rate = round(annual_noi / params.investment_price * 100, 2) if params.investment_price > 0 else 0.0

    return {
        "investment_price": params.investment_price,
        "down_payment_amount": down_amount,
        "loan_amount": loan_amount,
        "monthly_gross_rent": monthly_gross,
        "vacancy_loss": vacancy_loss,
        "effective_gross_rent": effective_gross,
        "monthly_debt_service": monthly_ds,
        "monthly_noi": monthly_noi,
        "monthly_net_cash_flow": monthly_cf,
        "annual_net_cash_flow": monthly_cf * 12,
        "cap_rate_pct": cap_rate,
        "expense_breakdown": {
            "property_tax": monthly_tax,
            "insurance": monthly_insurance,
            "maintenance": monthly_maintenance,
            "management": monthly_mgmt,
            "hoa": monthly_hoa,
            "total": total_expenses,
        },
    }


def _run_stress_tests(
    params: DualPropertyParams,
    base_investment: dict,
    base_extraction: dict,
) -> list[dict]:
    """Run stress scenarios on the combined cash flow."""
    tests: list[dict] = []
    base_combined_cf = (
        base_investment["monthly_net_cash_flow"] - base_extraction["monthly_increase"]
    )

    # 1. High vacancy (15%)
    high_vac_params = DualPropertyParams(
        **{**_params_to_dict(params), "vacancy_rate": 0.15}
    )
    high_vac_inv = _compute_investment_cashflow(high_vac_params)
    high_vac_cf = high_vac_inv["monthly_net_cash_flow"] - base_extraction["monthly_increase"]
    tests.append({
        "scenario": "High vacancy (15%)",
        "monthly_cash_flow": high_vac_cf,
        "annual_cash_flow": high_vac_cf * 12,
        "delta_from_base": high_vac_cf - base_combined_cf,
        "is_positive": high_vac_cf > 0,
    })

    # 2. Rate increase (+2% on investment)
    rate_up_params = DualPropertyParams(
        **{**_params_to_dict(params), "investment_rate": params.investment_rate + 2.0}
    )
    rate_up_inv = _compute_investment_cashflow(rate_up_params)
    rate_up_cf = rate_up_inv["monthly_net_cash_flow"] - base_extraction["monthly_increase"]
    tests.append({
        "scenario": "Rate increase (+2%)",
        "monthly_cash_flow": rate_up_cf,
        "annual_cash_flow": rate_up_cf * 12,
        "delta_from_base": rate_up_cf - base_combined_cf,
        "is_positive": rate_up_cf > 0,
    })

    # 3. Maintenance spike (3% of value)
    maint_spike_params = DualPropertyParams(
        **{**_params_to_dict(params), "maintenance_pct": 0.03}
    )
    maint_spike_inv = _compute_investment_cashflow(maint_spike_params)
    maint_spike_cf = maint_spike_inv["monthly_net_cash_flow"] - base_extraction["monthly_increase"]
    tests.append({
        "scenario": "Maintenance spike (3%)",
        "monthly_cash_flow": maint_spike_cf,
        "annual_cash_flow": maint_spike_cf * 12,
        "delta_from_base": maint_spike_cf - base_combined_cf,
        "is_positive": maint_spike_cf > 0,
    })

    # 4. Combined: high vacancy + rate increase
    combined_params = DualPropertyParams(
        **{
            **_params_to_dict(params),
            "vacancy_rate": 0.15,
            "investment_rate": params.investment_rate + 2.0,
        }
    )
    combined_inv = _compute_investment_cashflow(combined_params)
    combined_cf = combined_inv["monthly_net_cash_flow"] - base_extraction["monthly_increase"]
    tests.append({
        "scenario": "High vacancy + rate increase",
        "monthly_cash_flow": combined_cf,
        "annual_cash_flow": combined_cf * 12,
        "delta_from_base": combined_cf - base_combined_cf,
        "is_positive": combined_cf > 0,
    })

    return tests


def _params_to_dict(params: DualPropertyParams) -> dict:
    """Convert dataclass to dict for override-based cloning."""
    return {
        "primary_value": params.primary_value,
        "primary_mortgage_balance": params.primary_mortgage_balance,
        "primary_mortgage_rate": params.primary_mortgage_rate,
        "primary_mortgage_remaining_months": params.primary_mortgage_remaining_months,
        "extraction_method": params.extraction_method,
        "extraction_amount": params.extraction_amount,
        "heloc_rate": params.heloc_rate,
        "heloc_term_months": params.heloc_term_months,
        "cashout_refi_rate": params.cashout_refi_rate,
        "investment_price": params.investment_price,
        "investment_down_payment_pct": params.investment_down_payment_pct,
        "investment_rate": params.investment_rate,
        "investment_monthly_rent": params.investment_monthly_rent,
        "investment_hoa": params.investment_hoa,
        "vacancy_rate": params.vacancy_rate,
        "management_fee_pct": params.management_fee_pct,
        "maintenance_pct": params.maintenance_pct,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_dual_property(params: DualPropertyParams) -> dict:
    """Run the dual property model.

    Returns combined cash flow, extraction cost, investment performance,
    and stress test results.
    """
    # Available equity
    available_equity = max(0, params.primary_value - params.primary_mortgage_balance)
    max_heloc = int(round(params.primary_value * 0.80 - params.primary_mortgage_balance))
    max_heloc = max(0, max_heloc)

    # Extraction cost
    extraction = _compute_extraction_cost(params)

    # Investment cash flow
    investment = _compute_investment_cashflow(params)

    # Combined cash flow
    combined_monthly = (
        investment["monthly_net_cash_flow"] - extraction["monthly_increase"]
    )
    combined_annual = combined_monthly * 12

    # Cash-on-cash return (based on total cash invested)
    inv_down = investment.get("down_payment_amount", 0)
    total_cash_invested = inv_down  # down payment + any closing costs
    cash_on_cash = (
        round(combined_annual / total_cash_invested * 100, 2)
        if total_cash_invested > 0 else 0.0
    )

    # Stress tests
    stress_tests = _run_stress_tests(params, investment, extraction)
    worst_case = min(stress_tests, key=lambda s: s["monthly_cash_flow"])

    return {
        # Primary context
        "primary_value": params.primary_value,
        "primary_mortgage_balance": params.primary_mortgage_balance,
        "available_equity": available_equity,
        "max_heloc_amount": max_heloc,
        # Extraction
        "extraction": extraction,
        # Investment property
        "investment": investment,
        # Combined
        "combined_monthly_cash_flow": combined_monthly,
        "combined_annual_cash_flow": combined_annual,
        "cash_on_cash_pct": cash_on_cash,
        "is_cash_flow_positive": combined_monthly > 0,
        # Stress tests
        "stress_tests": stress_tests,
        "worst_case_scenario": worst_case["scenario"],
        "worst_case_monthly": worst_case["monthly_cash_flow"],
        "survives_worst_case": worst_case["is_positive"],
    }
