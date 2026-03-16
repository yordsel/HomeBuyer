"""Tests for BuyerState, BuyerProfile, FieldSource, Signal, SegmentTransition.

Covers:
- BuyerProfile extraction with confidence hierarchy
- Confidence decay for returning users
- known_factor_count
- Serialization roundtrips
- BuyerState segment transitions
"""

import time

from homebuyer.services.faketor.state.buyer import (
    BuyerProfile,
    BuyerState,
    FieldSource,
    SegmentTransition,
    Signal,
)


# ---------------------------------------------------------------------------
# FieldSource
# ---------------------------------------------------------------------------


class TestFieldSource:
    def test_to_dict_roundtrip(self):
        fs = FieldSource(
            source="explicit",
            confidence=0.9,
            evidence="I have $200k saved",
            extracted_at=1000.0,
            stale=False,
        )
        d = fs.to_dict()
        restored = FieldSource.from_dict(d)
        assert restored.source == "explicit"
        assert restored.confidence == 0.9
        assert restored.evidence == "I have $200k saved"
        assert restored.extracted_at == 1000.0
        assert restored.stale is False

    def test_stale_defaults_false(self):
        d = {"source": "inferred", "confidence": 0.5, "evidence": "x", "extracted_at": 1.0}
        fs = FieldSource.from_dict(d)
        assert fs.stale is False


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------


class TestSignal:
    def test_creation(self):
        s = Signal(evidence="I want to buy a rental", implication="invest_intent", confidence=0.8)
        assert s.evidence == "I want to buy a rental"
        assert s.confidence == 0.8


# ---------------------------------------------------------------------------
# BuyerProfile — extraction
# ---------------------------------------------------------------------------


class TestBuyerProfileExtraction:
    def _make_source(self, confidence: float = 0.8, source: str = "extracted") -> FieldSource:
        return FieldSource(
            source=source,
            confidence=confidence,
            evidence="test",
            extracted_at=time.time(),
        )

    def test_apply_extraction_sets_new_field(self):
        profile = BuyerProfile()
        updated = profile.apply_extraction({
            "intent": ("invest", self._make_source(0.9)),
        })
        assert "intent" in updated
        assert profile.intent == "invest"
        assert profile.intent_source.confidence == 0.9

    def test_apply_extraction_respects_confidence_hierarchy(self):
        profile = BuyerProfile()
        # Set initial with high confidence
        profile.apply_extraction({
            "capital": (200_000, self._make_source(0.95)),
        })
        # Try to overwrite with lower confidence — should NOT update
        updated = profile.apply_extraction({
            "capital": (300_000, self._make_source(0.5)),
        })
        assert "capital" not in updated
        assert profile.capital == 200_000

    def test_apply_extraction_upgrades_on_higher_confidence(self):
        profile = BuyerProfile()
        profile.apply_extraction({
            "income": (120_000, self._make_source(0.6)),
        })
        updated = profile.apply_extraction({
            "income": (150_000, self._make_source(0.95, source="explicit")),
        })
        assert "income" in updated
        assert profile.income == 150_000
        assert profile.income_source.source == "explicit"

    def test_apply_extraction_ignores_unknown_fields(self):
        profile = BuyerProfile()
        updated = profile.apply_extraction({
            "nonexistent_field": ("value", self._make_source()),
        })
        assert updated == []

    def test_apply_extraction_multiple_fields(self):
        profile = BuyerProfile()
        updated = profile.apply_extraction({
            "intent": ("occupy", self._make_source(0.9)),
            "capital": (500_000, self._make_source(0.8)),
            "is_first_time_buyer": (True, self._make_source(0.7)),
        })
        assert len(updated) == 3
        assert profile.intent == "occupy"
        assert profile.capital == 500_000
        assert profile.is_first_time_buyer is True


# ---------------------------------------------------------------------------
# BuyerProfile — confidence decay
# ---------------------------------------------------------------------------


class TestBuyerProfileDecay:
    def test_decay_multiplies_confidence(self):
        profile = BuyerProfile()
        fs = FieldSource(source="extracted", confidence=1.0, evidence="test", extracted_at=1.0)
        profile.intent = "invest"
        profile.intent_source = fs

        profile.apply_confidence_decay(factor=0.8)
        assert profile.intent_source.confidence == 0.8
        assert profile.intent_source.stale is True

    def test_decay_skips_none_sources(self):
        profile = BuyerProfile()
        # capital_source is None — should not raise
        profile.apply_confidence_decay()

    def test_decay_applies_to_all_sources(self):
        profile = BuyerProfile()
        for attr in ("intent", "capital", "equity", "income"):
            fs = FieldSource(source="extracted", confidence=1.0, evidence="x", extracted_at=1.0)
            setattr(profile, attr, "test_value" if attr == "intent" else 100)
            setattr(profile, f"{attr}_source", fs)

        profile.apply_confidence_decay(factor=0.5)
        for attr in ("intent", "capital", "equity", "income"):
            src = getattr(profile, f"{attr}_source")
            assert src.confidence == 0.5
            assert src.stale is True


# ---------------------------------------------------------------------------
# BuyerProfile — known_factor_count
# ---------------------------------------------------------------------------


class TestBuyerProfileFactorCount:
    def test_empty_profile_returns_zero(self):
        assert BuyerProfile().known_factor_count() == 0

    def test_partial_profile(self):
        p = BuyerProfile(intent="occupy", capital=100_000)
        assert p.known_factor_count() == 2

    def test_full_core_factors(self):
        p = BuyerProfile(intent="invest", capital=500_000, equity=200_000, income=150_000)
        assert p.known_factor_count() == 4


# ---------------------------------------------------------------------------
# BuyerProfile — serialization
# ---------------------------------------------------------------------------


class TestBuyerProfileSerialization:
    def test_empty_roundtrip(self):
        p = BuyerProfile()
        restored = BuyerProfile.from_dict(p.to_dict())
        assert restored.intent is None
        assert restored.capital is None
        assert restored.signals == []

    def test_populated_roundtrip(self):
        p = BuyerProfile(
            intent="invest",
            intent_source=FieldSource(
                source="explicit", confidence=0.95, evidence="I want rentals",
                extracted_at=1000.0,
            ),
            capital=500_000,
            capital_source=FieldSource(
                source="extracted", confidence=0.8, evidence="about 500k",
                extracted_at=1001.0,
            ),
            signals=[
                Signal(evidence="I want rentals", implication="invest_intent", confidence=0.95),
            ],
        )
        d = p.to_dict()
        restored = BuyerProfile.from_dict(d)
        assert restored.intent == "invest"
        assert restored.intent_source.confidence == 0.95
        assert restored.capital == 500_000
        assert len(restored.signals) == 1
        assert restored.signals[0].evidence == "I want rentals"


# ---------------------------------------------------------------------------
# SegmentTransition
# ---------------------------------------------------------------------------


class TestSegmentTransition:
    def test_to_dict_roundtrip_with_trigger(self):
        trigger = Signal(evidence="I plan to rent it out", implication="invest", confidence=0.9)
        t = SegmentTransition(
            from_segment="first_time_buyer",
            to_segment="leveraged_investor",
            confidence=0.85,
            trigger=trigger,
            triggered_at=2000.0,
        )
        d = t.to_dict()
        restored = SegmentTransition.from_dict(d)
        assert restored.from_segment == "first_time_buyer"
        assert restored.to_segment == "leveraged_investor"
        assert restored.confidence == 0.85
        assert restored.trigger.evidence == "I plan to rent it out"

    def test_to_dict_roundtrip_without_trigger(self):
        t = SegmentTransition(
            from_segment=None,
            to_segment="stretcher",
            confidence=0.7,
            trigger=None,
            triggered_at=1000.0,
        )
        d = t.to_dict()
        restored = SegmentTransition.from_dict(d)
        assert restored.from_segment is None
        assert restored.trigger is None


# ---------------------------------------------------------------------------
# BuyerState
# ---------------------------------------------------------------------------


class TestBuyerState:
    def test_record_transition_updates_segment(self):
        bs = BuyerState()
        bs.record_transition(from_segment=None, to_segment="first_time_buyer", confidence=0.8)
        assert bs.segment_id == "first_time_buyer"
        assert bs.segment_confidence == 0.8
        assert len(bs.segment_history) == 1

    def test_record_transition_appends_history(self):
        bs = BuyerState()
        bs.record_transition(from_segment=None, to_segment="stretcher", confidence=0.6)
        bs.record_transition(from_segment="stretcher", to_segment="first_time_buyer", confidence=0.85)
        assert bs.segment_id == "first_time_buyer"
        assert len(bs.segment_history) == 2
        assert bs.segment_history[0].to_segment == "stretcher"
        assert bs.segment_history[1].from_segment == "stretcher"

    def test_serialization_roundtrip(self):
        bs = BuyerState()
        bs.profile.intent = "occupy"
        bs.profile.intent_source = FieldSource(
            source="explicit", confidence=0.9, evidence="test", extracted_at=1.0
        )
        bs.record_transition(from_segment=None, to_segment="first_time_buyer", confidence=0.8)

        d = bs.to_dict()
        restored = BuyerState.from_dict(d)
        assert restored.profile.intent == "occupy"
        assert restored.segment_id == "first_time_buyer"
        assert len(restored.segment_history) == 1

    def test_empty_roundtrip(self):
        bs = BuyerState()
        restored = BuyerState.from_dict(bs.to_dict())
        assert restored.segment_id is None
        assert restored.segment_confidence == 0.0
        assert restored.segment_history == []
