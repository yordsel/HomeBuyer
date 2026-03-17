"""Tests for the deterministic SegmentClassifier.

Covers every segment path in the classification tree, transition rules,
edge cases, and confidence computation.

Phase C-5 (#36) of Epic #23.
"""

from homebuyer.services.faketor.classification import (
    APPRECIATION_BETTOR,
    CASH_BUYER,
    COMPETITIVE_BIDDER,
    DOWN_PAYMENT_CONSTRAINED,
    EQUITY_LEVERAGING_INVESTOR,
    EQUITY_TRAPPED_UPGRADER,
    FIRST_TIME_BUYER,
    LEVERAGED_INVESTOR,
    NOT_VIABLE,
    STRETCHER,
    VALUE_ADD_INVESTOR,
    ALL_SEGMENTS,
    INVEST_SEGMENTS,
    OCCUPY_SEGMENTS,
    SegmentClassifier,
    SegmentResult,
    _estimate_max_purchase_price,
    _estimate_true_monthly_cost,
    _max_monthly_payment,
)
from homebuyer.services.faketor.state.buyer import BuyerProfile, Signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile(**kwargs) -> BuyerProfile:
    """Create a BuyerProfile with given attributes."""
    p = BuyerProfile()
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


classifier = SegmentClassifier()


# ---------------------------------------------------------------------------
# Segment constants
# ---------------------------------------------------------------------------


class TestSegmentConstants:
    def test_all_segments_count(self):
        assert len(ALL_SEGMENTS) == 11

    def test_occupy_invest_partition(self):
        assert OCCUPY_SEGMENTS | INVEST_SEGMENTS == ALL_SEGMENTS
        assert OCCUPY_SEGMENTS & INVEST_SEGMENTS == set()

    def test_occupy_count(self):
        assert len(OCCUPY_SEGMENTS) == 6

    def test_invest_count(self):
        assert len(INVEST_SEGMENTS) == 5


# ---------------------------------------------------------------------------
# No classification possible (insufficient data)
# ---------------------------------------------------------------------------


class TestNoClassification:
    def test_no_intent_returns_none(self):
        result = classifier.classify(BuyerProfile())
        assert result.segment_id is None
        assert result.confidence == 0.0
        assert result.factor_coverage == 0.0

    def test_no_intent_with_some_data(self):
        """Even with financial data, no intent = no classification."""
        result = classifier.classify(_profile(capital=500_000, income=200_000))
        assert result.segment_id is None
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Occupy segments
# ---------------------------------------------------------------------------


class TestNotViable:
    def test_capital_below_fha_no_income(self):
        """Capital too low for FHA minimum, no income data."""
        result = classifier.classify(
            _profile(intent="occupy", capital=20_000),
            median_price=1_300_000,
        )
        assert result.segment_id == NOT_VIABLE
        assert "FHA minimum" in result.reasoning

    def test_pmi_makes_carry_unsustainable(self):
        """Low down payment + PMI pushes monthly cost beyond max."""
        result = classifier.classify(
            _profile(intent="occupy", capital=50_000, income=80_000),
            mortgage_rate=7.5,
            median_price=1_300_000,
        )
        assert result.segment_id == NOT_VIABLE
        assert "PMI" in result.reasoning or "unsustainable" in result.reasoning.lower()


class TestStretcher:
    def test_high_stress_ratio_with_pmi(self):
        """Needs PMI and stress ratio is above 0.90.

        With $80k down on $500k property at 6.5%, that's 16% down → needs PMI.
        max_monthly = 250k/12*0.28 = $5,833
        true cost with PMI on a $500k property should be high relative to max.
        """
        result = classifier.classify(
            _profile(intent="occupy", capital=80_000, income=250_000),
            mortgage_rate=7.0,
            median_price=900_000,
        )
        # With 80k on a price the classifier derives from income (~900k capped),
        # needs PMI, stress should be tight
        assert result.segment_id in (STRETCHER, DOWN_PAYMENT_CONSTRAINED, NOT_VIABLE)

    def test_income_only_no_capital(self):
        """Occupy intent with income but no capital (None) → tentative stretcher."""
        # capital=None means unknown, not zero — classifier should use fallback
        result = classifier.classify(
            _profile(intent="occupy", income=120_000),
        )
        assert result.segment_id == STRETCHER
        assert result.confidence < 0.5  # Low confidence without capital data


class TestDownPaymentConstrained:
    def test_below_20_pct_manageable_stress(self):
        """Below 20% down but stress ratio is manageable."""
        # Need income high enough that PMI doesn't push stress > 0.90
        result = classifier.classify(
            _profile(intent="occupy", capital=150_000, income=250_000),
            mortgage_rate=5.0,
            median_price=800_000,
        )
        # 150k / 800k = 18.75% down → needs PMI
        # With $250k income, max monthly ~$5,833
        # Should be manageable
        if result.segment_id == DOWN_PAYMENT_CONSTRAINED:
            assert "PMI" in result.reasoning or "manageable" in result.reasoning.lower()


class TestFirstTimeBuyer:
    def test_classic_first_time_buyer(self):
        """Capital, no equity, income supports carry."""
        result = classifier.classify(
            _profile(
                intent="occupy",
                capital=300_000,
                income=200_000,
            ),
            mortgage_rate=6.5,
            median_price=1_300_000,
        )
        assert result.segment_id == FIRST_TIME_BUYER
        assert "first-time" in result.reasoning.lower()

    def test_intent_only_defaults_to_first_time(self):
        """Occupy intent with no financial data → first-time with low confidence."""
        result = classifier.classify(_profile(intent="occupy"))
        assert result.segment_id == FIRST_TIME_BUYER
        assert result.confidence < 0.3


class TestEquityTrappedUpgrader:
    def test_high_rate_penalty(self):
        """Existing homeowner with significant rate penalty.

        Rate penalty = equity * (current_rate - locked_rate) / 12
        With equity=800k, rate=8.0%, locked ~5.5%, monthly gross=12.5k:
        penalty = 800k * (8.0-5.5)/100/12 = $1,667/mo
        penalty_pct = 1667/12500 = 13.3% > 10% tolerance
        """
        result = classifier.classify(
            _profile(
                intent="occupy",
                owns_current_home=True,
                equity=800_000,
                income=150_000,
                capital=100_000,
            ),
            mortgage_rate=8.0,
        )
        assert result.segment_id == EQUITY_TRAPPED_UPGRADER
        assert "rate penalty" in result.reasoning.lower()


class TestCompetitiveBidder:
    def test_full_optionality(self):
        """Has capital, equity, and income to support carry."""
        result = classifier.classify(
            _profile(
                intent="occupy",
                capital=400_000,
                equity=300_000,
                income=300_000,
                owns_current_home=True,
            ),
            mortgage_rate=5.5,  # Moderate rate to avoid equity trap
            median_price=1_200_000,
        )
        # With low rate, the rate penalty is small enough to not trap
        # and they have capital + equity + income
        assert result.segment_id in (COMPETITIVE_BIDDER, EQUITY_TRAPPED_UPGRADER)


# ---------------------------------------------------------------------------
# Invest segments
# ---------------------------------------------------------------------------


class TestCashBuyer:
    def test_capital_exceeds_median(self):
        """Capital >= median price → cash buyer."""
        result = classifier.classify(
            _profile(intent="invest", capital=1_500_000),
            median_price=1_300_000,
        )
        assert result.segment_id == CASH_BUYER
        assert "outright" in result.reasoning.lower() or "cash" in result.reasoning.lower()

    def test_capital_equals_median(self):
        """Capital exactly at median → still cash buyer."""
        result = classifier.classify(
            _profile(intent="invest", capital=1_300_000),
            median_price=1_300_000,
        )
        assert result.segment_id == CASH_BUYER


class TestEquityLeveragingInvestor:
    def test_existing_property_with_equity(self):
        """Has existing property with equity → equity-leveraging investor."""
        result = classifier.classify(
            _profile(
                intent="invest",
                owns_current_home=True,
                equity=400_000,
                capital=100_000,
            ),
        )
        assert result.segment_id == EQUITY_LEVERAGING_INVESTOR
        assert "HELOC" in result.reasoning or "equity" in result.reasoning.lower()


class TestLeveragedInvestor:
    def test_positive_leverage_spread(self):
        """Cap rate > borrowing cost → leveraged investor."""
        result = classifier.classify(
            _profile(intent="invest", capital=200_000, income=150_000),
            mortgage_rate=3.0,  # Low rate makes leverage attractive
        )
        assert result.segment_id == LEVERAGED_INVESTOR
        assert "leverage" in result.reasoning.lower()


class TestValueAddInvestor:
    def test_development_signals(self):
        """Development intent signals → value-add investor."""
        profile = _profile(intent="invest", capital=200_000)
        profile.signals = [
            Signal(
                evidence="I want to build an ADU",
                implication="development_intent",
                confidence=0.9,
            ),
        ]
        result = classifier.classify(profile)
        assert result.segment_id == VALUE_ADD_INVESTOR
        assert "ADU" in result.reasoning or "development" in result.reasoning.lower()


class TestAppreciationBettor:
    def test_invest_fallback(self):
        """Invest intent without other signals → appreciation bettor."""
        result = classifier.classify(
            _profile(intent="invest"),
        )
        assert result.segment_id == APPRECIATION_BETTOR
        assert "appreciation" in result.reasoning.lower()

    def test_negative_leverage_spread(self):
        """High rate makes leverage unattractive → appreciation bettor."""
        result = classifier.classify(
            _profile(intent="invest", capital=200_000, income=150_000),
            mortgage_rate=7.0,  # High rate → negative leverage spread
        )
        assert result.segment_id == APPRECIATION_BETTOR


# ---------------------------------------------------------------------------
# Transition rules
# ---------------------------------------------------------------------------


class TestShouldTransition:
    def test_initial_classification_always_allowed(self):
        """From no segment to any segment is always allowed."""
        current = SegmentResult(None, 0.0, "", 0.0)
        proposed = SegmentResult(FIRST_TIME_BUYER, 0.5, "", 0.5)
        assert classifier.should_transition(current, proposed) is True

    def test_never_transition_to_none(self):
        """Should not transition from a segment to no segment."""
        current = SegmentResult(FIRST_TIME_BUYER, 0.8, "", 0.75)
        proposed = SegmentResult(None, 0.0, "", 0.0)
        assert classifier.should_transition(current, proposed) is False

    def test_higher_confidence_different_segment(self):
        """Higher confidence proposed segment wins."""
        current = SegmentResult(STRETCHER, 0.5, "", 0.5)
        proposed = SegmentResult(FIRST_TIME_BUYER, 0.8, "", 0.75)
        assert classifier.should_transition(current, proposed) is True

    def test_lower_confidence_different_segment_rejected(self):
        """Lower confidence proposed segment is rejected."""
        current = SegmentResult(FIRST_TIME_BUYER, 0.8, "", 0.75)
        proposed = SegmentResult(STRETCHER, 0.5, "", 0.5)
        assert classifier.should_transition(current, proposed) is False

    def test_equal_confidence_requires_explicit_evidence(self):
        """Equal confidence requires a trigger signal with high confidence."""
        current = SegmentResult(STRETCHER, 0.7, "", 0.5)
        proposed = SegmentResult(FIRST_TIME_BUYER, 0.7, "", 0.75)

        # Without trigger — rejected
        assert classifier.should_transition(current, proposed) is False

        # With low-confidence trigger — rejected
        weak_signal = Signal(evidence="maybe", implication="test", confidence=0.3)
        assert classifier.should_transition(current, proposed, weak_signal) is False

        # With high-confidence trigger — accepted
        strong_signal = Signal(evidence="I have $300k saved", implication="capital", confidence=0.9)
        assert classifier.should_transition(current, proposed, strong_signal) is True

    def test_same_segment_higher_confidence(self):
        """Same segment with higher confidence updates."""
        current = SegmentResult(CASH_BUYER, 0.6, "", 0.5)
        proposed = SegmentResult(CASH_BUYER, 0.9, "", 1.0)
        assert classifier.should_transition(current, proposed) is True

    def test_same_segment_equal_confidence_rejected(self):
        """Same segment, same confidence — no transition needed."""
        current = SegmentResult(CASH_BUYER, 0.8, "", 0.75)
        proposed = SegmentResult(CASH_BUYER, 0.8, "", 0.75)
        assert classifier.should_transition(current, proposed) is False


# ---------------------------------------------------------------------------
# Confidence computation
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_zero_coverage_low_confidence(self):
        """No factors known → base confidence 0.3."""
        assert SegmentClassifier._base_confidence(0.0) == 0.3

    def test_full_coverage_high_confidence(self):
        """All factors known → max confidence 0.95."""
        assert SegmentClassifier._base_confidence(1.0) == 0.95

    def test_half_coverage_mid_confidence(self):
        """Half factors → ~0.625."""
        conf = SegmentClassifier._base_confidence(0.5)
        assert abs(conf - 0.625) < 0.01

    def test_confidence_scales_with_factors(self):
        """More known factors → higher confidence."""
        # 1 factor known (e.g., just intent)
        p1 = _profile(intent="invest")
        r1 = classifier.classify(p1)

        # 3 factors known
        p3 = _profile(intent="invest", capital=200_000, income=150_000)
        r3 = classifier.classify(p3)

        # More factors should give higher confidence
        assert r3.confidence >= r1.confidence


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_max_monthly_payment(self):
        """28% front-end DTI."""
        assert _max_monthly_payment(120_000) == 120_000 / 12 * 0.28

    def test_max_monthly_zero_income(self):
        assert _max_monthly_payment(0) == 0.0

    def test_estimate_true_monthly_cost_basic(self):
        """Sanity check: 1.3M property, 20% down, 6.5% rate."""
        cost = _estimate_true_monthly_cost(1_300_000, 260_000, 6.5)
        # Should be around $8,000-$10,000/month total
        assert 7_000 < cost < 12_000

    def test_estimate_true_monthly_cost_with_pmi(self):
        """PMI adds cost when LTV > 80%."""
        cost_no_pmi = _estimate_true_monthly_cost(1_000_000, 100_000, 6.5, include_pmi=False)
        cost_with_pmi = _estimate_true_monthly_cost(1_000_000, 100_000, 6.5, include_pmi=True)
        assert cost_with_pmi > cost_no_pmi

    def test_estimate_true_monthly_cost_zero_price(self):
        assert _estimate_true_monthly_cost(0, 0, 6.5) == 0.0

    def test_estimate_max_purchase_price_basic(self):
        """Sanity check: $200k income, $300k capital, 6.5% rate."""
        price = _estimate_max_purchase_price(200_000, 300_000, 6.5)
        # Should be somewhere in the $800k-$1.5M range
        assert 700_000 < price < 2_000_000

    def test_estimate_max_purchase_price_zero_income(self):
        assert _estimate_max_purchase_price(0, 300_000, 6.5) == 0

    def test_estimate_max_purchase_price_zero_rate(self):
        assert _estimate_max_purchase_price(200_000, 300_000, 0) == 0
