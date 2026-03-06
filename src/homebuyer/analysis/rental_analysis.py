"""Rental income and investment scenario analysis for Berkeley properties.

Provides rent estimation, expense modeling, mortgage analysis, tax benefits,
cash flow projections, and multi-scenario comparison (as-is, ADU, SB9, multi-unit).

This module is the shared computation engine used by both API endpoints (UI cards)
and Faketor AI chat tools.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RentEstimate:
    """Estimated monthly rent for a single unit."""

    unit_type: str  # "main_house", "adu", "sb9_unit_a", "sb9_unit_b"
    beds: int
    baths: float
    sqft: Optional[int]
    monthly_rent: int
    annual_rent: int
    estimation_method: str  # "neighborhood_ratio", "value_ratio", "bedroom_table"
    confidence: str  # "high", "medium", "low"
    notes: str = ""


@dataclass
class ExpenseBreakdown:
    """Itemized annual operating expenses."""

    property_tax: int
    insurance: int
    maintenance: int
    vacancy_reserve: int
    management_fee: int
    hoa: int = 0
    utilities: int = 0
    total_annual: int = 0
    expense_ratio_pct: float = 0.0


@dataclass
class MortgageAnalysis:
    """Mortgage terms and amortization summary."""

    property_value: int
    down_payment_pct: float
    down_payment_amount: int
    loan_amount: int
    rate_30yr: float
    monthly_pi: int  # principal + interest
    monthly_tax: int
    monthly_insurance: int
    monthly_piti: int
    is_jumbo: bool
    annual_interest_yr1: int
    annual_principal_yr1: int


@dataclass
class TaxBenefits:
    """Estimated annual tax benefits from rental property ownership."""

    depreciation_annual: int
    mortgage_interest_deduction: int
    operating_expense_deductions: int
    estimated_tax_savings: int
    marginal_tax_rate_used: float
    notes: list[str] = field(default_factory=list)


@dataclass
class AnnualCashFlow:
    """Single-year cash flow projection."""

    year: int
    gross_rent: int
    operating_expenses: int
    noi: int
    mortgage_payment: int
    cash_flow: int
    equity_buildup: int
    property_value: int
    cumulative_equity: int
    total_return: int


@dataclass
class InvestmentScenario:
    """Complete investment analysis for a single scenario."""

    scenario_name: str
    scenario_type: str  # "as_is", "adu", "sb9", "multi_unit"

    # Upfront costs
    property_value: int
    additional_investment: int
    total_investment: int

    # Unit rent estimates
    units: list[RentEstimate]
    total_monthly_rent: int
    total_annual_rent: int

    # Expenses and cash flow
    expenses: ExpenseBreakdown
    mortgage: MortgageAnalysis

    # Key metrics
    cap_rate_pct: float
    cash_on_cash_pct: float
    gross_rent_multiplier: float
    price_to_rent_ratio: float
    monthly_cash_flow: int

    # Projections
    projections: list[AnnualCashFlow]

    # Tax benefits
    tax_benefits: TaxBenefits

    # Development-specific
    development_feasible: bool = True
    development_notes: str = ""


@dataclass
class RentalAnalysisResponse:
    """Complete rental income and investment analysis."""

    property_address: Optional[str]
    property_value: int
    neighborhood: str
    scenarios: list[InvestmentScenario]
    best_scenario: str
    recommendation_notes: str
    data_sources: list[str]
    disclaimers: list[str]


# ---------------------------------------------------------------------------
# Berkeley-specific constants
# ---------------------------------------------------------------------------

# Base rent estimates by bedroom count (Berkeley 2025-26, monthly)
_BASE_RENTS = {
    0: 1800,  # studio
    1: 2200,
    2: 3000,
    3: 3800,
    4: 4500,
    5: 5200,
}

# Per-sqft monthly rent for ADUs (~$3.25/sqft in Berkeley)
_ADU_RENT_PER_SQFT = 3.25

# Price-to-rent ratios by property type (annual gross rent)
_PTR_SFH = 25.0
_PTR_MULTI = 20.0

# Expense rates
_PROPERTY_TAX_RATE = 0.0117  # 1.17% (Berkeley)
_INSURANCE_RATE = 0.0035  # 0.35% of value
_MAINTENANCE_RATE = 0.01  # 1% of value annually
_VACANCY_RATE = 0.05  # 5% of gross rent
_MANAGEMENT_FEE_RATE = 0.08  # 8% of gross rent

# Appreciation and growth
_DEFAULT_APPRECIATION = 0.04  # 4% Berkeley long-term
_DEFAULT_RENT_GROWTH = 0.03  # 3% annual rent growth

# Tax
_DEPRECIATION_YEARS = 27.5
_LAND_VALUE_PCT = 0.40  # ~40% land value in Berkeley
_DEFAULT_MARGINAL_TAX_RATE = 0.35  # combined federal + CA state

# Construction costs
_ADU_COST_PER_SQFT = 400  # $400/sqft (Berkeley avg)
_SB9_SPLIT_COST = 150_000  # approximate SB9 process + construction

# Mortgage
_JUMBO_THRESHOLD = 766_550  # 2025 conforming limit (Alameda County)
_DEFAULT_RATE = 6.5  # fallback if no DB data


# ---------------------------------------------------------------------------
# RentalAnalyzer
# ---------------------------------------------------------------------------


class RentalAnalyzer:
    """Comprehensive rental income and investment analysis for Berkeley properties.

    Shared computation module callable by both API endpoints and Faketor tools.
    """

    def __init__(self, db: Database, dev_calc=None) -> None:
        self.db = db
        self.dev_calc = dev_calc

    # ------------------------------------------------------------------
    # Rent estimation
    # ------------------------------------------------------------------

    def estimate_rent(
        self,
        beds: int,
        baths: float = 1.0,
        sqft: Optional[int] = None,
        neighborhood: Optional[str] = None,
        property_value: Optional[int] = None,
        unit_type: str = "main_house",
    ) -> RentEstimate:
        """Estimate monthly rent for a unit using a 3-tier strategy.

        1. Neighborhood-derived: scale base rent by neighborhood price tier
        2. Property-value ratio: value / price-to-rent ratio / 12
        3. Bedroom table fallback
        """
        beds_clamped = max(0, min(beds, 5))

        # Tier 1: Neighborhood-adjusted rent
        if neighborhood:
            nbr_factor = self._neighborhood_rent_factor(neighborhood)
            if nbr_factor is not None:
                base = _BASE_RENTS.get(beds_clamped, 3500)
                monthly = int(round(base * nbr_factor, -1))  # round to $10
                # Adjust for sqft if available (scale around typical sqft for bed count)
                if sqft and unit_type == "main_house":
                    typical_sqft = {0: 500, 1: 700, 2: 1000, 3: 1400, 4: 1800, 5: 2200}
                    typ = typical_sqft.get(beds_clamped, 1400)
                    sqft_ratio = min(max(sqft / typ, 0.7), 1.5)
                    monthly = int(round(monthly * sqft_ratio, -1))
                return RentEstimate(
                    unit_type=unit_type,
                    beds=beds,
                    baths=baths,
                    sqft=sqft,
                    monthly_rent=monthly,
                    annual_rent=monthly * 12,
                    estimation_method="neighborhood_ratio",
                    confidence="medium",
                    notes=f"Scaled by {neighborhood} price tier (factor {nbr_factor:.2f})",
                )

        # Tier 2: Property-value-based ratio
        if property_value and property_value > 0:
            ptr = _PTR_SFH
            monthly = int(round(property_value / ptr / 12, -1))
            return RentEstimate(
                unit_type=unit_type,
                beds=beds,
                baths=baths,
                sqft=sqft,
                monthly_rent=monthly,
                annual_rent=monthly * 12,
                estimation_method="value_ratio",
                confidence="medium",
                notes=f"Based on price-to-rent ratio of {ptr}",
            )

        # Tier 3: Bedroom table fallback
        monthly = _BASE_RENTS.get(beds_clamped, 3500)
        return RentEstimate(
            unit_type=unit_type,
            beds=beds,
            baths=baths,
            sqft=sqft,
            monthly_rent=monthly,
            annual_rent=monthly * 12,
            estimation_method="bedroom_table",
            confidence="low",
            notes="Berkeley average by bedroom count (no neighborhood data)",
        )

    def estimate_adu_rent(self, adu_sqft: int) -> RentEstimate:
        """Estimate rent for an ADU based on size."""
        monthly = int(round(adu_sqft * _ADU_RENT_PER_SQFT, -1))
        # ADUs are typically 1br/1ba
        beds = 1 if adu_sqft >= 400 else 0
        baths = 1.0
        return RentEstimate(
            unit_type="adu",
            beds=beds,
            baths=baths,
            sqft=adu_sqft,
            monthly_rent=monthly,
            annual_rent=monthly * 12,
            estimation_method="adu_per_sqft",
            confidence="medium",
            notes=f"ADU rent at ${_ADU_RENT_PER_SQFT:.2f}/sqft/month",
        )

    def _neighborhood_rent_factor(self, neighborhood: str) -> Optional[float]:
        """Get a rent scaling factor based on neighborhood median price vs city median.

        Returns a float (e.g. 1.15 = 15% above city average), or None if
        insufficient data.
        """
        try:
            # City-wide median price per sqft
            city_row = self.db.conn.execute(
                """
                SELECT AVG(price_per_sqft) as city_ppsf
                FROM property_sales
                WHERE price_per_sqft IS NOT NULL
                  AND sale_date >= date('now', '-2 years')
                """
            ).fetchone()
            if not city_row or not city_row["city_ppsf"]:
                return None

            # Neighborhood median price per sqft
            nbr_row = self.db.conn.execute(
                """
                SELECT AVG(price_per_sqft) as nbr_ppsf
                FROM property_sales
                WHERE price_per_sqft IS NOT NULL
                  AND neighborhood_normalized = ?
                  AND sale_date >= date('now', '-2 years')
                """,
                (neighborhood,),
            ).fetchone()
            if not nbr_row or not nbr_row["nbr_ppsf"]:
                return None

            factor = nbr_row["nbr_ppsf"] / city_row["city_ppsf"]
            # Clamp to reasonable range (0.6x - 2.0x)
            return max(0.6, min(factor, 2.0))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Expense calculation
    # ------------------------------------------------------------------

    def calculate_expenses(
        self,
        property_value: int,
        annual_gross_rent: int,
        hoa: int = 0,
        self_managed: bool = True,
    ) -> ExpenseBreakdown:
        """Calculate itemized annual operating expenses."""
        prop_tax = int(round(property_value * _PROPERTY_TAX_RATE))
        insurance = int(round(property_value * _INSURANCE_RATE))
        maintenance = int(round(property_value * _MAINTENANCE_RATE))
        vacancy = int(round(annual_gross_rent * _VACANCY_RATE))
        mgmt = 0 if self_managed else int(round(annual_gross_rent * _MANAGEMENT_FEE_RATE))

        total = prop_tax + insurance + maintenance + vacancy + mgmt + hoa
        ratio = round(total / annual_gross_rent * 100, 1) if annual_gross_rent > 0 else 0.0

        return ExpenseBreakdown(
            property_tax=prop_tax,
            insurance=insurance,
            maintenance=maintenance,
            vacancy_reserve=vacancy,
            management_fee=mgmt,
            hoa=hoa,
            total_annual=total,
            expense_ratio_pct=ratio,
        )

    # ------------------------------------------------------------------
    # Mortgage analysis
    # ------------------------------------------------------------------

    def analyze_mortgage(
        self,
        property_value: int,
        down_payment_pct: float = 20.0,
        rate_override: Optional[float] = None,
    ) -> MortgageAnalysis:
        """Compute mortgage terms using current DB rates or override."""
        # Get current rate from DB
        if rate_override is not None:
            rate_30yr = rate_override
        else:
            rate_30yr = self._get_current_mortgage_rate()

        down_pct = down_payment_pct / 100.0
        down_amount = int(round(property_value * down_pct))
        loan_amount = property_value - down_amount
        is_jumbo = loan_amount > _JUMBO_THRESHOLD

        # Monthly P&I (standard 30-year amortization)
        monthly_rate = (rate_30yr / 100) / 12
        n_payments = 360
        if monthly_rate > 0 and loan_amount > 0:
            monthly_pi = int(
                math.ceil(
                    loan_amount
                    * (monthly_rate * (1 + monthly_rate) ** n_payments)
                    / ((1 + monthly_rate) ** n_payments - 1)
                )
            )
        else:
            monthly_pi = 0

        monthly_tax = int(round(property_value * _PROPERTY_TAX_RATE / 12))
        monthly_ins = int(round(property_value * _INSURANCE_RATE / 12))
        monthly_piti = monthly_pi + monthly_tax + monthly_ins

        # First-year interest vs principal split
        annual_interest_yr1 = 0
        annual_principal_yr1 = 0
        balance = loan_amount
        for _ in range(12):
            interest = balance * monthly_rate
            principal = monthly_pi - interest
            if principal < 0:
                principal = 0
            annual_interest_yr1 += interest
            annual_principal_yr1 += principal
            balance -= principal

        return MortgageAnalysis(
            property_value=property_value,
            down_payment_pct=down_payment_pct,
            down_payment_amount=down_amount,
            loan_amount=loan_amount,
            rate_30yr=rate_30yr,
            monthly_pi=monthly_pi,
            monthly_tax=monthly_tax,
            monthly_insurance=monthly_ins,
            monthly_piti=monthly_piti,
            is_jumbo=is_jumbo,
            annual_interest_yr1=int(round(annual_interest_yr1)),
            annual_principal_yr1=int(round(annual_principal_yr1)),
        )

    def _get_current_mortgage_rate(self) -> float:
        """Query the latest 30yr mortgage rate from the DB."""
        try:
            row = self.db.conn.execute(
                """
                SELECT rate_30yr FROM mortgage_rates
                WHERE rate_30yr IS NOT NULL
                ORDER BY observation_date DESC LIMIT 1
                """
            ).fetchone()
            return row["rate_30yr"] if row else _DEFAULT_RATE
        except Exception:
            return _DEFAULT_RATE

    # ------------------------------------------------------------------
    # Tax benefits
    # ------------------------------------------------------------------

    def estimate_tax_benefits(
        self,
        property_value: int,
        mortgage: MortgageAnalysis,
        expenses: ExpenseBreakdown,
        marginal_rate: float = _DEFAULT_MARGINAL_TAX_RATE,
    ) -> TaxBenefits:
        """Estimate annual tax benefits from rental property ownership."""
        building_value = int(property_value * (1 - _LAND_VALUE_PCT))
        depreciation = int(round(building_value / _DEPRECIATION_YEARS))

        interest_deduction = mortgage.annual_interest_yr1
        # Deductible operating expenses (tax + insurance + maintenance + mgmt)
        op_deductions = (
            expenses.property_tax
            + expenses.insurance
            + expenses.maintenance
            + expenses.management_fee
        )

        total_deductions = depreciation + interest_deduction + op_deductions
        tax_savings = int(round(total_deductions * marginal_rate))

        notes = [
            f"Building value estimated at {100 - int(_LAND_VALUE_PCT * 100)}% of property value",
            f"Depreciated over {_DEPRECIATION_YEARS} years (straight-line)",
            f"Tax savings assume {marginal_rate:.0%} combined marginal rate",
            "Consult a tax professional for actual tax impact",
        ]

        return TaxBenefits(
            depreciation_annual=depreciation,
            mortgage_interest_deduction=interest_deduction,
            operating_expense_deductions=op_deductions,
            estimated_tax_savings=tax_savings,
            marginal_tax_rate_used=marginal_rate,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Cash flow projections
    # ------------------------------------------------------------------

    def project_cash_flow(
        self,
        property_value: int,
        annual_gross_rent: int,
        expenses: ExpenseBreakdown,
        mortgage: MortgageAnalysis,
        appreciation_rate: Optional[float] = None,
        rent_growth_rate: float = _DEFAULT_RENT_GROWTH,
        years: list[int] | None = None,
    ) -> list[AnnualCashFlow]:
        """Project cash flow over multiple horizons."""
        if years is None:
            years = [1, 5, 10, 20]
        if appreciation_rate is None:
            appreciation_rate = _DEFAULT_APPRECIATION

        max_year = max(years)
        projections: list[AnnualCashFlow] = []

        # Track running amortization
        balance = mortgage.loan_amount
        monthly_rate = (mortgage.rate_30yr / 100) / 12
        cumulative_principal = 0
        cumulative_cash_flow = 0

        for yr in range(1, max_year + 1):
            # Grow rent and property value
            rent_factor = (1 + rent_growth_rate) ** (yr - 1)
            value_factor = (1 + appreciation_rate) ** yr

            yr_gross_rent = int(round(annual_gross_rent * rent_factor))
            yr_property_value = int(round(property_value * value_factor))

            # Expenses grow with property value (tax, insurance, maintenance)
            # and with rent (vacancy, management)
            yr_expenses = int(round(
                yr_property_value * (_PROPERTY_TAX_RATE + _INSURANCE_RATE + _MAINTENANCE_RATE)
                + yr_gross_rent * _VACANCY_RATE
                + (yr_gross_rent * _MANAGEMENT_FEE_RATE if expenses.management_fee > 0 else 0)
                + expenses.hoa
            ))

            yr_noi = yr_gross_rent - yr_expenses
            yr_mortgage = mortgage.monthly_pi * 12

            # Principal paid this year
            yr_principal = 0
            for _ in range(12):
                if balance <= 0:
                    break
                interest = balance * monthly_rate
                principal = min(mortgage.monthly_pi - interest, balance)
                if principal < 0:
                    principal = 0
                yr_principal += principal
                balance -= principal

            cumulative_principal += yr_principal
            yr_cash_flow = yr_noi - yr_mortgage
            cumulative_cash_flow += yr_cash_flow

            appreciation_gain = yr_property_value - property_value
            cum_equity = (
                mortgage.down_payment_amount
                + int(round(cumulative_principal))
                + appreciation_gain
            )

            yr_total_return = yr_cash_flow + int(round(yr_principal)) + (
                int(round(property_value * appreciation_rate))
            )

            if yr in years:
                projections.append(
                    AnnualCashFlow(
                        year=yr,
                        gross_rent=yr_gross_rent,
                        operating_expenses=yr_expenses,
                        noi=yr_noi,
                        mortgage_payment=yr_mortgage,
                        cash_flow=yr_cash_flow,
                        equity_buildup=int(round(yr_principal)),
                        property_value=yr_property_value,
                        cumulative_equity=cum_equity,
                        total_return=yr_total_return,
                    )
                )

        return projections

    # ------------------------------------------------------------------
    # Scenario builders
    # ------------------------------------------------------------------

    def build_scenario_as_is(
        self,
        property_dict: dict,
        down_payment_pct: float = 20.0,
        self_managed: bool = True,
    ) -> InvestmentScenario:
        """Build 'Rent As-Is' scenario."""
        value = self._resolve_property_value(property_dict)
        beds = int(property_dict.get("beds") or 3)
        baths = float(property_dict.get("baths") or 2.0)
        sqft = property_dict.get("sqft")
        neighborhood = property_dict.get("neighborhood")
        hoa = int(property_dict.get("hoa_per_month") or 0) * 12

        rent = self.estimate_rent(
            beds=beds,
            baths=baths,
            sqft=sqft,
            neighborhood=neighborhood,
            property_value=value,
            unit_type="main_house",
        )

        expenses = self.calculate_expenses(value, rent.annual_rent, hoa=hoa, self_managed=self_managed)
        mortgage = self.analyze_mortgage(value, down_payment_pct)
        tax_benefits = self.estimate_tax_benefits(value, mortgage, expenses)

        appreciation = self._get_neighborhood_appreciation(neighborhood)
        projections = self.project_cash_flow(
            value, rent.annual_rent, expenses, mortgage,
            appreciation_rate=appreciation,
        )

        noi = rent.annual_rent - expenses.total_annual
        annual_mortgage = mortgage.monthly_pi * 12
        annual_cf = noi - annual_mortgage
        cash_invested = mortgage.down_payment_amount

        return InvestmentScenario(
            scenario_name="Rent As-Is",
            scenario_type="as_is",
            property_value=value,
            additional_investment=0,
            total_investment=value,
            units=[rent],
            total_monthly_rent=rent.monthly_rent,
            total_annual_rent=rent.annual_rent,
            expenses=expenses,
            mortgage=mortgage,
            cap_rate_pct=round(noi / value * 100, 2) if value > 0 else 0.0,
            cash_on_cash_pct=round(annual_cf / cash_invested * 100, 2) if cash_invested > 0 else 0.0,
            gross_rent_multiplier=round(value / rent.annual_rent, 1) if rent.annual_rent > 0 else 0.0,
            price_to_rent_ratio=round(value / rent.annual_rent, 1) if rent.annual_rent > 0 else 0.0,
            monthly_cash_flow=int(round(annual_cf / 12)),
            projections=projections,
            tax_benefits=tax_benefits,
        )

    def build_scenario_adu(
        self,
        property_dict: dict,
        dev_potential,
        down_payment_pct: float = 20.0,
        self_managed: bool = True,
    ) -> Optional[InvestmentScenario]:
        """Build 'Add ADU' scenario if ADU is feasible."""
        if not dev_potential or not dev_potential.adu or not dev_potential.adu.eligible:
            return None

        value = self._resolve_property_value(property_dict)
        beds = int(property_dict.get("beds") or 3)
        baths = float(property_dict.get("baths") or 2.0)
        sqft = property_dict.get("sqft")
        neighborhood = property_dict.get("neighborhood")
        hoa = int(property_dict.get("hoa_per_month") or 0) * 12

        adu_sqft = dev_potential.adu.max_adu_sqft or 800
        adu_cost = self._get_adu_construction_cost(adu_sqft)

        # Main house rent
        main_rent = self.estimate_rent(
            beds=beds, baths=baths, sqft=sqft,
            neighborhood=neighborhood, property_value=value,
            unit_type="main_house",
        )

        # ADU rent
        adu_rent = self.estimate_adu_rent(adu_sqft)

        total_monthly = main_rent.monthly_rent + adu_rent.monthly_rent
        total_annual = total_monthly * 12
        total_value = value + adu_cost

        expenses = self.calculate_expenses(total_value, total_annual, hoa=hoa, self_managed=self_managed)
        mortgage = self.analyze_mortgage(value, down_payment_pct)  # mortgage on original value
        tax_benefits = self.estimate_tax_benefits(total_value, mortgage, expenses)

        appreciation = self._get_neighborhood_appreciation(neighborhood)
        projections = self.project_cash_flow(
            total_value, total_annual, expenses, mortgage,
            appreciation_rate=appreciation,
        )

        noi = total_annual - expenses.total_annual
        annual_mortgage = mortgage.monthly_pi * 12
        annual_cf = noi - annual_mortgage
        cash_invested = mortgage.down_payment_amount + adu_cost

        return InvestmentScenario(
            scenario_name="Add ADU",
            scenario_type="adu",
            property_value=value,
            additional_investment=adu_cost,
            total_investment=value + adu_cost,
            units=[main_rent, adu_rent],
            total_monthly_rent=total_monthly,
            total_annual_rent=total_annual,
            expenses=expenses,
            mortgage=mortgage,
            cap_rate_pct=round(noi / total_value * 100, 2) if total_value > 0 else 0.0,
            cash_on_cash_pct=round(annual_cf / cash_invested * 100, 2) if cash_invested > 0 else 0.0,
            gross_rent_multiplier=round(total_value / total_annual, 1) if total_annual > 0 else 0.0,
            price_to_rent_ratio=round(total_value / total_annual, 1) if total_annual > 0 else 0.0,
            monthly_cash_flow=int(round(annual_cf / 12)),
            projections=projections,
            tax_benefits=tax_benefits,
            development_notes=f"ADU: {adu_sqft} sqft, estimated construction cost ${adu_cost:,}",
        )

    def build_scenario_sb9(
        self,
        property_dict: dict,
        dev_potential,
        down_payment_pct: float = 20.0,
        self_managed: bool = True,
    ) -> Optional[InvestmentScenario]:
        """Build 'SB9 Lot Split' scenario if eligible."""
        if not dev_potential or not dev_potential.sb9 or not dev_potential.sb9.can_split:
            return None

        value = self._resolve_property_value(property_dict)
        neighborhood = property_dict.get("neighborhood")
        hoa = int(property_dict.get("hoa_per_month") or 0) * 12
        lot_sizes = dev_potential.sb9.resulting_lot_sizes or []

        # Model 2 units: keep existing house + build new unit on split lot
        beds_a = int(property_dict.get("beds") or 3)
        baths_a = float(property_dict.get("baths") or 2.0)
        sqft_a = property_dict.get("sqft")

        # New unit on split lot: typically 2br/1ba, ~1000 sqft
        beds_b = 2
        baths_b = 1.0
        sqft_b = 1000

        unit_a = self.estimate_rent(
            beds=beds_a, baths=baths_a, sqft=sqft_a,
            neighborhood=neighborhood, property_value=value,
            unit_type="sb9_unit_a",
        )
        unit_b = self.estimate_rent(
            beds=beds_b, baths=baths_b, sqft=sqft_b,
            neighborhood=neighborhood,
            unit_type="sb9_unit_b",
        )

        total_monthly = unit_a.monthly_rent + unit_b.monthly_rent
        total_annual = total_monthly * 12
        total_value = value + _SB9_SPLIT_COST

        expenses = self.calculate_expenses(total_value, total_annual, hoa=hoa, self_managed=self_managed)
        mortgage = self.analyze_mortgage(value, down_payment_pct)
        tax_benefits = self.estimate_tax_benefits(total_value, mortgage, expenses)

        appreciation = self._get_neighborhood_appreciation(neighborhood)
        projections = self.project_cash_flow(
            total_value, total_annual, expenses, mortgage,
            appreciation_rate=appreciation,
        )

        noi = total_annual - expenses.total_annual
        annual_mortgage = mortgage.monthly_pi * 12
        annual_cf = noi - annual_mortgage
        cash_invested = mortgage.down_payment_amount + _SB9_SPLIT_COST

        lot_info = f"Resulting lots: {', '.join(str(s) for s in lot_sizes)} sqft" if lot_sizes else ""

        return InvestmentScenario(
            scenario_name="SB 9 Lot Split",
            scenario_type="sb9",
            property_value=value,
            additional_investment=_SB9_SPLIT_COST,
            total_investment=value + _SB9_SPLIT_COST,
            units=[unit_a, unit_b],
            total_monthly_rent=total_monthly,
            total_annual_rent=total_annual,
            expenses=expenses,
            mortgage=mortgage,
            cap_rate_pct=round(noi / total_value * 100, 2) if total_value > 0 else 0.0,
            cash_on_cash_pct=round(annual_cf / cash_invested * 100, 2) if cash_invested > 0 else 0.0,
            gross_rent_multiplier=round(total_value / total_annual, 1) if total_annual > 0 else 0.0,
            price_to_rent_ratio=round(total_value / total_annual, 1) if total_annual > 0 else 0.0,
            monthly_cash_flow=int(round(annual_cf / 12)),
            projections=projections,
            tax_benefits=tax_benefits,
            development_notes=(
                f"SB 9 lot split with new 2br/1ba unit. "
                f"Estimated split + construction cost: ${_SB9_SPLIT_COST:,}. {lot_info}"
            ),
        )

    def build_scenario_multi_unit(
        self,
        property_dict: dict,
        dev_potential,
        down_payment_pct: float = 20.0,
        self_managed: bool = True,
    ) -> Optional[InvestmentScenario]:
        """Build multi-unit development scenario if zoning allows > 2 units."""
        if (
            not dev_potential
            or not dev_potential.units
            or dev_potential.units.effective_max_units <= 2
        ):
            return None

        value = self._resolve_property_value(property_dict)
        neighborhood = property_dict.get("neighborhood")
        max_units = dev_potential.units.effective_max_units
        lot_size = property_dict.get("lot_size_sqft") or 5000

        # Model multi-unit: tear down and build to max density
        # Estimate unit sizes based on lot and coverage
        coverage_pct = 0.50  # typical multi-family
        if dev_potential.zone_rule:
            coverage_pct = dev_potential.zone_rule.max_lot_coverage_pct

        total_building_sqft = int(lot_size * coverage_pct * 2)  # 2 stories typical
        per_unit_sqft = max(500, total_building_sqft // max_units)

        # Construction cost: ~$350/sqft for multi-family in Berkeley
        construction_cost = total_building_sqft * 350
        # Less demolition credit of existing structure
        demolition_credit = 0  # conservative

        additional = construction_cost - demolition_credit

        units = []
        for i in range(max_units):
            # Mix of 1br and 2br units
            if i < max_units // 2:
                beds, baths = 2, 1.0
            else:
                beds, baths = 1, 1.0
            unit = self.estimate_rent(
                beds=beds, baths=baths, sqft=per_unit_sqft,
                neighborhood=neighborhood,
                unit_type=f"unit_{i + 1}",
            )
            units.append(unit)

        total_monthly = sum(u.monthly_rent for u in units)
        total_annual = total_monthly * 12
        total_value = value + additional

        expenses = self.calculate_expenses(total_value, total_annual, self_managed=self_managed)
        mortgage = self.analyze_mortgage(value, down_payment_pct)
        tax_benefits = self.estimate_tax_benefits(total_value, mortgage, expenses)

        appreciation = self._get_neighborhood_appreciation(neighborhood)
        projections = self.project_cash_flow(
            total_value, total_annual, expenses, mortgage,
            appreciation_rate=appreciation,
        )

        noi = total_annual - expenses.total_annual
        annual_mortgage = mortgage.monthly_pi * 12
        annual_cf = noi - annual_mortgage
        cash_invested = mortgage.down_payment_amount + additional

        return InvestmentScenario(
            scenario_name=f"Multi-Unit ({max_units} units)",
            scenario_type="multi_unit",
            property_value=value,
            additional_investment=additional,
            total_investment=value + additional,
            units=units,
            total_monthly_rent=total_monthly,
            total_annual_rent=total_annual,
            expenses=expenses,
            mortgage=mortgage,
            cap_rate_pct=round(noi / total_value * 100, 2) if total_value > 0 else 0.0,
            cash_on_cash_pct=round(annual_cf / cash_invested * 100, 2) if cash_invested > 0 else 0.0,
            gross_rent_multiplier=round(total_value / total_annual, 1) if total_annual > 0 else 0.0,
            price_to_rent_ratio=round(total_value / total_annual, 1) if total_annual > 0 else 0.0,
            monthly_cash_flow=int(round(annual_cf / 12)),
            projections=projections,
            tax_benefits=tax_benefits,
            development_notes=(
                f"Build {max_units} units ({per_unit_sqft} sqft each). "
                f"Estimated construction: ${additional:,}. "
                f"Requires significant capital and permitting."
            ),
        )

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def analyze(
        self,
        property_dict: dict,
        down_payment_pct: float = 20.0,
        self_managed: bool = True,
    ) -> RentalAnalysisResponse:
        """Run complete rental analysis with all applicable scenarios."""
        address = property_dict.get("address")
        neighborhood = property_dict.get("neighborhood", "Berkeley")
        value = self._resolve_property_value(property_dict)

        # Get development potential if calculator available
        dev_potential = None
        if self.dev_calc:
            lat = property_dict.get("latitude")
            lon = property_dict.get("longitude")
            if lat and lon:
                dev_potential = self.dev_calc.compute(
                    lat=lat,
                    lon=lon,
                    lot_size_sqft=property_dict.get("lot_size_sqft"),
                    sqft=property_dict.get("sqft"),
                    address=address,
                )

        # Build all applicable scenarios
        scenarios: list[InvestmentScenario] = []
        data_sources: list[str] = []

        # Always build as-is
        as_is = self.build_scenario_as_is(property_dict, down_payment_pct, self_managed)
        scenarios.append(as_is)
        data_sources.append("Berkeley property sales (price-to-rent ratios)")
        data_sources.append("FRED mortgage rates")

        # ADU scenario
        adu = self.build_scenario_adu(property_dict, dev_potential, down_payment_pct, self_managed)
        if adu:
            scenarios.append(adu)
            data_sources.append("Berkeley building permits (ADU costs)")
            data_sources.append("Berkeley zoning (ADU eligibility)")

        # SB9 scenario
        sb9 = self.build_scenario_sb9(property_dict, dev_potential, down_payment_pct, self_managed)
        if sb9:
            scenarios.append(sb9)
            data_sources.append("SB 9 eligibility from zoning data")

        # Multi-unit scenario
        multi = self.build_scenario_multi_unit(
            property_dict, dev_potential, down_payment_pct, self_managed,
        )
        if multi:
            scenarios.append(multi)
            data_sources.append("Middle Housing Ordinance unit limits")

        # Pick best by cash-on-cash return
        best = max(scenarios, key=lambda s: s.cash_on_cash_pct)
        recommendation = self._generate_recommendation(scenarios, best)

        return RentalAnalysisResponse(
            property_address=address,
            property_value=value,
            neighborhood=neighborhood,
            scenarios=scenarios,
            best_scenario=best.scenario_name,
            recommendation_notes=recommendation,
            data_sources=list(set(data_sources)),
            disclaimers=[
                "Rent estimates use local price-to-rent ratios, not actual rental comps.",
                "Construction costs are averages from Berkeley building permits.",
                "Tax benefit estimates are approximate — consult a tax professional.",
                "Appreciation projections use historical trends and are not guaranteed.",
                "Cash flow projections assume stable vacancy and expense ratios.",
            ],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_property_value(self, property_dict: dict) -> int:
        """Get property value from dict — use list_price, predicted_price, or estimate."""
        if property_dict.get("list_price"):
            return int(property_dict["list_price"])
        if property_dict.get("predicted_price"):
            return int(property_dict["predicted_price"])
        if property_dict.get("sale_price"):
            return int(property_dict["sale_price"])
        # Fallback: estimate from neighborhood median
        return 1_200_000  # Berkeley median fallback

    def _get_neighborhood_appreciation(self, neighborhood: Optional[str]) -> float:
        """Get YoY appreciation rate for a neighborhood from DB."""
        if not neighborhood:
            return _DEFAULT_APPRECIATION
        try:
            from homebuyer.analysis.market_analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(self.db)
            stats = analyzer.get_neighborhood_stats(neighborhood, lookback_years=2)
            if stats and stats.yoy_price_change_pct is not None:
                return stats.yoy_price_change_pct / 100.0
        except Exception:
            pass
        return _DEFAULT_APPRECIATION

    def _get_adu_construction_cost(self, adu_sqft: int) -> int:
        """Get ADU construction cost from permit data or use default."""
        try:
            row = self.db.conn.execute(
                """
                SELECT AVG(job_value) as avg_cost, COUNT(*) as cnt
                FROM building_permits
                WHERE (LOWER(description) LIKE '%adu%'
                    OR LOWER(description) LIKE '%accessory dwelling%')
                  AND job_value > 10000
                """
            ).fetchone()
            if row and row["cnt"] and row["cnt"] >= 5 and row["avg_cost"]:
                return int(round(row["avg_cost"], -3))
        except Exception:
            pass
        return adu_sqft * _ADU_COST_PER_SQFT

    def _generate_recommendation(
        self,
        scenarios: list[InvestmentScenario],
        best: InvestmentScenario,
    ) -> str:
        """Generate a recommendation note comparing scenarios."""
        if len(scenarios) == 1:
            s = scenarios[0]
            if s.monthly_cash_flow >= 0:
                return (
                    f"Renting as-is generates ${s.monthly_cash_flow:,}/month cash flow "
                    f"with a {s.cap_rate_pct}% cap rate."
                )
            return (
                f"Renting as-is would result in negative cash flow of "
                f"${abs(s.monthly_cash_flow):,}/month. The investment return comes "
                f"from appreciation and equity buildup."
            )

        parts = [f"Best scenario by cash-on-cash return: {best.scenario_name} ({best.cash_on_cash_pct}%)."]
        for s in scenarios:
            if s.scenario_name != best.scenario_name:
                parts.append(
                    f"{s.scenario_name}: {s.cash_on_cash_pct}% CoC, "
                    f"${s.monthly_cash_flow:,}/mo cash flow."
                )
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Serialization helpers (for JSON API responses)
# ---------------------------------------------------------------------------


def rental_analysis_to_dict(resp: RentalAnalysisResponse) -> dict:
    """Convert a RentalAnalysisResponse to a JSON-serializable dict."""
    return {
        "property_address": resp.property_address,
        "property_value": resp.property_value,
        "neighborhood": resp.neighborhood,
        "scenarios": [_scenario_to_dict(s) for s in resp.scenarios],
        "best_scenario": resp.best_scenario,
        "recommendation_notes": resp.recommendation_notes,
        "data_sources": resp.data_sources,
        "disclaimers": resp.disclaimers,
    }


def _scenario_to_dict(s: InvestmentScenario) -> dict:
    return {
        "scenario_name": s.scenario_name,
        "scenario_type": s.scenario_type,
        "property_value": s.property_value,
        "additional_investment": s.additional_investment,
        "total_investment": s.total_investment,
        "units": [_rent_to_dict(u) for u in s.units],
        "total_monthly_rent": s.total_monthly_rent,
        "total_annual_rent": s.total_annual_rent,
        "expenses": {
            "property_tax": s.expenses.property_tax,
            "insurance": s.expenses.insurance,
            "maintenance": s.expenses.maintenance,
            "vacancy_reserve": s.expenses.vacancy_reserve,
            "management_fee": s.expenses.management_fee,
            "hoa": s.expenses.hoa,
            "utilities": s.expenses.utilities,
            "total_annual": s.expenses.total_annual,
            "expense_ratio_pct": s.expenses.expense_ratio_pct,
        },
        "mortgage": {
            "property_value": s.mortgage.property_value,
            "down_payment_pct": s.mortgage.down_payment_pct,
            "down_payment_amount": s.mortgage.down_payment_amount,
            "loan_amount": s.mortgage.loan_amount,
            "rate_30yr": s.mortgage.rate_30yr,
            "monthly_pi": s.mortgage.monthly_pi,
            "monthly_tax": s.mortgage.monthly_tax,
            "monthly_insurance": s.mortgage.monthly_insurance,
            "monthly_piti": s.mortgage.monthly_piti,
            "is_jumbo": s.mortgage.is_jumbo,
            "annual_interest_yr1": s.mortgage.annual_interest_yr1,
            "annual_principal_yr1": s.mortgage.annual_principal_yr1,
        },
        "cap_rate_pct": s.cap_rate_pct,
        "cash_on_cash_pct": s.cash_on_cash_pct,
        "gross_rent_multiplier": s.gross_rent_multiplier,
        "price_to_rent_ratio": s.price_to_rent_ratio,
        "monthly_cash_flow": s.monthly_cash_flow,
        "projections": [
            {
                "year": p.year,
                "gross_rent": p.gross_rent,
                "operating_expenses": p.operating_expenses,
                "noi": p.noi,
                "mortgage_payment": p.mortgage_payment,
                "cash_flow": p.cash_flow,
                "equity_buildup": p.equity_buildup,
                "property_value": p.property_value,
                "cumulative_equity": p.cumulative_equity,
                "total_return": p.total_return,
            }
            for p in s.projections
        ],
        "tax_benefits": {
            "depreciation_annual": s.tax_benefits.depreciation_annual,
            "mortgage_interest_deduction": s.tax_benefits.mortgage_interest_deduction,
            "operating_expense_deductions": s.tax_benefits.operating_expense_deductions,
            "estimated_tax_savings": s.tax_benefits.estimated_tax_savings,
            "marginal_tax_rate_used": s.tax_benefits.marginal_tax_rate_used,
            "notes": s.tax_benefits.notes,
        },
        "development_feasible": s.development_feasible,
        "development_notes": s.development_notes,
    }


def _rent_to_dict(r: RentEstimate) -> dict:
    return {
        "unit_type": r.unit_type,
        "beds": r.beds,
        "baths": r.baths,
        "sqft": r.sqft,
        "monthly_rent": r.monthly_rent,
        "annual_rent": r.annual_rent,
        "estimation_method": r.estimation_method,
        "confidence": r.confidence,
        "notes": r.notes,
    }
