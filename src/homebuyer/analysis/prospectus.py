"""Investment prospectus generator for Berkeley properties.

Aggregates data from multiple analysis modules (valuation, market, development,
rental/investment, comparables) into a comprehensive investment case with
recommended strategy, capital requirements, projected returns, and risk factors.

Used by the Faketor chat tool ``generate_investment_prospectus``.
"""

import logging
import math
import statistics
from collections import Counter
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

    # Narrative commentaries (generated from data, no LLM needed)
    valuation_commentary: str = ""
    market_position_commentary: str = ""
    scenario_recommendation_narrative: str = ""
    comps_analysis_narrative: str = ""
    risk_mitigation_narrative: str = ""

    # Best scenario detail for charts (full scenario dict w/ projections, expenses)
    best_scenario_detail: Optional[dict] = None

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

    # Multi-property mode and narrative
    mode: str = "curated"
    investment_thesis: str = ""

    # Similar mode
    shared_traits: list[str] = field(default_factory=list)
    individual_differences: list[str] = field(default_factory=list)

    # Thesis mode
    group_statistics: Optional[dict] = None
    example_property_indices: list[int] = field(default_factory=list)

    # Chart data
    comparison_metrics: list[dict] = field(default_factory=list)
    neighborhood_allocation: dict = field(default_factory=dict)
    strategy_allocation: dict = field(default_factory=dict)


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
        mode: Optional[str] = None,
    ) -> InvestmentProspectusResponse:
        """Generate prospectus for one or more properties.

        Args:
            mode: "curated", "similar", "thesis", or None for auto-detect.
        """
        detected_mode = mode or self._detect_mode(properties)

        # For thesis mode with many properties, only generate full
        # prospectuses for example properties; rest contribute to
        # aggregate stats.
        if detected_mode == "thesis" and len(properties) > 10:
            example_indices = self._select_example_indices(
                properties, down_payment_pct, investment_horizon_years,
            )
            prospectuses: list[PropertyProspectus] = []
            for i, prop_dict in enumerate(properties):
                if i in example_indices:
                    p = self._generate_single(
                        prop_dict, down_payment_pct, investment_horizon_years,
                    )
                else:
                    p = self._generate_lightweight(prop_dict)
                prospectuses.append(p)
        else:
            prospectuses = []
            for prop_dict in properties:
                p = self._generate_single(
                    prop_dict, down_payment_pct, investment_horizon_years,
                )
                prospectuses.append(p)

        portfolio = None
        if len(prospectuses) > 1:
            portfolio = self._build_portfolio_summary(
                prospectuses, mode=detected_mode,
            )

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

        # --- Best scenario detail for charts ---
        if analysis:
            best_obj = self._find_best_scenario(analysis)
            if best_obj:
                from homebuyer.analysis.rental_analysis import _scenario_to_dict
                p.best_scenario_detail = _scenario_to_dict(best_obj)

        # --- Risk factors ---
        p.risk_factors = self._assess_risks(prop_dict, p, nbr_stats, dev_potential)

        # --- Narrative commentaries ---
        p.valuation_commentary = self._generate_valuation_commentary(p)
        p.market_position_commentary = self._generate_market_position_commentary(p)
        p.scenario_recommendation_narrative = self._generate_scenario_narrative(p)
        p.comps_analysis_narrative = self._generate_comps_narrative(p)
        p.risk_mitigation_narrative = self._generate_risk_mitigation(p)

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
    # Narrative generators (data-driven, no LLM)
    # ------------------------------------------------------------------

    def _generate_valuation_commentary(self, p: PropertyProspectus) -> str:
        """Compare estimated value to neighborhood/city medians and $/sqft."""
        parts: list[str] = []

        if p.estimated_value and p.neighborhood_median_price:
            delta_pct = (
                (p.estimated_value - p.neighborhood_median_price)
                / p.neighborhood_median_price
                * 100
            )
            if abs(delta_pct) < 5:
                parts.append(
                    f"At ${p.estimated_value:,.0f}, this property is valued near the "
                    f"{p.neighborhood} median of ${p.neighborhood_median_price:,.0f}"
                )
            elif delta_pct > 0:
                parts.append(
                    f"Valued at ${p.estimated_value:,.0f}, this property sits "
                    f"{delta_pct:.0f}% above the {p.neighborhood} median of "
                    f"${p.neighborhood_median_price:,.0f}"
                )
            else:
                parts.append(
                    f"At ${p.estimated_value:,.0f}, this property is priced "
                    f"{abs(delta_pct):.0f}% below the {p.neighborhood} median "
                    f"of ${p.neighborhood_median_price:,.0f}, suggesting relative value"
                )

        if p.value_per_sqft and p.neighborhood_avg_ppsf:
            ppsf_delta = p.value_per_sqft - p.neighborhood_avg_ppsf
            if abs(ppsf_delta) > 30:
                direction = "above" if ppsf_delta > 0 else "below"
                parts.append(
                    f"At ${p.value_per_sqft}/sqft vs. the neighborhood average of "
                    f"${p.neighborhood_avg_ppsf:.0f}/sqft, the price per square foot "
                    f"is ${abs(ppsf_delta):.0f} {direction} average"
                )

        range_width = p.value_range_high - p.value_range_low
        if range_width > 0 and p.estimated_value:
            pct_range = range_width / p.estimated_value * 100
            parts.append(
                f"The valuation range of ${p.value_range_low:,.0f} to "
                f"${p.value_range_high:,.0f} ({pct_range:.0f}% spread) reflects "
                f"{'moderate' if pct_range < 20 else 'significant'} uncertainty"
            )

        return ". ".join(parts) + "." if parts else ""

    def _generate_market_position_commentary(self, p: PropertyProspectus) -> str:
        """Contextualize the property within market trends."""
        parts: list[str] = []

        if p.neighborhood_yoy_change_pct is not None:
            yoy = p.neighborhood_yoy_change_pct
            if yoy > 5:
                parts.append(
                    f"{p.neighborhood} has seen strong {yoy:.1f}% year-over-year "
                    f"price appreciation, indicating a seller's market with upward "
                    f"momentum"
                )
            elif yoy > 0:
                parts.append(
                    f"{p.neighborhood} shows steady {yoy:.1f}% annual appreciation, "
                    f"consistent with a stable, growing market"
                )
            elif yoy > -3:
                parts.append(
                    f"{p.neighborhood} has seen a modest {yoy:.1f}% year-over-year "
                    f"price adjustment, which may present a buying opportunity"
                )
            else:
                parts.append(
                    f"{p.neighborhood} is experiencing a {abs(yoy):.1f}% year-over-year "
                    f"price decline, suggesting caution and potential for further "
                    f"correction"
                )

        if p.city_median_price and p.neighborhood_median_price:
            if p.neighborhood_median_price > p.city_median_price * 1.15:
                parts.append(
                    f"This is a premium neighborhood, with median prices "
                    f"{((p.neighborhood_median_price / p.city_median_price) - 1) * 100:.0f}% "
                    f"above the Berkeley-wide median of ${p.city_median_price:,.0f}"
                )
            elif p.neighborhood_median_price < p.city_median_price * 0.85:
                parts.append(
                    f"Priced below the Berkeley-wide median of "
                    f"${p.city_median_price:,.0f}, this neighborhood offers "
                    f"a more accessible entry point"
                )

        if p.median_dom is not None:
            if p.median_dom < 14:
                parts.append(
                    f"With a median {p.median_dom} days on market, homes sell "
                    f"quickly — indicating strong buyer demand"
                )
            elif p.median_dom > 45:
                parts.append(
                    f"At {p.median_dom} median days on market, there may be room "
                    f"to negotiate favorable terms"
                )

        return ". ".join(parts) + "." if parts else ""

    def _generate_scenario_narrative(self, p: PropertyProspectus) -> str:
        """Explain why the recommended scenario is best vs alternatives."""
        scenarios = p.scenarios or []
        if len(scenarios) < 2:
            return p.recommendation_notes or ""

        best_sc = None
        for sc in scenarios:
            name = sc.get("scenario_name", "")
            if name and p.best_scenario_name and name.lower() == p.best_scenario_name.lower():
                best_sc = sc
                break
        if not best_sc:
            best_sc = scenarios[0]

        others = [s for s in scenarios if s is not best_sc]
        best_coc = best_sc.get("cash_on_cash_pct", 0)
        best_cf = best_sc.get("monthly_cash_flow", 0)
        best_invest = best_sc.get("total_investment", 0)

        parts = [
            f"The recommended {best_sc.get('scenario_name', 'scenario')} delivers "
            f"a {best_coc:.1f}% cash-on-cash return with ${best_cf:,.0f}/month "
            f"cash flow on a ${best_invest:,.0f} total investment"
        ]

        for alt in others[:2]:
            alt_name = alt.get("scenario_name", "Alternative")
            alt_coc = alt.get("cash_on_cash_pct", 0)
            alt_cf = alt.get("monthly_cash_flow", 0)
            delta = best_coc - alt_coc
            if delta > 0:
                parts.append(
                    f"Compared to {alt_name} ({alt_coc:.1f}% CoC, "
                    f"${alt_cf:,.0f}/mo), the recommended approach outperforms "
                    f"by {delta:.1f} percentage points"
                )
            elif delta < -0.5:
                extra_invest = (
                    alt.get("total_investment", 0) - best_invest
                )
                parts.append(
                    f"While {alt_name} offers a higher {alt_coc:.1f}% CoC, "
                    f"it requires ${extra_invest:,.0f} more capital and "
                    f"carries additional development risk"
                )

        return ". ".join(parts) + "."

    def _generate_comps_narrative(self, p: PropertyProspectus) -> str:
        """Discuss how the subject property compares to recent sales."""
        comps = p.comparable_sales or []
        if not comps:
            return ""

        prices = [c.get("sale_price", 0) for c in comps if c.get("sale_price")]
        if not prices:
            return ""

        avg_comp = sum(prices) / len(prices)
        parts: list[str] = []

        if p.estimated_value and avg_comp:
            delta_pct = (p.estimated_value - avg_comp) / avg_comp * 100
            if abs(delta_pct) < 5:
                parts.append(
                    f"The estimated value of ${p.estimated_value:,.0f} aligns "
                    f"closely with the average comparable sale price of "
                    f"${avg_comp:,.0f} across {len(comps)} recent transactions"
                )
            elif delta_pct > 0:
                parts.append(
                    f"At ${p.estimated_value:,.0f}, the property is valued "
                    f"{delta_pct:.0f}% above the average comparable at "
                    f"${avg_comp:,.0f}"
                )
            else:
                parts.append(
                    f"The estimated value of ${p.estimated_value:,.0f} is "
                    f"{abs(delta_pct):.0f}% below the average comparable "
                    f"sale of ${avg_comp:,.0f}, suggesting the model sees "
                    f"downside factors"
                )

        ppsf_values = [
            c.get("price_per_sqft", 0) for c in comps if c.get("price_per_sqft")
        ]
        if ppsf_values and p.value_per_sqft:
            avg_ppsf = sum(ppsf_values) / len(ppsf_values)
            parts.append(
                f"On a per-square-foot basis, the subject at ${p.value_per_sqft}/sqft "
                f"compares to a comp average of ${avg_ppsf:.0f}/sqft"
            )

        return ". ".join(parts) + "." if parts else ""

    def _generate_risk_mitigation(self, p: PropertyProspectus) -> str:
        """Provide practical mitigation strategies for the identified risks."""
        if not p.risk_factors:
            return ""

        mitigations: list[str] = []

        for risk in p.risk_factors:
            risk_lower = risk.lower()
            if "negative yoy" in risk_lower or "price decline" in risk_lower:
                mitigations.append(
                    "Mitigate market decline risk by negotiating below "
                    "asking price and focusing on cash flow rather than "
                    "appreciation"
                )
            elif "mortgage rate" in risk_lower:
                mitigations.append(
                    "Consider adjustable-rate or buydown options to reduce "
                    "near-term costs, with refinancing when rates improve"
                )
            elif "pre-1940" in risk_lower or "seismic" in risk_lower:
                mitigations.append(
                    "Budget for a seismic retrofit inspection and obtain "
                    "estimates before purchase to avoid surprises"
                )
            elif "high-value" in risk_lower or "limited buyer" in risk_lower:
                mitigations.append(
                    "High-value properties can be offset by stronger "
                    "appreciation in premium neighborhoods and higher "
                    "quality tenants"
                )
            elif "adu construction" in risk_lower:
                mitigations.append(
                    "Get multiple contractor bids and pre-check permitting "
                    "feasibility before committing to ADU development"
                )
            elif "sb9" in risk_lower:
                mitigations.append(
                    "Engage a land surveyor early and consult with "
                    "Berkeley planning to validate SB9 feasibility"
                )
            elif "rent control" in risk_lower:
                mitigations.append(
                    "Rent control limits annual increases but newly "
                    "constructed ADUs are exempt, offsetting this constraint"
                )

        if not mitigations:
            mitigations.append(
                "Diversify across strategies and maintain adequate "
                "reserves to manage unforeseen expenses"
            )

        return " ".join(mitigations[:4])

    # ------------------------------------------------------------------
    # Mode detection
    # ------------------------------------------------------------------

    def _detect_mode(self, properties: list[dict]) -> str:
        """Auto-detect prospectus mode based on count and similarity."""
        count = len(properties)
        if count <= 1:
            return "single"
        if count > 10:
            return "thesis"

        # Check similarity for 2-10 properties
        neighborhoods = [p.get("neighborhood", "") for p in properties]
        zonings = [p.get("zoning_class", "") for p in properties]
        prices = [
            p.get("last_sale_price") or p.get("predicted_price") or 0
            for p in properties
        ]

        # Same neighborhood test
        if neighborhoods:
            most_common_nbr = max(set(neighborhoods), key=neighborhoods.count)
            nbr_ratio = neighborhoods.count(most_common_nbr) / count
        else:
            nbr_ratio = 0

        # Same zoning test
        valid_zonings = [z for z in zonings if z]
        if valid_zonings:
            most_common_zone = max(set(valid_zonings), key=valid_zonings.count)
            zone_ratio = valid_zonings.count(most_common_zone) / count
        else:
            zone_ratio = 0

        # Price similarity test (within 30% of median)
        valid_prices = [p for p in prices if p > 0]
        if valid_prices:
            median_price = sorted(valid_prices)[len(valid_prices) // 2]
            price_similar = (
                sum(1 for p in valid_prices if abs(p - median_price) / median_price < 0.3)
                / count
            )
        else:
            price_similar = 0

        if nbr_ratio >= 0.7 or zone_ratio >= 0.7 or price_similar >= 0.7:
            return "similar"

        return "curated"

    # ------------------------------------------------------------------
    # Lightweight generation (thesis mode, non-example properties)
    # ------------------------------------------------------------------

    def _generate_lightweight(self, prop_dict: dict) -> PropertyProspectus:
        """Generate a minimal prospectus with just basic fields + valuation."""
        p = PropertyProspectus()
        p.generated_at = datetime.now(timezone.utc).isoformat()

        p.address = prop_dict.get("address")
        p.neighborhood = prop_dict.get("neighborhood", "Berkeley")
        p.property_type = prop_dict.get("property_type", "Single Family Residential")
        p.beds = prop_dict.get("beds")
        p.baths = prop_dict.get("baths")
        p.sqft = prop_dict.get("sqft")
        p.year_built = prop_dict.get("year_built")
        p.lot_size_sqft = prop_dict.get("lot_size_sqft")
        p.zoning_class = prop_dict.get("zoning_class")

        # ML prediction for value
        try:
            pred = self.predict_fn(prop_dict, "prospectus")
            p.estimated_value = pred.get("predicted_price", 0)
            p.value_range_low = pred.get("price_lower", p.estimated_value)
            p.value_range_high = pred.get("price_upper", p.estimated_value)
            if p.sqft and p.estimated_value:
                p.value_per_sqft = int(p.estimated_value / p.sqft)
        except Exception as e:
            logger.warning("Lightweight prediction failed: %s", e)

        return p

    def _select_example_indices(
        self,
        properties: list[dict],
        down_payment_pct: float,
        investment_horizon_years: int,
    ) -> set[int]:
        """Pick 3-5 diverse example property indices for thesis mode.

        Generates full prospectuses for a sample to select from.
        """
        if len(properties) <= 5:
            return set(range(len(properties)))

        # Sample up to 8 evenly-spaced properties to evaluate
        step = max(1, len(properties) // 8)
        sample_indices = list(range(0, len(properties), step))[:8]

        # Always include first and last
        if 0 not in sample_indices:
            sample_indices.insert(0, 0)
        last = len(properties) - 1
        if last not in sample_indices:
            sample_indices.append(last)

        # Generate prospectuses for samples to evaluate metrics
        samples: list[tuple[int, PropertyProspectus]] = []
        for idx in sample_indices:
            try:
                p = self._generate_single(
                    properties[idx], down_payment_pct, investment_horizon_years,
                )
                samples.append((idx, p))
            except Exception:
                continue

        if len(samples) <= 5:
            return {idx for idx, _ in samples}

        # Select diverse examples
        selected: set[int] = set()

        # Highest cap rate
        by_cap = max(samples, key=lambda x: x[1].cap_rate_pct)
        selected.add(by_cap[0])

        # Best cash flow
        by_cf = max(samples, key=lambda x: x[1].monthly_cash_flow)
        selected.add(by_cf[0])

        # Highest development potential
        by_dev = max(samples, key=lambda x: x[1].effective_max_units)
        selected.add(by_dev[0])

        # Median value (most representative)
        by_value = sorted(samples, key=lambda x: x[1].estimated_value)
        selected.add(by_value[len(by_value) // 2][0])

        # If still < 5, add the lowest value for budget option
        if len(selected) < 5 and by_value[0][0] not in selected:
            selected.add(by_value[0][0])

        return selected

    # ------------------------------------------------------------------
    # Portfolio summary (multi-property)
    # ------------------------------------------------------------------

    def _build_portfolio_summary(
        self,
        prospectuses: list[PropertyProspectus],
        mode: str = "curated",
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
        neighborhoods = {p.neighborhood for p in prospectuses if p.neighborhood}
        approaches = {
            _STRATEGY_LABELS.get(p.recommended_approach, p.recommended_approach)
            for p in prospectuses
            if p.recommended_approach
        }
        notes_parts: list[str] = []
        if len(neighborhoods) > 1:
            notes_parts.append(
                f"Diversified across {len(neighborhoods)} neighborhoods: "
                f"{', '.join(sorted(neighborhoods))}"
            )
        elif neighborhoods:
            notes_parts.append(
                f"Concentrated in {next(iter(neighborhoods))}"
            )
        if len(approaches) > 1:
            notes_parts.append(
                f"Mixed strategies: {', '.join(sorted(approaches))}"
            )

        # Chart data — comparison metrics
        comparison_metrics = [
            {
                "address": p.address or p.neighborhood,
                "estimated_value": p.estimated_value,
                "cap_rate_pct": p.cap_rate_pct,
                "cash_on_cash_pct": p.cash_on_cash_pct,
                "monthly_cash_flow": p.monthly_cash_flow,
                "strategy": _STRATEGY_LABELS.get(
                    p.recommended_approach, p.recommended_approach,
                ),
            }
            for p in prospectuses
        ]

        # Chart data — allocations
        nbr_counter: Counter[str] = Counter()
        strat_counter: Counter[str] = Counter()
        for p in prospectuses:
            nbr_counter[p.neighborhood] += 1
            strat_counter[
                _STRATEGY_LABELS.get(p.recommended_approach, p.recommended_approach)
            ] += 1

        summary = PortfolioSummary(
            total_capital_required=total_capital,
            total_monthly_cash_flow=total_cf,
            weighted_avg_cap_rate=round(w_cap, 2),
            weighted_avg_coc=round(w_coc, 2),
            property_count=len(prospectuses),
            diversification_notes=". ".join(notes_parts),
            mode=mode,
            comparison_metrics=comparison_metrics,
            neighborhood_allocation=dict(nbr_counter),
            strategy_allocation=dict(strat_counter),
        )

        # Mode-specific data
        if mode == "similar":
            summary.shared_traits, summary.individual_differences = (
                self._analyze_similarity(prospectuses)
            )
        elif mode == "thesis":
            summary.group_statistics = self._compute_group_statistics(prospectuses)
            summary.example_property_indices = [
                i
                for i, p in enumerate(prospectuses)
                if p.scenarios  # has full analysis (not lightweight)
            ][:5]

        # Investment thesis narrative
        summary.investment_thesis = self._generate_investment_thesis(
            prospectuses, summary, mode,
        )

        return summary

    def _analyze_similarity(
        self, prospectuses: list[PropertyProspectus],
    ) -> tuple[list[str], list[str]]:
        """Find shared traits and individual differences for similar mode."""
        shared: list[str] = []
        diffs: list[str] = []

        neighborhoods = [p.neighborhood for p in prospectuses]
        zonings = [p.zoning_class for p in prospectuses if p.zoning_class]
        types_ = [p.property_type for p in prospectuses]
        values = [p.estimated_value for p in prospectuses if p.estimated_value]

        # Check neighborhood similarity
        nbr_counter = Counter(neighborhoods)
        dominant_nbr, dominant_count = nbr_counter.most_common(1)[0]
        if dominant_count == len(prospectuses):
            shared.append(f"All properties in {dominant_nbr}")
        elif dominant_count >= len(prospectuses) * 0.7:
            shared.append(f"Most properties in {dominant_nbr}")
        else:
            diffs.append(
                f"Spread across neighborhoods: "
                f"{', '.join(sorted(set(neighborhoods)))}"
            )

        # Check zoning similarity
        if zonings:
            zone_counter = Counter(zonings)
            dom_zone, dom_zone_count = zone_counter.most_common(1)[0]
            if dom_zone_count >= len(prospectuses) * 0.7:
                shared.append(f"Common zoning: {dom_zone}")
            else:
                diffs.append(
                    f"Mixed zoning: {', '.join(sorted(set(zonings)))}"
                )

        # Check property type similarity
        type_counter = Counter(types_)
        dom_type, dom_type_count = type_counter.most_common(1)[0]
        if dom_type_count == len(prospectuses):
            shared.append(f"All {dom_type}")

        # Check price range
        if values:
            min_v, max_v = min(values), max(values)
            if max_v > 0:
                spread_pct = (max_v - min_v) / max_v * 100
                if spread_pct < 25:
                    shared.append(
                        f"Similar price range: ${min_v:,.0f} – ${max_v:,.0f}"
                    )
                else:
                    diffs.append(
                        f"Price range: ${min_v:,.0f} – ${max_v:,.0f} "
                        f"({spread_pct:.0f}% spread)"
                    )

        # Individual metric differences
        caps = [p.cap_rate_pct for p in prospectuses]
        if caps:
            cap_range = max(caps) - min(caps)
            if cap_range > 1.0:
                diffs.append(
                    f"Cap rates vary from {min(caps):.1f}% to {max(caps):.1f}%"
                )

        return shared, diffs

    def _compute_group_statistics(
        self, prospectuses: list[PropertyProspectus],
    ) -> dict:
        """Compute aggregate statistics for thesis mode."""
        values = [p.estimated_value for p in prospectuses if p.estimated_value]
        caps = [p.cap_rate_pct for p in prospectuses if p.cap_rate_pct]
        cocs = [p.cash_on_cash_pct for p in prospectuses if p.cash_on_cash_pct]

        # Price distribution buckets
        buckets: list[dict] = []
        if values:
            min_v, max_v = min(values), max(values)
            bucket_size = max(100_000, (max_v - min_v) // 5)
            lower = (min_v // bucket_size) * bucket_size
            while lower <= max_v:
                upper = lower + bucket_size
                count = sum(1 for v in values if lower <= v < upper)
                if count > 0:
                    buckets.append({
                        "bracket": f"${lower / 1000:.0f}K–${upper / 1000:.0f}K",
                        "count": count,
                    })
                lower = upper

        nbr_counter = Counter(p.neighborhood for p in prospectuses)
        zone_counter = Counter(
            p.zoning_class for p in prospectuses if p.zoning_class
        )

        return {
            "count": len(prospectuses),
            "avg_price": int(statistics.mean(values)) if values else 0,
            "median_price": int(statistics.median(values)) if values else 0,
            "min_price": min(values) if values else 0,
            "max_price": max(values) if values else 0,
            "avg_cap_rate": round(statistics.mean(caps), 2) if caps else 0,
            "avg_coc": round(statistics.mean(cocs), 2) if cocs else 0,
            "price_distribution": buckets,
            "common_neighborhoods": [
                n for n, _ in nbr_counter.most_common(5)
            ],
            "common_zoning": [z for z, _ in zone_counter.most_common(5)],
        }

    def _generate_investment_thesis(
        self,
        prospectuses: list[PropertyProspectus],
        summary: PortfolioSummary,
        mode: str,
    ) -> str:
        """Generate a data-grounded investment thesis narrative."""
        count = summary.property_count
        total_cap = summary.total_capital_required
        avg_cap_rate = summary.weighted_avg_cap_rate
        avg_coc = summary.weighted_avg_coc
        total_cf = summary.total_monthly_cash_flow

        neighborhoods = sorted({p.neighborhood for p in prospectuses})
        nbr_str = ", ".join(neighborhoods[:5])
        if len(neighborhoods) > 5:
            nbr_str += f" and {len(neighborhoods) - 5} more"

        strategies = sorted({
            _STRATEGY_LABELS.get(p.recommended_approach, p.recommended_approach)
            for p in prospectuses
        })

        # Characterize returns
        if avg_cap_rate >= 5:
            return_char = "strong income-generating potential"
        elif avg_cap_rate >= 3:
            return_char = "balanced income and appreciation potential"
        else:
            return_char = "appreciation-driven returns"

        # Characterize cash flow
        if total_cf > 0:
            cf_char = f"positive aggregate cash flow of ${total_cf:,.0f}/month"
        else:
            cf_char = (
                f"negative near-term cash flow of ${total_cf:,.0f}/month, "
                f"offset by equity buildup and appreciation"
            )

        parts: list[str] = []

        if mode == "curated":
            parts.append(
                f"This curated portfolio of {count} Berkeley properties "
                f"across {nbr_str} requires ${total_cap:,.0f} in total "
                f"capital and offers {return_char}."
            )
            parts.append(
                f"The portfolio achieves a weighted average {avg_cap_rate:.1f}% "
                f"cap rate and {avg_coc:.1f}% cash-on-cash return with {cf_char}."
            )
            if len(strategies) > 1:
                parts.append(
                    f"Strategy diversification across {', '.join(strategies)} "
                    f"reduces concentration risk."
                )

        elif mode == "similar":
            trait_summary = (
                "; ".join(summary.shared_traits[:3])
                if summary.shared_traits
                else "similar characteristics"
            )
            parts.append(
                f"These {count} properties share {trait_summary}, "
                f"making them directly comparable investment options."
            )
            parts.append(
                f"Combined capital requirement is ${total_cap:,.0f} with "
                f"an average {avg_cap_rate:.1f}% cap rate and {cf_char}."
            )
            if summary.individual_differences:
                parts.append(
                    f"Key differences: {'; '.join(summary.individual_differences[:2])}."
                )

        elif mode == "thesis":
            stats = summary.group_statistics or {}
            median_price = stats.get("median_price", 0)
            parts.append(
                f"This investment thesis covers {count} Berkeley properties "
                f"with a median value of ${median_price:,.0f} across {nbr_str}."
            )
            parts.append(
                f"The portfolio offers {return_char} with a weighted average "
                f"{avg_cap_rate:.1f}% cap rate requiring ${total_cap:,.0f} "
                f"total capital."
            )
            parts.append(
                f"Representative examples are provided to illustrate "
                f"how the investment strategy applies across different "
                f"property profiles."
            )

        return " ".join(parts)


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
        # Narrative commentaries
        "valuation_commentary": p.valuation_commentary,
        "market_position_commentary": p.market_position_commentary,
        "scenario_recommendation_narrative": p.scenario_recommendation_narrative,
        "comps_analysis_narrative": p.comps_analysis_narrative,
        "risk_mitigation_narrative": p.risk_mitigation_narrative,
        # Best scenario detail for charts
        "best_scenario_detail": p.best_scenario_detail,
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
        # Multi-property mode
        "mode": ps.mode,
        "investment_thesis": ps.investment_thesis,
        # Similar mode
        "shared_traits": ps.shared_traits,
        "individual_differences": ps.individual_differences,
        # Thesis mode
        "group_statistics": ps.group_statistics,
        "example_property_indices": ps.example_property_indices,
        # Chart data
        "comparison_metrics": ps.comparison_metrics,
        "neighborhood_allocation": ps.neighborhood_allocation,
        "strategy_allocation": ps.strategy_allocation,
    }
