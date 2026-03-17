"""Edge case and boundary tests for all 10 gap tools.

Covers zero-input guards, boundary conditions, negative inputs,
and formula verification that the primary test files don't cover.
"""

import pytest

from homebuyer.services.faketor.tools.gap.true_cost import (
    TrueCostParams,
    _calc_monthly_pi,
    _calc_monthly_pmi,
    _pmi_rate_for_ltv,
    calc_pmi_dropoff_month,
    compute_true_cost,
)
from homebuyer.services.faketor.tools.gap.rent_vs_buy import (
    RentVsBuyParams,
    compute_rent_vs_buy,
)
from homebuyer.services.faketor.tools.gap.pmi_model import (
    PmiModelParams,
    _pmi_rate_for_ltv as pmi_rate_for_ltv,
    _simulate_pmi_timeline,
    compute_pmi_model,
)
from homebuyer.services.faketor.tools.gap.rate_penalty import (
    RatePenaltyParams,
    _find_breakeven_rate,
    _monthly_payment,
    compute_rate_penalty,
)
from homebuyer.services.faketor.tools.gap.competition import (
    CompetitionParams,
    _compute_dom_distribution,
    _normalize_score,
    _score_label,
    compute_competition,
)
from homebuyer.services.faketor.tools.gap.dual_property import (
    DualPropertyParams,
    compute_dual_property,
)
from homebuyer.services.faketor.tools.gap.yield_ranking import (
    PropertyForRanking,
    YieldRankingParams,
    compute_yield_ranking,
)
from homebuyer.services.faketor.tools.gap.appreciation_stress import (
    AppreciationScenario,
    AppreciationStressParams,
    compute_appreciation_stress,
)
from homebuyer.services.faketor.tools.gap.neighborhood_lifestyle import (
    NeighborhoodLifestyleParams,
    compute_neighborhood_lifestyle,
)
from homebuyer.services.faketor.tools.gap.adjacent_market import (
    AdjacentMarketParams,
    compute_adjacent_market,
)


# ==========================================================================
# TRUE_COST edge cases
# ==========================================================================


class TestTrueCostEdgeCases:
    """Zero-input, boundary, and formula verification for true_cost."""

    def test_zero_purchase_price(self):
        """Zero price → all components are zero."""
        result = compute_true_cost(TrueCostParams(purchase_price=0))
        assert result["total_monthly_cost"] == 0
        assert result["monthly_principal_and_interest"] == 0
        assert result["monthly_pmi"] == 0

    def test_zero_loan_amount_100pct_down(self):
        """100% down payment → no P&I, no PMI."""
        result = compute_true_cost(TrueCostParams(
            purchase_price=1_000_000, down_payment_pct=100.0
        ))
        assert result["loan_amount"] == 0
        assert result["monthly_principal_and_interest"] == 0
        assert result["monthly_pmi"] == 0
        assert result["is_pmi_applicable"] is False

    def test_pmi_rate_ltv_boundary_exactly_80(self):
        """LTV exactly at 80% → no PMI (must be > 80%)."""
        rate = _pmi_rate_for_ltv(0.80)
        assert rate == 0.0

    def test_pmi_rate_ltv_boundary_80_01(self):
        """LTV at 80.01% → triggers 0.75% PMI bracket."""
        rate = _pmi_rate_for_ltv(0.8001)
        assert rate == 0.0075

    def test_pmi_rate_ltv_boundary_exactly_85(self):
        """LTV exactly at 85% → 0.75% bracket (inclusive upper bound)."""
        rate = _pmi_rate_for_ltv(0.85)
        assert rate == 0.0075

    def test_pmi_rate_ltv_boundary_85_01(self):
        """LTV at 85.01% → triggers 1.10% high-risk bracket."""
        rate = _pmi_rate_for_ltv(0.8501)
        assert rate == 0.0110

    def test_pmi_rate_ltv_above_95(self):
        """LTV above 95% → no matching bracket, returns 0."""
        rate = _pmi_rate_for_ltv(0.96)
        assert rate == 0.0

    def test_pmi_dropoff_zero_rate(self):
        """Zero mortgage rate → straight-line principal paydown."""
        month = calc_pmi_dropoff_month(
            loan_amount=900_000, purchase_price=1_000_000, annual_rate_pct=0.0
        )
        # LTV = 90%, target = 80% = $800k. Need to pay down $100k.
        # Monthly payment = $900k/360 = $2,500. Months = $100k/$2500 = 40
        assert month is not None
        assert month == 40

    def test_pmi_dropoff_no_pmi_needed(self):
        """Loan is 80% LTV → PMI not applicable, returns None."""
        month = calc_pmi_dropoff_month(
            loan_amount=800_000, purchase_price=1_000_000, annual_rate_pct=6.5
        )
        assert month is None

    def test_pmi_dropoff_zero_loan(self):
        """Zero loan amount → returns None."""
        month = calc_pmi_dropoff_month(
            loan_amount=0, purchase_price=1_000_000, annual_rate_pct=6.5
        )
        assert month is None

    def test_unknown_construction_type_defaults_to_wood(self):
        """Unknown construction type falls back to wood_frame rate."""
        r1 = compute_true_cost(TrueCostParams(
            purchase_price=1_000_000, construction_type="unknown_type"
        ))
        r2 = compute_true_cost(TrueCostParams(
            purchase_price=1_000_000, construction_type="wood_frame"
        ))
        assert r1["monthly_earthquake_insurance"] == r2["monthly_earthquake_insurance"]

    def test_negative_rent_delta(self):
        """Ownership cheaper than rent → negative delta, 'less_than_rent'."""
        result = compute_true_cost(TrueCostParams(
            purchase_price=300_000,
            down_payment_pct=20.0,
            mortgage_rate=4.0,
            current_rent=5_000,
        ))
        assert result["monthly_delta_vs_rent"] < 0
        assert result["delta_direction"] == "less_than_rent"

    def test_exact_rent_equal(self):
        """When rent exactly equals ownership cost → 'equal'."""
        result = compute_true_cost(TrueCostParams(
            purchase_price=1_000_000,
            down_payment_pct=20.0,
            mortgage_rate=6.5,
        ))
        total = result["total_monthly_cost"]
        # Now compute with rent = total
        result2 = compute_true_cost(TrueCostParams(
            purchase_price=1_000_000,
            down_payment_pct=20.0,
            mortgage_rate=6.5,
            current_rent=total,
        ))
        assert result2["delta_direction"] == "equal"
        assert result2["monthly_delta_vs_rent"] == 0

    def test_masonry_higher_earthquake_than_wood(self):
        """Masonry rate (0.60%) > wood_frame rate (0.25%)."""
        wood = compute_true_cost(TrueCostParams(
            purchase_price=1_000_000, construction_type="wood_frame"
        ))
        masonry = compute_true_cost(TrueCostParams(
            purchase_price=1_000_000, construction_type="masonry"
        ))
        assert masonry["monthly_earthquake_insurance"] > wood["monthly_earthquake_insurance"]


# ==========================================================================
# RENT_VS_BUY edge cases
# ==========================================================================


class TestRentVsBuyEdgeCases:
    """Zero-input, negative appreciation, and formula verification."""

    def test_zero_purchase_price(self):
        """Zero price → buying is effectively free; crossover at year 1."""
        result = compute_rent_vs_buy(RentVsBuyParams(
            purchase_price=0, current_rent=3000
        ))
        assert result["crossover_year"] == 1

    def test_negative_appreciation(self):
        """Negative appreciation → home loses value; buying is worse."""
        result = compute_rent_vs_buy(RentVsBuyParams(
            purchase_price=1_000_000,
            down_payment_pct=20.0,
            mortgage_rate=6.5,
            annual_appreciation_pct=-5.0,
            current_rent=3_000,
            monthly_ownership_cost=7_000,
            horizon_years=15,
        ))
        # With -5% annual depreciation, renting should be cheaper
        assert result["crossover_year"] is None

    def test_horizon_capped_at_30(self):
        """Horizon exceeding 30 is capped to max."""
        result = compute_rent_vs_buy(RentVsBuyParams(
            purchase_price=1_000_000, horizon_years=50
        ))
        assert result["horizon_years"] == 30

    def test_zero_rent(self):
        """Zero rent → buying is always more expensive."""
        result = compute_rent_vs_buy(RentVsBuyParams(
            purchase_price=1_000_000,
            monthly_ownership_cost=5_000,
            current_rent=0,
            horizon_years=10,
        ))
        # With zero rent, cumulative_rent_net stays 0, buying always loses
        assert result["crossover_year"] is None

    def test_all_cash_no_mortgage(self):
        """100% down → no P&I, no interest, simpler amortization."""
        result = compute_rent_vs_buy(RentVsBuyParams(
            purchase_price=1_000_000,
            down_payment_pct=100.0,
            mortgage_rate=6.5,
            current_rent=4_000,
            monthly_ownership_cost=2_000,
            annual_appreciation_pct=3.0,
            horizon_years=10,
        ))
        # No loan means remaining_balance stays at 0
        last = result["yearly_comparison"][-1]
        assert last["remaining_balance"] == 0

    def test_pmi_dropoff_exactly_at_year_boundary(self):
        """PMI dropping at exactly month 12 → year 1 boundary."""
        result = compute_rent_vs_buy(RentVsBuyParams(
            purchase_price=1_000_000,
            monthly_ownership_cost=6_000,
            monthly_pmi=200,
            pmi_dropoff_month=12,  # exactly end of year 1
            current_rent=4_000,
            horizon_years=3,
        ))
        # Year 1: full PMI all 12 months
        y1 = result["yearly_comparison"][0]
        assert y1["annual_ownership_cost"] == 6_000 * 12
        # Year 2: no PMI (month 13+ is after dropoff month 12)
        y2 = result["yearly_comparison"][1]
        assert y2["annual_ownership_cost"] == (6_000 - 200) * 12


# ==========================================================================
# PMI_MODEL edge cases
# ==========================================================================


class TestPmiModelEdgeCases:
    """Zero-rate, LTV boundaries, and wait analysis edge cases."""

    def test_zero_purchase_price(self):
        """Zero price → no PMI applicable."""
        result = compute_pmi_model(PmiModelParams(purchase_price=0))
        assert result["pmi_applicable"] is False

    def test_exactly_20_pct_down_no_pmi(self):
        """Exactly 20% down → LTV = 80% → no PMI."""
        result = compute_pmi_model(PmiModelParams(
            purchase_price=1_000_000, down_payment_pct=20.0
        ))
        assert result["pmi_applicable"] is False
        assert result["monthly_pmi"] == 0

    def test_19_99_pct_down_triggers_pmi(self):
        """19.99% down → LTV > 80% → PMI applies."""
        result = compute_pmi_model(PmiModelParams(
            purchase_price=1_000_000, down_payment_pct=19.99
        ))
        assert result["pmi_applicable"] is True
        assert result["monthly_pmi"] > 0

    def test_simulate_timeline_zero_loan(self):
        """Zero loan → empty timeline."""
        snapshots = _simulate_pmi_timeline(0, 1_000_000, 6.5, 3.0)
        assert snapshots == []

    def test_simulate_timeline_zero_price(self):
        """Zero price → empty timeline."""
        snapshots = _simulate_pmi_timeline(900_000, 0, 6.5, 3.0)
        assert snapshots == []

    def test_simulate_timeline_zero_rate(self):
        """Zero rate → straight-line paydown, still tracks PMI."""
        snapshots = _simulate_pmi_timeline(900_000, 1_000_000, 0.0, 0.0)
        assert len(snapshots) > 0
        # Balance should decrease each month
        for i in range(1, len(snapshots)):
            assert snapshots[i]["balance"] <= snapshots[i - 1]["balance"]

    def test_wait_analysis_zero_savings(self):
        """Zero monthly savings → savings_gained is 0."""
        result = compute_pmi_model(PmiModelParams(
            purchase_price=1_000_000,
            down_payment_pct=10.0,
            monthly_savings=0,
            wait_months=12,
        ))
        assert result["wait_analysis"] is not None
        assert result["wait_analysis"]["savings_gained"] == 0

    def test_high_down_payment_no_wait_needed(self):
        """25% down → no PMI, wait analysis is None by default."""
        result = compute_pmi_model(PmiModelParams(
            purchase_price=1_000_000, down_payment_pct=25.0
        ))
        assert result["wait_analysis"] is None


# ==========================================================================
# RATE_PENALTY edge cases
# ==========================================================================


class TestRatePenaltyEdgeCases:
    """Zero-loan, zero-rate, breakeven precision, and boundary tests."""

    def test_zero_existing_balance(self):
        """Zero balance → existing payment is 0."""
        result = compute_rate_penalty(RatePenaltyParams(
            existing_balance=0, existing_rate=3.0,
            new_purchase_price=1_000_000, new_rate=7.0,
        ))
        assert result["existing_monthly_payment"] == 0
        assert result["monthly_penalty"] > 0

    def test_zero_rate_existing(self):
        """Zero rate → straight-line payment = balance / term."""
        payment = _monthly_payment(360_000, 0.0, 360)
        assert payment == 1000  # 360k / 360 months

    def test_zero_rate_zero_term(self):
        """Zero rate and zero term → returns 0."""
        payment = _monthly_payment(100_000, 0.0, 0)
        assert payment == 0

    def test_breakeven_rate_zero_loan(self):
        """Zero loan → no breakeven possible."""
        result = _find_breakeven_rate(0, 2000)
        assert result is None

    def test_breakeven_rate_zero_target(self):
        """Zero target payment → no breakeven."""
        result = _find_breakeven_rate(800_000, 0)
        assert result is None

    def test_breakeven_rate_reasonable(self):
        """Breakeven rate should be lower than the new rate."""
        result = compute_rate_penalty(RatePenaltyParams(
            existing_balance=400_000, existing_rate=3.0,
            new_purchase_price=1_200_000, new_rate=7.0,
        ))
        if result["breakeven_rate"] is not None:
            assert result["breakeven_rate"] < result["new_rate"]

    def test_same_rate_zero_penalty(self):
        """Same rate and same loan → zero penalty."""
        result = compute_rate_penalty(RatePenaltyParams(
            existing_balance=500_000, existing_rate=6.5,
            new_purchase_price=625_000,  # 80% = $500k loan
            new_down_payment_pct=20.0,
            new_rate=6.5,
        ))
        assert result["monthly_penalty"] == 0

    def test_income_none_skips_pct(self):
        """No income → penalty_pct_of_income is None."""
        result = compute_rate_penalty(RatePenaltyParams(
            existing_balance=400_000, existing_rate=3.0,
            new_purchase_price=1_000_000, new_rate=7.0,
            annual_gross_income=None,
        ))
        assert result["penalty_pct_of_income"] is None
        assert result["is_tolerable"] is None

    def test_tolerable_rate_with_high_income(self):
        """High income → at least one scenario rate is tolerable.

        With $1M income ($83k/mo) and a ~$2k penalty, penalty_pct ≈ 2.5%
        which is well under the 5% tolerable threshold.
        """
        result = compute_rate_penalty(RatePenaltyParams(
            existing_balance=300_000, existing_rate=3.0,
            new_purchase_price=800_000, new_rate=7.0,
            annual_gross_income=1_000_000,
        ))
        assert result["tolerable_rate"] is not None


# ==========================================================================
# COMPETITION edge cases
# ==========================================================================


class TestCompetitionEdgeCases:
    """DOM distribution boundaries, score normalization, and empty data."""

    def test_normalize_score_at_hot_bound(self):
        """Value at hot bound → score 100."""
        assert _normalize_score(1.05, 1.05, 0.95) == 100.0

    def test_normalize_score_at_cold_bound(self):
        """Value at cold bound → score 0."""
        assert _normalize_score(0.95, 1.05, 0.95) == 0.0

    def test_normalize_score_beyond_hot(self):
        """Value beyond hot → clamped to 100."""
        assert _normalize_score(1.10, 1.05, 0.95) == 100.0

    def test_normalize_score_below_cold(self):
        """Value below cold → clamped to 0."""
        assert _normalize_score(0.90, 1.05, 0.95) == 0.0

    def test_normalize_score_equal_bounds(self):
        """Hot == cold → neutral 50."""
        assert _normalize_score(5.0, 5.0, 5.0) == 50.0

    def test_score_label_all_thresholds(self):
        """Verify all 5 label tiers."""
        assert _score_label(85) == "Very Competitive"
        assert _score_label(65) == "Competitive"
        assert _score_label(45) == "Moderate"
        assert _score_label(25) == "Buyer-Friendly"
        assert _score_label(5) == "Very Buyer-Friendly"

    def test_score_label_exact_boundaries(self):
        """Boundary values: 80, 60, 40, 20, 0."""
        assert _score_label(80) == "Very Competitive"
        assert _score_label(60) == "Competitive"
        assert _score_label(40) == "Moderate"
        assert _score_label(20) == "Buyer-Friendly"
        assert _score_label(0) == "Very Buyer-Friendly"

    def test_dom_distribution_single_value(self):
        """Single DOM value → p25 = p75 = that value."""
        dist = _compute_dom_distribution([15])
        assert dist["p25"] == 15
        assert dist["p75"] == 15
        assert dist["median"] == 15

    def test_dom_distribution_two_values(self):
        """Two values → p25 = min, p75 = max."""
        dist = _compute_dom_distribution([5, 30])
        assert dist["p25"] == 5
        assert dist["p75"] == 30

    def test_dom_distribution_three_values(self):
        """Three values → p25 = min, p75 = max (n < 4)."""
        dist = _compute_dom_distribution([5, 15, 30])
        assert dist["p25"] == 5
        assert dist["p75"] == 30

    def test_dom_distribution_four_values_uses_quantiles(self):
        """Four values → uses statistics.quantiles(n=4)."""
        dist = _compute_dom_distribution([5, 10, 20, 40])
        assert dist["p25"] is not None
        assert dist["p75"] is not None
        # p25 should be between min and median, p75 between median and max
        assert dist["min"] <= dist["p25"] <= dist["median"]
        assert dist["median"] <= dist["p75"] <= dist["max"]

    def test_zero_inventory_zero_sales(self):
        """Both zero → absorption is neutral."""
        result = compute_competition(CompetitionParams(
            active_listings=0, monthly_closed_sales=0.0,
        ))
        assert result["absorption_rate"] is None
        assert result["competition_score"] == 50.0  # all neutral defaults

    def test_mixed_some_data_some_not(self):
        """Sale-to-list present but no DOM or above-asking → partial scores."""
        result = compute_competition(CompetitionParams(
            sale_to_list_ratios=[1.02, 1.03, 1.01],
            dom_values=[],
            above_asking_flags=[],
        ))
        assert result["sale_to_list_median"] is not None
        assert result["dom_distribution"]["median"] is None
        assert result["above_asking_pct"] is None


# ==========================================================================
# DUAL_PROPERTY edge cases
# ==========================================================================


class TestDualPropertyEdgeCases:
    """Zero-input, HELOC rate zero, and cash-out refi fallback."""

    def test_zero_investment_price(self):
        """Zero investment price → all investment fields zero."""
        result = compute_dual_property(DualPropertyParams(
            primary_value=1_000_000,
            investment_price=0,
        ))
        assert result["investment"]["monthly_gross_rent"] == 0
        assert result["investment"]["monthly_net_cash_flow"] == 0

    def test_zero_extraction_amount(self):
        """Zero extraction → no monthly increase on primary."""
        result = compute_dual_property(DualPropertyParams(
            primary_value=1_000_000,
            primary_mortgage_balance=400_000,
            extraction_amount=0,
            investment_price=500_000,
            investment_monthly_rent=3_000,
        ))
        assert result["extraction"]["monthly_increase"] == 0

    def test_cashout_refi_fallback_rate(self):
        """Cash-out refi with no explicit rate → uses investment_rate."""
        result = compute_dual_property(DualPropertyParams(
            primary_value=1_000_000,
            primary_mortgage_balance=400_000,
            extraction_method="cashout_refi",
            extraction_amount=200_000,
            cashout_refi_rate=None,
            investment_rate=7.5,
            investment_price=600_000,
            investment_monthly_rent=3_000,
        ))
        assert result["extraction"]["refi_rate"] == 7.5

    def test_100_pct_down_on_investment(self):
        """100% down → no debt service on investment."""
        result = compute_dual_property(DualPropertyParams(
            primary_value=1_000_000,
            primary_mortgage_balance=0,
            investment_price=500_000,
            investment_down_payment_pct=100.0,
            investment_monthly_rent=3_000,
        ))
        assert result["investment"]["monthly_debt_service"] == 0
        assert result["investment"]["loan_amount"] == 0

    def test_max_heloc_negative_equity(self):
        """Mortgage > 80% of value → max HELOC is 0 (clamped)."""
        result = compute_dual_property(DualPropertyParams(
            primary_value=500_000,
            primary_mortgage_balance=450_000,  # 90% LTV
            investment_price=300_000,
            investment_monthly_rent=2_000,
        ))
        assert result["max_heloc_amount"] == 0

    def test_cash_on_cash_zero_invested(self):
        """Zero invested cash → cash_on_cash is 0.0."""
        result = compute_dual_property(DualPropertyParams(
            primary_value=1_000_000,
            investment_price=500_000,
            investment_down_payment_pct=0.0,  # 0% down
            investment_monthly_rent=3_000,
        ))
        # With 0% down, total_cash_invested = 0
        assert result["cash_on_cash_pct"] == 0.0

    def test_stress_tests_always_4_scenarios(self):
        """Stress tests always produce exactly 4 scenarios."""
        result = compute_dual_property(DualPropertyParams(
            primary_value=1_000_000,
            primary_mortgage_balance=400_000,
            extraction_amount=100_000,
            investment_price=600_000,
            investment_monthly_rent=3_500,
        ))
        assert len(result["stress_tests"]) == 4
        assert result["worst_case_scenario"] is not None


# ==========================================================================
# YIELD_RANKING edge cases
# ==========================================================================


class TestYieldRankingEdgeCases:
    """Zero-price skip, zero-rate, DSCR edge, and single-property."""

    def test_zero_price_property_skipped(self):
        """Property with price=0 is skipped from rankings."""
        result = compute_yield_ranking(YieldRankingParams(
            properties=[
                PropertyForRanking(address="A", price=0, monthly_rent=2000),
                PropertyForRanking(address="B", price=500_000, monthly_rent=3000),
            ]
        ))
        assert result["property_count"] == 1
        assert result["ranked_by_spread"][0]["address"] == "B"

    def test_100_pct_down_no_debt_service(self):
        """100% down → monthly_ds = 0, DSCR = 999.0 (sentinel)."""
        result = compute_yield_ranking(YieldRankingParams(
            properties=[PropertyForRanking(price=500_000, monthly_rent=3000)],
            down_payment_pct=100.0,
        ))
        r = result["ranked_by_dscr"][0]
        assert r["monthly_debt_service"] == 0
        assert r["dscr"] == 999.0

    def test_zero_rent_all_negative(self):
        """Zero rent → all cash flows negative."""
        result = compute_yield_ranking(YieldRankingParams(
            properties=[PropertyForRanking(price=500_000, monthly_rent=0)],
            down_payment_pct=25.0,
        ))
        r = result["ranked_by_spread"][0]
        assert r["monthly_cash_flow"] < 0
        assert result["positive_cash_flow_count"] == 0

    def test_single_property_is_best_in_all(self):
        """Single property → it's best in all rankings."""
        result = compute_yield_ranking(YieldRankingParams(
            properties=[PropertyForRanking(price=500_000, monthly_rent=3000)],
        ))
        assert result["best_leverage_spread"] is not None
        assert result["best_dscr"] is not None
        assert result["best_cash_on_cash"] is not None

    def test_empty_properties(self):
        """Empty list → counts are all zero."""
        result = compute_yield_ranking(YieldRankingParams(properties=[]))
        assert result["property_count"] == 0
        assert result["best_leverage_spread"] is None


# ==========================================================================
# APPRECIATION_STRESS edge cases
# ==========================================================================


class TestAppreciationStressEdgeCases:
    """Custom scenarios, zero down, refi same rate, short horizon."""

    def test_custom_scenarios(self):
        """Custom scenario list overrides defaults."""
        result = compute_appreciation_stress(AppreciationStressParams(
            purchase_price=1_000_000,
            scenarios=[
                AppreciationScenario(name="Custom +10%", annual_appreciation_pct=10.0),
                AppreciationScenario(name="Custom -20%", annual_appreciation_pct=-20.0),
            ],
        ))
        assert result["scenario_count"] == 2
        assert result["scenarios"][0]["scenario_name"] == "Custom +10%"
        assert result["scenarios"][1]["scenario_name"] == "Custom -20%"

    def test_zero_down_payment(self):
        """0% down → full loan, higher carry."""
        result = compute_appreciation_stress(AppreciationStressParams(
            purchase_price=1_000_000,
            down_payment_pct=0.0,
            mortgage_rate=7.0,
            exit_years=[5],
        ))
        assert result["down_payment_amount"] == 0
        assert result["monthly_carry_cost"] > 0

    def test_refi_same_rate_zero_savings(self):
        """Refi at same rate → zero monthly savings."""
        result = compute_appreciation_stress(AppreciationStressParams(
            purchase_price=1_000_000,
            mortgage_rate=7.0,
            refi_rate=7.0,
            exit_years=[5],
        ))
        assert result["refi_analysis"] is not None
        assert result["refi_analysis"]["monthly_savings"] == 0

    def test_single_exit_year(self):
        """Single exit year → one exit per scenario."""
        result = compute_appreciation_stress(AppreciationStressParams(
            purchase_price=1_000_000,
            exit_years=[1],
        ))
        for scenario in result["scenarios"]:
            assert len(scenario["exits"]) == 1

    def test_all_cash_purchase(self):
        """100% cash → no mortgage costs, no refi possible."""
        result = compute_appreciation_stress(AppreciationStressParams(
            purchase_price=1_000_000,
            down_payment_pct=100.0,
            mortgage_rate=7.0,
            refi_rate=5.0,
            exit_years=[5],
        ))
        # With 100% down, loan = 0. Refi analysis should still work but with 0 PI
        assert result["monthly_ownership_cost"] > 0  # taxes + insurance + maintenance
        # Even bull scenario should be profitable with no debt
        bull = next(s for s in result["scenarios"] if "Bull" in s["scenario_name"])
        assert any(e["is_profitable"] for e in bull["exits"])

    def test_crash_scenario_loss(self):
        """Crash (-15%/yr) for 3 years → significant loss."""
        result = compute_appreciation_stress(AppreciationStressParams(
            purchase_price=1_000_000,
            exit_years=[3],
        ))
        crash = next(s for s in result["scenarios"] if "Crash" in s["scenario_name"])
        assert crash["exits"][0]["is_profitable"] is False
        assert crash["exits"][0]["profit"] < 0


# ==========================================================================
# NEIGHBORHOOD_LIFESTYLE edge cases
# ==========================================================================


class TestNeighborhoodLifestyleEdgeCases:
    """Zero weights, missing factors, all-unknown neighborhoods."""

    def test_all_zero_weights(self):
        """All weights = 0 → total_weight fallback to 1.0."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams(
            neighborhoods=["North Berkeley"],
            priority_walkability=0.0,
            priority_transit=0.0,
            priority_schools=0.0,
            priority_dining=0.0,
            priority_parks=0.0,
            priority_safety=0.0,
        ))
        # Should still compute without division by zero
        assert result["neighborhoods_compared"] == 1
        assert result["comparisons"][0]["composite_score"] == 0.0

    def test_heavily_weighted_single_factor(self):
        """Only schools weighted → ranking follows school scores."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams(
            neighborhoods=["North Berkeley", "South Berkeley", "Claremont"],
            priority_walkability=0.0,
            priority_transit=0.0,
            priority_schools=10.0,
            priority_dining=0.0,
            priority_parks=0.0,
            priority_safety=0.0,
        ))
        # Claremont and North Berkeley both have schools=9
        scores = {c["neighborhood"]: c["scores"]["schools"] for c in result["comparisons"]}
        # Best overall should be one with schools=9
        best = result["comparisons"][0]
        assert best["scores"]["schools"] >= 9

    def test_all_unknown_neighborhoods(self):
        """All unknown neighborhoods → empty comparisons."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams(
            neighborhoods=["Atlantis", "Narnia"]
        ))
        assert result["neighborhoods_compared"] == 0
        assert result["best_overall"] is None

    def test_empty_neighborhoods_uses_all(self):
        """Empty list → compares all 10 known neighborhoods."""
        result = compute_neighborhood_lifestyle(NeighborhoodLifestyleParams())
        assert result["neighborhoods_compared"] == 10


# ==========================================================================
# ADJACENT_MARKET edge cases
# ==========================================================================


class TestAdjacentMarketEdgeCases:
    """Affordability tier boundaries, requirements filtering, unknown markets."""

    def test_affordability_boundary_exactly_1_3(self):
        """Budget / median = 1.3 → 'Very Affordable'."""
        # Berkeley median = 1,350,000. Budget = 1,350,000 * 1.3 = 1,755,000
        result = compute_adjacent_market(AdjacentMarketParams(budget=1_755_000))
        berkeley = next(c for c in result["comparisons"] if c["market"] == "Berkeley")
        assert berkeley["affordability"] == "Very Affordable"

    def test_affordability_boundary_exactly_1_0(self):
        """Budget / median = 1.0 → 'Affordable'."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=1_350_000))
        berkeley = next(c for c in result["comparisons"] if c["market"] == "Berkeley")
        assert berkeley["affordability"] == "Affordable"

    def test_affordability_boundary_below_0_8(self):
        """Budget / median < 0.8 → 'Out of Range'."""
        # Berkeley median = 1,350,000. Budget < 1,080,000
        result = compute_adjacent_market(AdjacentMarketParams(budget=500_000))
        berkeley = next(c for c in result["comparisons"] if c["market"] == "Berkeley")
        assert berkeley["affordability"] == "Out of Range"

    def test_bart_filter_excludes_non_bart(self):
        """must_have_bart=True → non-BART markets fail requirements."""
        result = compute_adjacent_market(AdjacentMarketParams(
            budget=1_500_000, must_have_bart=True,
        ))
        for c in result["comparisons"]:
            if not c["bart_access"]:
                assert c["meets_requirements"] is False

    def test_commute_filter(self):
        """max_commute_minutes=25 → most markets fail commute check."""
        result = compute_adjacent_market(AdjacentMarketParams(
            budget=1_500_000, max_commute_minutes=25,
        ))
        passing = [c for c in result["comparisons"] if c["meets_requirements"]]
        # Only markets with commute <= 25 should pass
        for c in passing:
            assert c["commute_sf_minutes"] <= 25

    def test_unknown_market_skipped(self):
        """Unknown market in list → silently skipped."""
        result = compute_adjacent_market(AdjacentMarketParams(
            budget=1_000_000, markets=["Berkeley", "Atlantis", "Albany"]
        ))
        markets = [c["market"] for c in result["comparisons"]]
        assert "Atlantis" not in markets
        assert result["markets_compared"] == 2

    def test_zero_budget(self):
        """Zero budget → all markets are 'Out of Range'."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=0))
        for c in result["comparisons"]:
            assert c["affordability"] == "Out of Range"
            assert c["budget_ratio"] == 0.0

    def test_sqft_bonus_negative_when_budget_low(self):
        """Low budget → affordable_sqft < typical → negative sqft_bonus."""
        result = compute_adjacent_market(AdjacentMarketParams(budget=500_000))
        for c in result["comparisons"]:
            if c["price_per_sqft"] > 0:
                expected_sqft = int(round(500_000 / c["price_per_sqft"]))
                assert c["affordable_sqft"] == expected_sqft
                assert c["sqft_bonus"] == expected_sqft - c["typical_sqft"]
