"""Deterministic segment classifier for the segment-driven Faketor redesign.

Implements the classification tree from the design doc Section 1.3.2 and 6.5.2.
Pure functions — no LLM, no DB, no side effects. Given the same BuyerProfile
and MarketSnapshot, always produces the same segment.

Phase C-2 (#33) of Epic #23.
"""

from __future__ import annotations

from dataclasses import dataclass

from homebuyer.services.faketor.state.buyer import BuyerProfile, Signal


# ---------------------------------------------------------------------------
# SegmentResult — output of classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentResult:
    """Result of a segment classification.

    ``segment_id`` is ``None`` when there's insufficient data to classify.
    ``confidence`` is 0.0–1.0, driven by factor coverage (how many of the
    4 core factors are known).
    """

    segment_id: str | None
    confidence: float
    reasoning: str
    factor_coverage: float  # 0.0–1.0 based on known core factors


@dataclass(frozen=True)
class SegmentCandidate:
    """A scored segment candidate with disambiguation info.

    Used by ``classify_with_alternatives()`` to return the top-N candidates
    so the prompt can show alternatives and ask targeted follow-up questions.
    """

    segment_id: str
    confidence: float
    reasoning: str
    distinguishing_factor: str  # what would disambiguate from adjacent candidates


# ---------------------------------------------------------------------------
# Segment IDs — canonical string identifiers
# ---------------------------------------------------------------------------

# Occupy segments
NOT_VIABLE = "not_viable"
STRETCHER = "stretcher"
FIRST_TIME_BUYER = "first_time_buyer"
DOWN_PAYMENT_CONSTRAINED = "down_payment_constrained"
EQUITY_TRAPPED_UPGRADER = "equity_trapped_upgrader"
COMPETITIVE_BIDDER = "competitive_bidder"

# Invest segments
CASH_BUYER = "cash_buyer"
EQUITY_LEVERAGING_INVESTOR = "equity_leveraging_investor"
LEVERAGED_INVESTOR = "leveraged_investor"
VALUE_ADD_INVESTOR = "value_add_investor"
APPRECIATION_BETTOR = "appreciation_bettor"

ALL_SEGMENTS = frozenset({
    NOT_VIABLE, STRETCHER, FIRST_TIME_BUYER, DOWN_PAYMENT_CONSTRAINED,
    EQUITY_TRAPPED_UPGRADER, COMPETITIVE_BIDDER,
    CASH_BUYER, EQUITY_LEVERAGING_INVESTOR, LEVERAGED_INVESTOR,
    VALUE_ADD_INVESTOR, APPRECIATION_BETTOR,
})

OCCUPY_SEGMENTS = frozenset({
    NOT_VIABLE, STRETCHER, FIRST_TIME_BUYER, DOWN_PAYMENT_CONSTRAINED,
    EQUITY_TRAPPED_UPGRADER, COMPETITIVE_BIDDER,
})

INVEST_SEGMENTS = frozenset({
    CASH_BUYER, EQUITY_LEVERAGING_INVESTOR, LEVERAGED_INVESTOR,
    VALUE_ADD_INVESTOR, APPRECIATION_BETTOR,
})


# ---------------------------------------------------------------------------
# Market defaults for Berkeley (used when MarketSnapshot isn't available)
# ---------------------------------------------------------------------------

# Berkeley median home price — used as reference for affordability calculations
_DEFAULT_BERKELEY_MEDIAN = 1_300_000

# FHA minimum down payment percentage
_FHA_MINIMUM_PCT = 0.035

# Monthly stress ratio threshold: above this → stretcher, below → DP constrained
_STRESS_RATIO_THRESHOLD = 0.90

# Rate penalty tolerance threshold (as fraction of monthly gross income)
_RATE_PENALTY_TOLERANCE = 0.10

# Minimum viable supply pool (properties in lookback window)
_MIN_SUPPLY_POOL = 5


# ---------------------------------------------------------------------------
# Helper: estimate max purchase price from income
# ---------------------------------------------------------------------------


def _estimate_max_purchase_price(
    income: int,
    capital: int,
    mortgage_rate: float,
) -> int:
    """Estimate maximum purchase price from income using standard DTI ratios.

    Uses 28% front-end DTI (housing expenses / gross income).
    This is a rough heuristic for classification, not an underwriting decision.
    """
    if income <= 0 or mortgage_rate <= 0:
        return 0

    max_monthly_housing = income / 12 * 0.28  # 28% front-end DTI
    # Approximate: 30-year monthly payment per $1000 borrowed
    # Formula: r * (1+r)^n / ((1+r)^n - 1) where r = monthly rate, n = 360
    monthly_rate = mortgage_rate / 100 / 12
    if monthly_rate <= 0:
        return 0
    payment_per_1000 = (
        monthly_rate * (1 + monthly_rate) ** 360
        / ((1 + monthly_rate) ** 360 - 1)
    ) * 1000

    # Deduct estimated property tax (~1.17%) and insurance (~0.35%) from housing budget
    # These are annual percentages of home value, converted to monthly
    piti_overhead_monthly_pct = (1.17 + 0.35) / 100 / 12  # ~0.127% per month
    # max_monthly_housing = PI + (price * piti_overhead_monthly_pct)
    # PI = (price - down_payment) * payment_per_1000 / 1000
    # Solve for price given capital as down payment
    # This is approximate — iterate once for reasonable accuracy
    if capital > 0:
        # Assume capital is down payment
        # Loan = price - capital
        # PI = loan * payment_per_1000 / 1000
        # max_monthly = PI + price * piti_overhead
        # max_monthly = (price - capital) * ppk/1000 + price * overhead
        # max_monthly = price * (ppk/1000 + overhead) - capital * ppk/1000
        ppk = payment_per_1000 / 1000
        price = (max_monthly_housing + capital * ppk) / (ppk + piti_overhead_monthly_pct)
        return max(0, int(price))
    else:
        # No down payment — theoretical max based on 97% LTV
        ppk = payment_per_1000 / 1000 * 0.97  # 97% LTV
        price = max_monthly_housing / (ppk + piti_overhead_monthly_pct)
        return max(0, int(price))


def _estimate_true_monthly_cost(
    price: int,
    down_payment: int,
    mortgage_rate: float,
    include_pmi: bool = False,
) -> float:
    """Estimate true monthly cost of ownership for a given property price.

    Includes P&I, property tax (1.17%), insurance (0.35%), earthquake (0.15%),
    maintenance (1%), and optional PMI (0.5%).
    """
    if price <= 0 or mortgage_rate <= 0:
        return 0.0

    loan = max(0, price - down_payment)
    monthly_rate = mortgage_rate / 100 / 12

    # P&I
    if loan > 0 and monthly_rate > 0:
        pi = loan * (
            monthly_rate * (1 + monthly_rate) ** 360
            / ((1 + monthly_rate) ** 360 - 1)
        )
    else:
        pi = 0.0

    # Property tax (Berkeley ~1.17% of value / 12)
    prop_tax = price * 0.0117 / 12

    # Homeowner's insurance (0.35% of value / 12)
    insurance = price * 0.0035 / 12

    # Earthquake insurance (0.15% of value / 12)
    earthquake = price * 0.0015 / 12

    # Maintenance (1% of value / 12)
    maintenance = price * 0.01 / 12

    total = pi + prop_tax + insurance + earthquake + maintenance

    # PMI (0.5% of loan / 12, only if LTV > 80%)
    if include_pmi and loan > price * 0.80:
        pmi = loan * 0.005 / 12
        total += pmi

    return total


def _max_monthly_payment(income: int) -> float:
    """Maximum monthly housing payment based on 28% front-end DTI."""
    return income / 12 * 0.28 if income > 0 else 0.0


# ---------------------------------------------------------------------------
# SegmentClassifier
# ---------------------------------------------------------------------------


class SegmentClassifier:
    """Deterministic segment classifier.

    Implements the classification tree from the design doc Section 1.3.2.
    Takes a BuyerProfile and market parameters and returns a SegmentResult.

    This is a pure function — no state, no side effects, no LLM calls.
    """

    def classify(
        self,
        profile: BuyerProfile,
        mortgage_rate: float = 6.5,
        median_price: int = _DEFAULT_BERKELEY_MEDIAN,
    ) -> SegmentResult:
        """Classify the buyer into a segment.

        Returns SegmentResult with segment_id=None and confidence=0.0
        if insufficient information (no intent known).

        Args:
            profile: The buyer's current profile.
            mortgage_rate: Current 30-year mortgage rate (e.g. 6.5).
            median_price: Berkeley median home price for reference.
        """
        factor_coverage = profile.known_factor_count() / 4.0

        # Cannot classify without intent
        if profile.intent is None:
            return SegmentResult(
                segment_id=None,
                confidence=0.0,
                reasoning="Cannot classify: intent not yet determined",
                factor_coverage=factor_coverage,
            )

        if profile.intent == "occupy":
            return self._classify_occupy(
                profile, mortgage_rate, median_price, factor_coverage
            )
        else:  # invest
            return self._classify_invest(
                profile, mortgage_rate, median_price, factor_coverage
            )

    def _classify_occupy(
        self,
        profile: BuyerProfile,
        rate: float,
        median_price: int,
        factor_coverage: float,
    ) -> SegmentResult:
        """Classify an occupy-intent buyer.

        Distinguishes between None (unknown) and 0 (known to be zero) for
        financial fields. When a factor is None, the classifier skips checks
        that depend on it rather than treating it as $0.
        """
        capital = profile.capital  # None = unknown, 0 = known zero
        equity = profile.equity
        income = profile.income
        has_existing = profile.owns_current_home is True

        # Effective values for math (treat None as 0 for arithmetic)
        cap_val = capital if capital is not None else 0
        eq_val = equity if equity is not None else 0
        inc_val = income if income is not None else 0

        # Use median price as target when we don't know better
        target_price = median_price

        # Estimate max purchase price from income
        if inc_val > 0:
            max_price = _estimate_max_purchase_price(inc_val, cap_val, rate)
            target_price = min(max_price, median_price)
        else:
            max_price = 0

        max_monthly = _max_monthly_payment(inc_val)

        # --- Not Viable checks (only when capital is known) ---

        # Can't meet FHA minimum (3.5% of target price)
        if capital is not None and cap_val > 0 and cap_val < target_price * _FHA_MINIMUM_PCT:
            if inc_val == 0 or max_monthly == 0:
                return SegmentResult(
                    segment_id=NOT_VIABLE,
                    confidence=self._base_confidence(factor_coverage),
                    reasoning=(
                        f"Capital ${cap_val:,} below FHA minimum "
                        f"(3.5% of ${target_price:,} = ${int(target_price * 0.035):,}) "
                        f"and insufficient income data"
                    ),
                    factor_coverage=factor_coverage,
                )

        # If we have no financial data at all, default to first-time buyer
        if capital is None and income is None and equity is None:
            return SegmentResult(
                segment_id=FIRST_TIME_BUYER,
                confidence=max(0.2, factor_coverage * 0.5),
                reasoning=(
                    "Occupy intent detected but no financial data yet. "
                    "Defaulting to first-time buyer with low confidence."
                ),
                factor_coverage=factor_coverage,
            )

        # --- Down payment analysis (only when capital is known) ---
        if capital is not None and target_price > 0:
            down_payment_pct = cap_val / target_price
            needs_pmi = down_payment_pct < 0.20 and eq_val == 0

            if needs_pmi and inc_val > 0:
                true_cost = _estimate_true_monthly_cost(
                    target_price, cap_val, rate, include_pmi=True
                )

                if true_cost > max_monthly and max_monthly > 0:
                    return SegmentResult(
                        segment_id=NOT_VIABLE,
                        confidence=self._base_confidence(factor_coverage),
                        reasoning=(
                            f"True monthly cost ${true_cost:,.0f} exceeds "
                            f"max monthly ${max_monthly:,.0f} with PMI. "
                            f"Down payment {down_payment_pct:.1%} requires PMI."
                        ),
                        factor_coverage=factor_coverage,
                    )

                if down_payment_pct < _FHA_MINIMUM_PCT:
                    return SegmentResult(
                        segment_id=NOT_VIABLE,
                        confidence=self._base_confidence(factor_coverage),
                        reasoning=(
                            f"Down payment {down_payment_pct:.1%} below "
                            f"FHA minimum of {_FHA_MINIMUM_PCT:.1%}"
                        ),
                        factor_coverage=factor_coverage,
                    )

                # Stretcher vs. Down Payment Constrained
                stress_ratio = true_cost / max_monthly if max_monthly > 0 else 1.0
                if stress_ratio > _STRESS_RATIO_THRESHOLD:
                    return SegmentResult(
                        segment_id=STRETCHER,
                        confidence=self._base_confidence(factor_coverage),
                        reasoning=(
                            f"Monthly stress ratio {stress_ratio:.2f} > "
                            f"{_STRESS_RATIO_THRESHOLD}. Needs PMI, budget is tight."
                        ),
                        factor_coverage=factor_coverage,
                    )
                else:
                    return SegmentResult(
                        segment_id=DOWN_PAYMENT_CONSTRAINED,
                        confidence=self._base_confidence(factor_coverage),
                        reasoning=(
                            f"Below 20% down ({down_payment_pct:.1%}), needs PMI, "
                            f"but stress ratio {stress_ratio:.2f} is manageable."
                        ),
                        factor_coverage=factor_coverage,
                    )

        # --- Equity-Trapped Upgrader ---
        # Check this BEFORE competitive bidder — a homeowner with high rate
        # penalty should be classified as trapped even if they have resources
        if has_existing and eq_val > 0 and inc_val > 0:
            monthly_gross = inc_val / 12
            # Simplified rate penalty: assume locked at ~2.5pp below current
            estimated_locked_rate = max(rate - 2.5, 2.5)
            old_pi = eq_val * (estimated_locked_rate / 100 / 12)
            new_pi = eq_val * (rate / 100 / 12)
            rate_penalty = new_pi - old_pi
            penalty_pct = rate_penalty / monthly_gross if monthly_gross > 0 else 0

            if penalty_pct > _RATE_PENALTY_TOLERANCE:
                return SegmentResult(
                    segment_id=EQUITY_TRAPPED_UPGRADER,
                    confidence=self._base_confidence(factor_coverage),
                    reasoning=(
                        f"Rate penalty ~${rate_penalty:,.0f}/mo "
                        f"({penalty_pct:.1%} of monthly gross). "
                        f"Equity-trapped at current rate environment."
                    ),
                    factor_coverage=factor_coverage,
                )

        # --- Competitive Bidder ---
        if eq_val > 0 and cap_val > 0 and inc_val > 0:
            true_cost = _estimate_true_monthly_cost(target_price, cap_val + eq_val, rate)
            if max_monthly > 0 and true_cost <= max_monthly:
                return SegmentResult(
                    segment_id=COMPETITIVE_BIDDER,
                    confidence=self._base_confidence(factor_coverage),
                    reasoning=(
                        "Has capital, equity, and income to support carry. "
                        "Full optionality in the market."
                    ),
                    factor_coverage=factor_coverage,
                )

        # --- First-Time Buyer ---
        if cap_val > 0 and eq_val == 0 and inc_val > 0:
            return SegmentResult(
                segment_id=FIRST_TIME_BUYER,
                confidence=self._base_confidence(factor_coverage),
                reasoning=(
                    f"Occupy intent, ${cap_val:,} capital, no equity, "
                    f"income supports carry. Classic first-time buyer profile."
                ),
                factor_coverage=factor_coverage,
            )

        # --- Fallback: classify based on available info ---
        if inc_val > 0 and capital is None:
            # Has income but capital unknown yet
            return SegmentResult(
                segment_id=STRETCHER,
                confidence=max(0.3, factor_coverage * 0.5),
                reasoning=(
                    "Occupy intent with income but no capital data. "
                    "Tentatively classified as stretcher pending capital info."
                ),
                factor_coverage=factor_coverage,
            )

        # Default occupy fallback
        return SegmentResult(
            segment_id=FIRST_TIME_BUYER,
            confidence=max(0.2, factor_coverage * 0.4),
            reasoning="Occupy intent with partial data. Low confidence classification.",
            factor_coverage=factor_coverage,
        )

    def _classify_invest(
        self,
        profile: BuyerProfile,
        rate: float,
        median_price: int,
        factor_coverage: float,
    ) -> SegmentResult:
        """Classify an invest-intent buyer."""
        capital = profile.capital or 0
        equity = profile.equity or 0
        has_existing = profile.owns_current_home is True

        # --- Cash Buyer ---
        # Check explicit capital threshold
        if capital >= median_price:
            return SegmentResult(
                segment_id=CASH_BUYER,
                confidence=self._base_confidence(factor_coverage),
                reasoning=(
                    f"Capital ${capital:,} >= median price ${median_price:,}. "
                    f"Can buy outright without financing."
                ),
                factor_coverage=factor_coverage,
            )

        # Check for implicit cash signals (e.g., "all-cash", "no mortgage")
        cash_signals = [
            s for s in profile.signals
            if "cash_buyer" in s.implication.lower()
            and s.confidence >= 0.7
        ]
        if cash_signals:
            return SegmentResult(
                segment_id=CASH_BUYER,
                confidence=min(
                    self._base_confidence(factor_coverage),
                    max(s.confidence for s in cash_signals),
                ),
                reasoning=(
                    f"Cash buyer signal detected: "
                    f"{cash_signals[0].evidence[:80]}. "
                    f"Capital amount unknown but buyer indicated all-cash intent."
                ),
                factor_coverage=factor_coverage,
            )

        # --- Equity-Leveraging Investor ---
        if has_existing and equity > 0:
            return SegmentResult(
                segment_id=EQUITY_LEVERAGING_INVESTOR,
                confidence=self._base_confidence(factor_coverage),
                reasoning=(
                    f"Has existing property with ${equity:,} equity. "
                    f"Can leverage via HELOC or cash-out refi."
                ),
                factor_coverage=factor_coverage,
            )

        # --- Leveraged Investor ---
        # Has capital + income to service debt, using leverage to invest.
        # Note: leverage spread (cap rate vs borrowing cost) informs advice
        # framing, not segment eligibility — in high-rate environments the
        # spread is negative but investors still use leverage intentionally.
        if capital > 0 and profile.income and profile.income > 0:
            estimated_cap_rate = 0.035
            leverage_spread = estimated_cap_rate - (rate / 100)
            spread_note = (
                f"Positive leverage spread ({estimated_cap_rate:.1%} cap > "
                f"{rate / 100:.1%} rate) — leverage amplifies returns."
                if leverage_spread > 0
                else (
                    f"Negative leverage spread ({estimated_cap_rate:.1%} cap < "
                    f"{rate / 100:.1%} rate) — cash flow negative but may "
                    f"benefit from appreciation and tax advantages."
                )
            )
            return SegmentResult(
                segment_id=LEVERAGED_INVESTOR,
                confidence=self._base_confidence(factor_coverage),
                reasoning=spread_note,
                factor_coverage=factor_coverage,
            )

        # --- Value-Add Investor ---
        # Detected from signals about development, renovation, ADU
        dev_signals = [
            s for s in profile.signals
            if any(kw in s.implication.lower() for kw in (
                "development", "renovation", "adu", "value_add", "flip", "rehab"
            ))
        ]
        if dev_signals:
            return SegmentResult(
                segment_id=VALUE_ADD_INVESTOR,
                confidence=self._base_confidence(factor_coverage),
                reasoning=(
                    f"Development intent signals detected: "
                    f"{', '.join(s.evidence[:50] for s in dev_signals[:3])}"
                ),
                factor_coverage=factor_coverage,
            )

        # --- Appreciation Bettor (default invest fallback) ---
        return SegmentResult(
            segment_id=APPRECIATION_BETTOR,
            confidence=max(0.3, self._base_confidence(factor_coverage) * 0.8),
            reasoning=(
                "Invest intent without clear leverage advantage or development "
                "focus. Classified as appreciation bettor (betting on price gains)."
            ),
            factor_coverage=factor_coverage,
        )

    def should_transition(
        self,
        current: SegmentResult,
        proposed: SegmentResult,
        trigger_signal: Signal | None = None,
    ) -> bool:
        """Determine whether a segment transition should occur.

        Implements the transition rules from the design doc Section 6.5.4:
        - Higher confidence always replaces lower
        - Equal confidence requires explicit evidence (trigger_signal)
        - Never transitions to None segment
        - Never transitions from a real segment to the same segment
          (handled upstream in TurnState.promote)
        """
        # Never transition to unclassified
        if proposed.segment_id is None:
            return False

        # Always allow initial classification
        if current.segment_id is None:
            return True

        # Different segment: higher confidence wins
        if proposed.segment_id != current.segment_id:
            if proposed.confidence > current.confidence:
                return True
            # Equal confidence requires explicit evidence
            if (
                proposed.confidence == current.confidence
                and trigger_signal is not None
                and trigger_signal.confidence >= 0.7
            ):
                return True
            return False

        # Same segment: only update if higher confidence
        return proposed.confidence > current.confidence

    def classify_with_alternatives(
        self,
        profile: BuyerProfile,
        mortgage_rate: float = 6.5,
        median_price: int = _DEFAULT_BERKELEY_MEDIAN,
        max_candidates: int = 3,
    ) -> list[SegmentCandidate]:
        """Classify buyer and return top-N scored candidates.

        Unlike ``classify()`` which returns only the winner, this method
        returns up to ``max_candidates`` plausible segments with confidence
        scores and distinguishing factors. This lets the prompt renderer
        show alternatives and ask targeted disambiguation questions.

        Returns empty list if no classification is possible (no intent).
        """
        primary = self.classify(profile, mortgage_rate, median_price)
        if primary.segment_id is None:
            return []

        # Score all segments in the same intent group
        if profile.intent == "occupy":
            candidate_pool = OCCUPY_SEGMENTS
        else:
            candidate_pool = INVEST_SEGMENTS

        scored: list[SegmentCandidate] = []
        for seg_id in candidate_pool:
            if seg_id == primary.segment_id:
                scored.append(SegmentCandidate(
                    segment_id=seg_id,
                    confidence=primary.confidence,
                    reasoning=primary.reasoning,
                    distinguishing_factor="",
                ))
            else:
                # Score how plausible this alternative is
                alt_conf = self._score_alternative(
                    seg_id, profile, mortgage_rate, median_price,
                    primary.factor_coverage,
                )
                if alt_conf > 0.0:
                    factor = _DISTINGUISHING_FACTORS.get(
                        (primary.segment_id, seg_id),
                        _DISTINGUISHING_FACTORS.get(
                            (seg_id, primary.segment_id),
                            "additional financial details",
                        ),
                    )
                    scored.append(SegmentCandidate(
                        segment_id=seg_id,
                        confidence=alt_conf,
                        reasoning=f"Alternative to {primary.segment_id}",
                        distinguishing_factor=factor,
                    ))

        # Sort by confidence descending, take top N
        scored.sort(key=lambda c: c.confidence, reverse=True)
        return scored[:max_candidates]

    def _score_alternative(
        self,
        segment_id: str,
        profile: BuyerProfile,
        rate: float,
        median_price: int,
        factor_coverage: float,
    ) -> float:
        """Score how plausible an alternative segment is.

        Returns 0.0 if the segment is clearly impossible given known data.
        Returns a reduced confidence score if it's plausible but not the
        primary classification.
        """
        base = self._base_confidence(factor_coverage)
        capital = profile.capital
        equity = profile.equity
        income = profile.income
        has_existing = profile.owns_current_home is True

        # --- Invest segments ---
        if segment_id == CASH_BUYER:
            # Check for explicit cash signals first
            cash_signals = [
                s for s in profile.signals
                if "cash_buyer" in s.implication.lower()
                and s.confidence >= 0.7
            ]
            if cash_signals:
                return base * 0.9  # strong signal
            # Plausible if capital unknown (could be high) or capital > 0
            if capital is None:
                return base * 0.7  # unknown capital = maybe
            if capital >= median_price:
                return base  # definitely cash buyer
            return 0.0  # known capital too low

        if segment_id == LEVERAGED_INVESTOR:
            # Plausible if income exists or is unknown
            if income is not None and income > 0 and (capital is None or capital > 0):
                return base * 0.8
            if income is None and capital is None:
                return base * 0.5  # both unknown = maybe
            return 0.0

        if segment_id == EQUITY_LEVERAGING_INVESTOR:
            if has_existing and (equity is None or (equity is not None and equity > 0)):
                return base * 0.7
            return 0.0

        if segment_id == VALUE_ADD_INVESTOR:
            dev_signals = [
                s for s in profile.signals
                if any(kw in s.implication.lower() for kw in (
                    "development", "renovation", "adu", "value_add", "flip",
                ))
            ]
            return base * 0.6 if dev_signals else 0.0

        if segment_id == APPRECIATION_BETTOR:
            # Always plausible as invest fallback
            return max(0.2, base * 0.5)

        # --- Occupy segments ---
        if segment_id == FIRST_TIME_BUYER:
            if not has_existing and (equity is None or equity == 0):
                return base * 0.7
            return 0.0

        if segment_id == STRETCHER:
            if income is not None and income > 0:
                return base * 0.6
            if income is None:
                return base * 0.4
            return 0.0

        if segment_id == DOWN_PAYMENT_CONSTRAINED:
            if capital is not None and capital > 0:
                cap_val = capital
                dp_pct = cap_val / median_price if median_price > 0 else 0
                if dp_pct < 0.20:
                    return base * 0.7
            if capital is None:
                return base * 0.4
            return 0.0

        if segment_id == NOT_VIABLE:
            # Only plausible if capital is known and very low
            if capital is not None and capital < median_price * _FHA_MINIMUM_PCT:
                return base * 0.5
            return 0.0

        if segment_id == EQUITY_TRAPPED_UPGRADER:
            if has_existing and (equity is not None and equity > 0):
                return base * 0.6
            return 0.0

        if segment_id == COMPETITIVE_BIDDER:
            if (capital is not None and capital > 0
                    and equity is not None and equity > 0
                    and income is not None and income > 0):
                return base * 0.7
            return 0.0

        return 0.0

    @staticmethod
    def _base_confidence(factor_coverage: float) -> float:
        """Compute base confidence from factor coverage.

        Maps 0–1 factor coverage to 0.3–0.95 confidence range.
        Even with full factor coverage, we cap at 0.95 because the
        classification tree uses heuristics, not verified data.
        """
        # Linear interpolation: 0.3 at 0% coverage → 0.95 at 100%
        return 0.3 + factor_coverage * 0.65


# ---------------------------------------------------------------------------
# Distinguishing factor lookup — what question disambiguates two segments
# ---------------------------------------------------------------------------

_DISTINGUISHING_FACTORS: dict[tuple[str, str], str] = {
    # Invest segment pairs
    (CASH_BUYER, APPRECIATION_BETTOR): "capital availability (can you purchase outright?)",
    (CASH_BUYER, LEVERAGED_INVESTOR): "financing plan (all-cash or mortgage?)",
    (CASH_BUYER, EQUITY_LEVERAGING_INVESTOR): "source of funds (cash savings or home equity?)",
    (LEVERAGED_INVESTOR, APPRECIATION_BETTOR): "income and financing capacity",
    (LEVERAGED_INVESTOR, EQUITY_LEVERAGING_INVESTOR): (
        "source of capital (savings + income or existing home equity?)"
    ),
    (APPRECIATION_BETTOR, VALUE_ADD_INVESTOR): (
        "investment strategy (buy-and-hold or renovate/develop?)"
    ),
    (APPRECIATION_BETTOR, EQUITY_LEVERAGING_INVESTOR): (
        "whether you own property with equity to leverage"
    ),
    # Occupy segment pairs
    (STRETCHER, FIRST_TIME_BUYER): "budget tightness relative to income",
    (STRETCHER, DOWN_PAYMENT_CONSTRAINED): "whether the budget or down payment is the bottleneck",
    (FIRST_TIME_BUYER, DOWN_PAYMENT_CONSTRAINED): "down payment amount relative to purchase price",
    (FIRST_TIME_BUYER, COMPETITIVE_BIDDER): "available capital and equity",
    (EQUITY_TRAPPED_UPGRADER, COMPETITIVE_BIDDER): (
        "current homeownership and interest rate lock-in"
    ),
    (NOT_VIABLE, STRETCHER): "income level and savings",
    (NOT_VIABLE, DOWN_PAYMENT_CONSTRAINED): "total savings available for down payment",
}
