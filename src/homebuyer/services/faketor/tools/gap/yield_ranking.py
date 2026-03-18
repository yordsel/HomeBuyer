"""Yield ranking for leveraged investors.

Ranks properties by leverage spread (cap rate - borrowing cost), DSCR,
and cash-on-cash return at specified down payment and rate.

All computation is pure — no DB access, no I/O.

Phase F-7 (#60) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from homebuyer.utils.mortgage import calc_monthly_payment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOAN_TERM_MONTHS = 360
_PROPERTY_TAX_RATE = 0.0118
_INSURANCE_RATE = 0.0040
_MAINTENANCE_PCT = 0.01
_VACANCY_RATE = 0.05
_MGMT_FEE_PCT = 0.08


# ---------------------------------------------------------------------------
# Input parameters
# ---------------------------------------------------------------------------


@dataclass
class PropertyForRanking:
    """One property in the ranking set."""

    address: str = ""
    price: int = 0
    monthly_rent: int = 0
    hoa_monthly: int = 0
    property_id: int | None = None


@dataclass
class YieldRankingParams:
    """Inputs for the yield ranking analysis."""

    properties: list[PropertyForRanking] = field(default_factory=list)
    down_payment_pct: float = 25.0    # investor down payment (percent)
    mortgage_rate: float = 7.5        # investor rate (percent)
    vacancy_rate: float = _VACANCY_RATE
    management_fee_pct: float = _MGMT_FEE_PCT


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_yield_ranking(params: YieldRankingParams) -> dict:
    """Rank properties by leverage spread, DSCR, and cash-on-cash."""
    rankings: list[dict] = []
    down_pct = params.down_payment_pct / 100.0

    for prop in params.properties:
        if prop.price <= 0:
            continue

        down = int(round(prop.price * down_pct))
        loan = prop.price - down

        # Revenue
        gross_rent = prop.monthly_rent
        vacancy = int(round(gross_rent * params.vacancy_rate))
        effective_rent = gross_rent - vacancy

        # Expenses
        tax = int(round(prop.price * _PROPERTY_TAX_RATE / 12))
        insurance = int(round(prop.price * _INSURANCE_RATE / 12))
        maintenance = int(round(prop.price * _MAINTENANCE_PCT / 12))
        mgmt = int(round(gross_rent * params.management_fee_pct))
        total_expenses = tax + insurance + maintenance + mgmt + prop.hoa_monthly

        # NOI
        monthly_noi = effective_rent - total_expenses
        annual_noi = monthly_noi * 12

        # Cap rate
        cap_rate = round(annual_noi / prop.price * 100, 2) if prop.price > 0 else 0.0

        # Debt service
        if loan > 0 and params.mortgage_rate > 0:
            monthly_ds = int(round(
                calc_monthly_payment(loan, params.mortgage_rate, _LOAN_TERM_MONTHS)
            ))
        else:
            monthly_ds = 0

        annual_ds = monthly_ds * 12

        # DSCR (debt service coverage ratio)
        dscr = round(annual_noi / annual_ds, 2) if annual_ds > 0 else 999.0

        # Cash flow
        monthly_cf = monthly_noi - monthly_ds
        annual_cf = monthly_cf * 12

        # Cash-on-cash return
        cash_on_cash = round(annual_cf / down * 100, 2) if down > 0 else 0.0

        # Leverage spread = cap rate - borrowing cost
        leverage_spread = round(cap_rate - params.mortgage_rate, 2)

        rankings.append({
            "address": prop.address,
            "property_id": prop.property_id,
            "price": prop.price,
            "monthly_rent": prop.monthly_rent,
            "down_payment": down,
            "loan_amount": loan,
            "monthly_noi": monthly_noi,
            "annual_noi": annual_noi,
            "cap_rate_pct": cap_rate,
            "monthly_debt_service": monthly_ds,
            "dscr": dscr,
            "monthly_cash_flow": monthly_cf,
            "annual_cash_flow": annual_cf,
            "cash_on_cash_pct": cash_on_cash,
            "leverage_spread_pct": leverage_spread,
        })

    # Sort by leverage spread descending (best first)
    by_spread = sorted(rankings, key=lambda r: r["leverage_spread_pct"], reverse=True)
    by_dscr = sorted(rankings, key=lambda r: r["dscr"], reverse=True)
    by_coc = sorted(rankings, key=lambda r: r["cash_on_cash_pct"], reverse=True)

    # Summary
    positive_cf = [r for r in rankings if r["monthly_cash_flow"] > 0]
    negative_spread = [r for r in rankings if r["leverage_spread_pct"] < 0]

    return {
        "down_payment_pct": params.down_payment_pct,
        "mortgage_rate": params.mortgage_rate,
        "property_count": len(rankings),
        "positive_cash_flow_count": len(positive_cf),
        "negative_spread_count": len(negative_spread),
        "ranked_by_spread": by_spread,
        "ranked_by_dscr": by_dscr,
        "ranked_by_cash_on_cash": by_coc,
        "best_leverage_spread": by_spread[0] if by_spread else None,
        "best_dscr": by_dscr[0] if by_dscr else None,
        "best_cash_on_cash": by_coc[0] if by_coc else None,
    }
