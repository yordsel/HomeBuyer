"""Investment prospectus generator for Berkeley properties.

Aggregates data from multiple analysis modules (valuation, market, development,
rental/investment, comparables) into a comprehensive investment case with
recommended strategy, capital requirements, projected returns, and risk factors.

Used by the Faketor chat tool ``generate_investment_prospectus``.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from homebuyer.analysis.market_analysis import MarketAnalyzer, NeighborhoodStats
from homebuyer.analysis.rental_analysis import (
    InvestmentScenario,
    RentalAnalysisResponse,
    RentalAnalyzer,
)
from homebuyer.processing.development import (
    DevelopmentPotential,
    DevelopmentPotentialCalculator,
)
from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PropertyProspectus:
    """Complete investment prospectus for a single property."""

    # Property Overview
    address: Optional[str] = None
    neighborhood: str = "Berkeley"
    property_type: str = "Single Family Residential"
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    zoning_class: Optional[str] = None

    # Valuation
    estimated_value: int = 0
    value_range_low: int = 0
    value_range_high: int = 0
    value_per_sqft: Optional[int] = None

    # Market Context
    neighborhood_median_price: Optional[int] = None
    neighborhood_yoy_change_pct: Optional[float] = None
    neighborhood_avg_ppsf: Optional[float] = None
    city_median_price: Optional[int] = None
    mortgage_rate_30yr: Optional[float] = None
    median_dom: Optional[int] = None
    comparable_sales: list[dict] = field(default_factory=list)

    # Development Potential
    adu_eligible: bool = False
    adu_max_sqft: Optional[int] = None
    sb9_eligible: bool = False
    sb9_can_split: bool = False
    middle_housing_eligible: bool = False
    middle_housing_max_units: Optional[int] = None
    effective_max_units: int = 1
    development_notes: str = ""

    # Investment Scenarios
    scenarios: list[dict] = field(default_factory=list)
    best_scenario_name: str = ""
    recommendation_notes: str = ""

    # Recommended Strategy
    recommended_approach: str = "rent_as_is"
    strategy_rationale: str = ""
    capital_required: int = 0
    time_horizon_years: int = 5
    projected_total_return: int = 0
    projected_annual_return_pct: float = 0.0
    monthly_cash_flow: int = 0

    # Risk Factors
    risk_factors: list[str] = field(default_factory=list)

    # Key Metrics
    cap_rate_pct: float = 0.0
    cash_on_cash_pct: float = 0.0
    gross_rent_multiplier: float = 0.0
    price_to_rent_ratio: float = 0.0

    # Metadata
    generated_at: str = ""
    data_sources: list[str] = field(default_factory=list)
    disclaimers: list[str] = field(default_factory=list)


@dataclass
class PortfolioSummary:
    """Aggregated metrics for a multi-property prospectus."""

    total_capital_required: int = 0
    total_monthly_cash_flow: int = 0
    weighted_avg_cap_rate: float = 0.0
    weighted_avg_coc: float = 0.0
    property_count: int = 0
    diversification_notes: str = ""


@dataclass
class InvestmentProspectusResponse:
    """Top-level response supporting single or multi-property prospectus."""

    properties: list[PropertyProspectus] = field(default_factory=list)
    portfolio_summary: Optional[PortfolioSummary] = None
    is_multi_property: bool = False


# ---------------------------------------------------------------------------
# Strategy labels
# ---------------------------------------------------------------------------

_STRATEGY_LABELS = {
    "rent_as_is": "Rent As-Is",
    "develop_adu_and_rent": "Build ADU + Rent",
    "develop_sb9_and_rent": "SB9 Split + Rent",
    "develop_and_sell": "Develop + Sell",
    "hold_for_appreciation": "Hold for Appreciation",
    "multi_unit_development": "Multi-Unit Development",
}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class ProspectusGenerator:
    """Orchestrates multiple analyzers to build a comprehensive prospectus."""

    def __init__(
        self,
        db: Database,
        dev_calc: Optional[DevelopmentPotentialCalculator],
        rental_analyzer: RentalAnalyzer,
        market_analyzer: MarketAnalyzer,
        predict_fn: Callable[[dict, str], dict],
    ) -> None:
        self.db = db
        self.dev_calc = dev_calc
        self.rental_analyzer = rental_analyzer
        self.market_analyzer = market_analyzer
        self.predict_fn = predict_fn

    def generate(
        self,
        properties: list[dict],
        down_payment_pct: float = 20.0,
        investment_horizon_years: int = 5,
    ) -> InvestmentProspectusResponse:
        """Generate prospectus for one or more properties."""
        prospectuses = []
        for prop_dict in properties:
            p = self._generate_single(prop_dict, down_payment_pct, investment_horizon_years)
            prospectuses.append(p)

        portfolio = None
        if len(prospectuses) > 1:
            portfolio = self._build_portfolio_summary(prospectuses)

        return InvestmentProspectusResponse(
            properties=prospectuses,
            portfolio_summary=portfolio,
            is_multi_property=len(prospectuses) > 1,
        )

    # ------------------------------------------------------------------
    # Single property
    # ------------------------------------------------------------------

    def _generate_single(
        self,
        prop_dict: dict,
        down_payment_pct: float,
        horizon_years: int,
    ) -> PropertyProspectus:
        p = PropertyProspectus()
        p.time_horizon_years = horizon_years
        p.generated_at = datetime.now(timezone.utc).isoformat()

        # --- Property overview ---
        p.address = prop_dict.get("address")
        p.neighborhood = prop_dict.get("neighborhood", "Berkeley")
        p.property_type = prop_dict.get("property_type", "Single Family Residential")
        p.beds = prop_dict.get("beds")
        p.baths = prop_dict.get("baths")
        p.sqft = prop_dict.get("sqft")
        p.year_built = prop_dict.get("year_built")
        p.lot_size_sqft = prop_dict.get("lot_size_sqft")
        p.zoning_class = prop_dict.get("zoning_class")

        # --- Valuation (ML prediction) ---
        try:
            pred = self.predict_fn(prop_dict, "prospectus")
            p.estimated_value = pred.get("predicted_price", 0)
            p.value_range_low = pred.get("price_lower", p.estimated_value)
            p.value_range_high = pred.get("price_upper", p.estimated_value)
            if p.sqft and p.estimated_value:
                p.value_per_sqft = int(p.estimated_value / p.sqft)
            p.data_sources.append("ML price prediction model")
        except Exception as e:
            logger.warning("Prediction failed for prospectus: %s", e)

        # --- Market context ---
        try:
            nbr_stats = self.market_analyzer.get_neighborhood_stats(
                p.neighborhood, lookback_years=2,
            )
            if nbr_stats:
                p.neighborhood_median_price = (
                    int(nbr_stats.median_price) if nbr_stats.median_price else None
                )
                p.neighborhood_yoy_change_pct = nbr_stats.yoy_price_change_pct
                p.neighborhood_avg_ppsf = (
                    round(nbr_stats.avg_ppsf, 1) if nbr_stats.avg_ppsf else None
                )
                p.data_sources.append("Berkeley property sales database")
        except Exception as e:
            logger.warning("Neighborhood stats failed: %s", e)
            nbr_stats = None

        try:
            market = self.market_analyzer.generate_summary_report()
            cm = market.get("current_market", {})
            p.city_median_price = cm.get("median_sale_price")
            p.mortgage_rate_30yr = cm.get("mortgage_rate_30yr")
            p.median_dom = cm.get("median_days_on_market")
            if cm:
                p.data_sources.append("Berkeley market metrics")
        except Exception as e:
            logger.warning("Market summary failed: %s", e)

        # --- Comparable sales ---
        try:
            comps = self.market_analyzer.find_comparables(
                neighborhood=p.neighborhood,
                beds=p.beds,
                baths=p.baths,
                sqft=p.sqft,
                year_built=p.year_built,
                max_results=5,
            )
            p.comparable_sales = [
                {
                    "address": c.address,
                    "sale_price": c.sale_price,
                    "sale_date": str(c.sale_date),
                    "beds": c.beds,
                    "sqft": c.sqft,
                    "price_per_sqft": (
                        round(c.price_per_sqft, 0) if c.price_per_sqft else None
                    ),
                }
                for c in comps[:5]
            ]
            if comps:
                p.data_sources.append("Comparable sales data")
        except Exception as e:
            logger.warning("Comps failed: %s", e)

        # --- Development potential ---
        dev_potential: Optional[DevelopmentPotential] = None
        if self.dev_calc:
            lat = prop_dict.get("latitude")
            lon = prop_dict.get("longitude")
            if lat and lon:
                try:
                    dev_potential = self.dev_calc.compute(
                        lat=lat, lon=lon,
                        lot_size_sqft=p.lot_size_sqft,
                        sqft=p.sqft,
                        address=p.address,
                    )
                    if dev_potential.adu:
                        p.adu_eligible = dev_potential.adu.eligible
                        p.adu_max_sqft = dev_potential.adu.max_adu_sqft
                    if dev_potential.sb9:
                        p.sb9_eligible = dev_potential.sb9.eligible
                        p.sb9_can_split = dev_potential.sb9.can_split
                    if dev_potential.units:
                        p.middle_housing_eligible = dev_potential.units.middle_housing_eligible
                        p.middle_housing_max_units = dev_potential.units.middle_housing_max_units
                        p.effective_max_units = dev_potential.units.effective_max_units
                    if dev_potential.zoning:
                        p.zoning_class = p.zoning_class or dev_potential.zoning.zone_class
                    p.development_notes = self._summarize_development(dev_potential)
                    p.data_sources.append("Berkeley zoning & development data")
                except Exception as e:
                    logger.warning("Development potential failed: %s", e)

        # --- Investment scenarios ---
        analysis: Optional[RentalAnalysisResponse] = None
        try:
            # Inject predicted price so RentalAnalyzer can use it
            scenario_prop = dict(prop_dict)
            if p.estimated_value and not scenario_prop.get("predicted_price"):
                scenario_prop["predicted_price"] = p.estimated_value

            analysis = self.rental_analyzer.analyze(
                scenario_prop,
                down_payment_pct=down_payment_pct,
                self_managed=True,
            )
            from homebuyer.analysis.rental_analysis import _scenario_to_dict

            p.scenarios = [_scenario_to_dict(s) for s in analysis.scenarios]
            p.best_scenario_name = analysis.best_scenario
            p.recommendation_notes = analysis.recommendation_notes
            p.data_sources.extend(
                s for s in analysis.data_sources if s not in p.data_sources
            )
        except Exception as e:
            logger.warning("Investment analysis failed: %s", e)

        # --- Recommended strategy ---
        if analysis:
            approach, rationale = self._determine_strategy(
                analysis, dev_potential, nbr_stats, horizon_years,
            )
            p.recommended_approach = approach
            p.strategy_rationale = rationale

            # Find the best scenario to pull metrics from
            best = self._find_best_scenario(analysis)
            if best:
                p.cap_rate_pct = best.cap_rate_pct
                p.cash_on_cash_pct = best.cash_on_cash_pct
                p.gross_rent_multiplier = best.gross_rent_multiplier
                p.price_to_rent_ratio = best.price_to_rent_ratio
                p.monthly_cash_flow = best.monthly_cash_flow

                # Capital required = down payment + additional investment
                p.capital_required = (
                    best.mortgage.down_payment_amount + best.additional_investment
                )

                # Projected returns from cash flow projections
                target_proj = None
                for proj in best.projections:
                    if proj.year == horizon_years:
                        target_proj = proj
                        break
                if not target_proj and best.projections:
                    target_proj = best.projections[-1]

                if target_proj:
                    p.projected_total_return = target_proj.total_return
                    if p.capital_required > 0 and target_proj.total_return:
                        annualized = (
                            (target_proj.total_return / p.capital_required)
                            / max(horizon_years, 1)
                            * 100
                        )
                        p.projected_annual_return_pct = round(annualized, 1)

        # --- Risk factors ---
        p.risk_factors = self._assess_risks(prop_dict, p, nbr_stats, dev_potential)

        # --- Disclaimers ---
        p.disclaimers = [
            "All projections are estimates based on historical data and may not reflect future performance.",
            "Actual construction costs, rental income, and property values may vary significantly.",
            "This is not financial advice. Consult a licensed financial advisor before making investment decisions.",
        ]

        return p

    # ------------------------------------------------------------------
    # Strategy determination
    # ------------------------------------------------------------------

    def _determine_strategy(
        self,
        analysis: RentalAnalysisResponse,
        dev_potential: Optional[DevelopmentPotential],
        nbr_stats: Optional[NeighborhoodStats],
        horizon_years: int,
    ) -> tuple[str, str]:
        """Pick and justify the recommended investment strategy."""
        scenarios = analysis.scenarios
        if not scenarios:
            return "rent_as_is", "Insufficient data for strategy recommendation."

        # Find the as-is scenario and the best alternative
        as_is: Optional[InvestmentScenario] = None
        best_alt: Optional[InvestmentScenario] = None
        best_alt_coc: float = -999

        for s in scenarios:
            if s.scenario_type == "as_is":
                as_is = s
            elif s.development_feasible and s.cash_on_cash_pct > best_alt_coc:
                best_alt = s
                best_alt_coc = s.cash_on_cash_pct

        if not as_is:
            as_is = scenarios[0]

        yoy = (
            nbr_stats.yoy_price_change_pct
            if nbr_stats and nbr_stats.yoy_price_change_pct is not None
            else 3.0
        )

        # Decision logic
        # 1. Strong appreciation market + low cap rate → hold for appreciation
        if yoy > 5.0 and as_is.cap_rate_pct < 3.0:
            return (
                "hold_for_appreciation",
                f"With {yoy:.1f}% annual appreciation in {as_is.scenario_name or 'this area'} "
                f"and a modest {as_is.cap_rate_pct:.1f}% cap rate, the primary return driver "
                f"is property value growth. Holding for {horizon_years} years maximizes "
                f"equity gains while collecting modest rental income.",
            )

        # 2. ADU scenario significantly outperforms as-is
        adu_scenario = next(
            (s for s in scenarios if s.scenario_type == "adu" and s.development_feasible),
            None,
        )
        if adu_scenario and adu_scenario.cash_on_cash_pct > as_is.cash_on_cash_pct + 1.5:
            additional = adu_scenario.additional_investment
            return (
                "develop_adu_and_rent",
                f"Adding an ADU boosts cash-on-cash return from "
                f"{as_is.cash_on_cash_pct:.1f}% to {adu_scenario.cash_on_cash_pct:.1f}%, "
                f"requiring approximately ${additional:,.0f} in additional capital. "
                f"The extra rental unit diversifies income and improves overall yield.",
            )

        # 3. SB9 scenario has highest CoC and property qualifies
        sb9_scenario = next(
            (s for s in scenarios if s.scenario_type == "sb9" and s.development_feasible),
            None,
        )
        if (
            sb9_scenario
            and sb9_scenario.cash_on_cash_pct > as_is.cash_on_cash_pct + 2.0
            and (not adu_scenario or sb9_scenario.cash_on_cash_pct > adu_scenario.cash_on_cash_pct)
        ):
            return (
                "develop_sb9_and_rent",
                f"SB9 lot splitting delivers the highest cash-on-cash return at "
                f"{sb9_scenario.cash_on_cash_pct:.1f}%, creating multiple rental units "
                f"from a single parcel. This requires more capital and longer timeline "
                f"but maximizes income potential.",
            )

        # 4. Multi-unit development with high returns but high capital
        multi_scenario = next(
            (s for s in scenarios if s.scenario_type == "multi_unit" and s.development_feasible),
            None,
        )
        if (
            multi_scenario
            and multi_scenario.additional_investment > 500_000
            and multi_scenario.cash_on_cash_pct > as_is.cash_on_cash_pct + 3.0
        ):
            return (
                "develop_and_sell",
                f"Multi-unit development offers {multi_scenario.cash_on_cash_pct:.1f}% "
                f"cash-on-cash return but requires ${multi_scenario.additional_investment:,.0f} "
                f"in development capital. Consider developing and selling for a one-time "
                f"profit if you prefer to avoid ongoing landlord responsibilities.",
            )

        # 5. Good as-is cap rate
        if as_is.cap_rate_pct >= 4.0:
            return (
                "rent_as_is",
                f"The property generates a solid {as_is.cap_rate_pct:.1f}% cap rate "
                f"with ${as_is.monthly_cash_flow:,.0f}/month cash flow as a rental "
                f"without any additional development investment. "
                f"Combined with {yoy:.1f}% annual appreciation, this is a strong "
                f"buy-and-hold strategy.",
            )

        # 6. Default: rent as-is with moderate returns
        return (
            "rent_as_is",
            f"Renting the property as-is provides a {as_is.cap_rate_pct:.1f}% cap rate "
            f"with ${as_is.monthly_cash_flow:,.0f}/month cash flow. "
            f"While development options may exist, the as-is scenario offers the "
            f"lowest risk entry point for a {horizon_years}-year investment horizon.",
        )

    def _find_best_scenario(
        self, analysis: RentalAnalysisResponse,
    ) -> Optional[InvestmentScenario]:
        """Return the scenario matching best_scenario name."""
        for s in analysis.scenarios:
            if s.scenario_name == analysis.best_scenario:
                return s
        return analysis.scenarios[0] if analysis.scenarios else None

    # ------------------------------------------------------------------
    # Development summary
    # ------------------------------------------------------------------

    def _summarize_development(self, dev: DevelopmentPotential) -> str:
        """Build a concise development summary string."""
        parts = []
        if dev.zoning:
            parts.append(f"Zoned {dev.zoning.zone_class}")
        if dev.adu and dev.adu.eligible:
            sqft = f" (up to {dev.adu.max_adu_sqft} sqft)" if dev.adu.max_adu_sqft else ""
            parts.append(f"ADU eligible{sqft}")
        elif dev.adu:
            parts.append("ADU not eligible")
        if dev.sb9 and dev.sb9.eligible:
            parts.append("SB9 lot split eligible")
        if dev.units and dev.units.middle_housing_eligible:
            parts.append(
                f"Middle Housing up to {dev.units.middle_housing_max_units} units"
            )
        if dev.units:
            parts.append(f"Max {dev.units.effective_max_units} units")
        return ". ".join(parts) + "." if parts else "No development data available."

    # ------------------------------------------------------------------
    # Risk assessment
    # ------------------------------------------------------------------

    def _assess_risks(
        self,
        prop_dict: dict,
        prospectus: PropertyProspectus,
        nbr_stats: Optional[NeighborhoodStats],
        dev_potential: Optional[DevelopmentPotential],
    ) -> list[str]:
        """Generate dynamic risk factor list based on property characteristics."""
        risks: list[str] = []

        # Market risks
        if nbr_stats and nbr_stats.yoy_price_change_pct is not None:
            if nbr_stats.yoy_price_change_pct < 0:
                risks.append(
                    f"Neighborhood showing negative YoY price trend "
                    f"({nbr_stats.yoy_price_change_pct:+.1f}%)"
                )
        if prospectus.mortgage_rate_30yr and prospectus.mortgage_rate_30yr > 7.0:
            risks.append(
                f"Elevated mortgage rates ({prospectus.mortgage_rate_30yr:.2f}%) "
                f"reduce cash flow and buyer demand"
            )

        # Property-specific risks
        year_built = prop_dict.get("year_built")
        if year_built and year_built < 1940:
            risks.append(
                "Pre-1940 construction may require significant seismic or "
                "structural upgrades"
            )
        if prospectus.estimated_value > 2_000_000:
            risks.append(
                "High-value property may have a more limited buyer and renter pool"
            )

        # Development risks
        if dev_potential and dev_potential.adu and dev_potential.adu.eligible:
            risks.append(
                "ADU construction costs may vary significantly from estimates; "
                "permitting timeline can be 6-18 months"
            )
        if dev_potential and dev_potential.sb9 and dev_potential.sb9.eligible:
            risks.append(
                "SB9 lot splitting requires survey, permitting, and infrastructure "
                "separation which adds cost and time"
            )

        # Berkeley-specific
        if year_built and year_built < 1980:
            risks.append(
                "Berkeley rent control applies to most residential units built "
                "before 1980, limiting rent increases"
            )
        risks.append(
            "Rent estimates use historical price-to-rent ratios and may not "
            "reflect current rental market conditions"
        )
        risks.append(
            "Construction cost estimates are Berkeley averages and actual costs "
            "depend on scope, permits, and contractor availability"
        )

        return risks

    # ------------------------------------------------------------------
    # Portfolio summary (multi-property)
    # ------------------------------------------------------------------

    def _build_portfolio_summary(
        self, prospectuses: list[PropertyProspectus],
    ) -> PortfolioSummary:
        """Aggregate metrics across multiple properties."""
        total_capital = sum(p.capital_required for p in prospectuses)
        total_cf = sum(p.monthly_cash_flow for p in prospectuses)

        # Weighted average metrics by estimated value
        total_value = sum(p.estimated_value for p in prospectuses) or 1
        w_cap = sum(
            p.cap_rate_pct * p.estimated_value for p in prospectuses
        ) / total_value
        w_coc = sum(
            p.cash_on_cash_pct * p.estimated_value for p in prospectuses
        ) / total_value

        # Diversification notes
        neighborhoods = {p.neighborhood for p in prospectuses}
        approaches = {_STRATEGY_LABELS.get(p.recommended_approach, p.recommended_approach)
                      for p in prospectuses}
        notes_parts = []
        if len(neighborhoods) > 1:
            notes_parts.append(
                f"Diversified across {len(neighborhoods)} neighborhoods: "
                f"{', '.join(sorted(neighborhoods))}"
            )
        else:
            notes_parts.append(
                f"Concentrated in {next(iter(neighborhoods))}"
            )
        if len(approaches) > 1:
            notes_parts.append(
                f"Mixed strategies: {', '.join(sorted(approaches))}"
            )

        return PortfolioSummary(
            total_capital_required=total_capital,
            total_monthly_cash_flow=total_cf,
            weighted_avg_cap_rate=round(w_cap, 2),
            weighted_avg_coc=round(w_coc, 2),
            property_count=len(prospectuses),
            diversification_notes=". ".join(notes_parts),
        )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def prospectus_to_dict(resp: InvestmentProspectusResponse) -> dict:
    """Convert an InvestmentProspectusResponse to a JSON-serializable dict."""
    return {
        "properties": [_property_prospectus_to_dict(p) for p in resp.properties],
        "portfolio_summary": _portfolio_to_dict(resp.portfolio_summary) if resp.portfolio_summary else None,
        "is_multi_property": resp.is_multi_property,
    }


def _property_prospectus_to_dict(p: PropertyProspectus) -> dict:
    return {
        # Property overview
        "address": p.address,
        "neighborhood": p.neighborhood,
        "property_type": p.property_type,
        "beds": p.beds,
        "baths": p.baths,
        "sqft": p.sqft,
        "year_built": p.year_built,
        "lot_size_sqft": p.lot_size_sqft,
        "zoning_class": p.zoning_class,
        # Valuation
        "estimated_value": p.estimated_value,
        "value_range_low": p.value_range_low,
        "value_range_high": p.value_range_high,
        "value_per_sqft": p.value_per_sqft,
        # Market context
        "neighborhood_median_price": p.neighborhood_median_price,
        "neighborhood_yoy_change_pct": p.neighborhood_yoy_change_pct,
        "neighborhood_avg_ppsf": p.neighborhood_avg_ppsf,
        "city_median_price": p.city_median_price,
        "mortgage_rate_30yr": p.mortgage_rate_30yr,
        "median_dom": p.median_dom,
        "comparable_sales": p.comparable_sales,
        # Development potential
        "adu_eligible": p.adu_eligible,
        "adu_max_sqft": p.adu_max_sqft,
        "sb9_eligible": p.sb9_eligible,
        "sb9_can_split": p.sb9_can_split,
        "middle_housing_eligible": p.middle_housing_eligible,
        "middle_housing_max_units": p.middle_housing_max_units,
        "effective_max_units": p.effective_max_units,
        "development_notes": p.development_notes,
        # Investment scenarios
        "scenarios": p.scenarios,
        "best_scenario_name": p.best_scenario_name,
        "recommendation_notes": p.recommendation_notes,
        # Recommended strategy
        "recommended_approach": p.recommended_approach,
        "recommended_approach_label": _STRATEGY_LABELS.get(
            p.recommended_approach, p.recommended_approach,
        ),
        "strategy_rationale": p.strategy_rationale,
        "capital_required": p.capital_required,
        "time_horizon_years": p.time_horizon_years,
        "projected_total_return": p.projected_total_return,
        "projected_annual_return_pct": p.projected_annual_return_pct,
        "monthly_cash_flow": p.monthly_cash_flow,
        # Risk factors
        "risk_factors": p.risk_factors,
        # Key metrics
        "cap_rate_pct": p.cap_rate_pct,
        "cash_on_cash_pct": p.cash_on_cash_pct,
        "gross_rent_multiplier": p.gross_rent_multiplier,
        "price_to_rent_ratio": p.price_to_rent_ratio,
        # Metadata
        "generated_at": p.generated_at,
        "data_sources": p.data_sources,
        "disclaimers": p.disclaimers,
    }


def _portfolio_to_dict(ps: PortfolioSummary) -> dict:
    return {
        "total_capital_required": ps.total_capital_required,
        "total_monthly_cash_flow": ps.total_monthly_cash_flow,
        "weighted_avg_cap_rate": ps.weighted_avg_cap_rate,
        "weighted_avg_coc": ps.weighted_avg_coc,
        "property_count": ps.property_count,
        "diversification_notes": ps.diversification_notes,
    }
