"""Tests for ResearchContext, TurnState, and ResearchContextStore.

Covers:
- ResearchContext serialization roundtrips
- TurnState.promote() — all five promotion paths
- ResearchContextStore lifecycle (load_or_create, persist, eviction)
"""

import time

from homebuyer.services.faketor.state.buyer import FieldSource
from homebuyer.services.faketor.state.context import (
    ResearchContext,
    ResearchContextStore,
    TurnState,
)
from homebuyer.services.faketor.state.market import (
    BerkeleyWideMetrics,
    MarketSnapshot,
)


# ---------------------------------------------------------------------------
# ResearchContext — basics
# ---------------------------------------------------------------------------


class TestResearchContext:
    def test_defaults(self):
        ctx = ResearchContext()
        assert ctx.user_id is None
        assert ctx.session_id is None
        assert ctx.created_at == 0.0

    def test_touch_updates_last_active(self):
        ctx = ResearchContext()
        before = time.time()
        ctx.touch()
        assert ctx.last_active >= before

    def test_serialization_roundtrip_empty(self):
        ctx = ResearchContext(user_id="u1", session_id="s1", created_at=1000.0, last_active=1001.0)
        restored = ResearchContext.from_dict(ctx.to_dict())
        assert restored.user_id == "u1"
        assert restored.session_id == "s1"
        assert restored.created_at == 1000.0

    def test_serialization_roundtrip_with_state(self):
        ctx = ResearchContext(user_id="u1")
        ctx.buyer.profile.intent = "invest"
        ctx.buyer.profile.intent_source = FieldSource(
            source="explicit", confidence=0.9, evidence="test", extracted_at=1.0,
        )
        ctx.buyer.record_transition(from_segment=None, to_segment="cash_buyer", confidence=0.85)
        ctx.market = MarketSnapshot(
            snapshot_at=1000.0,
            mortgage_rate_30yr=6.75,
            berkeley_wide=BerkeleyWideMetrics(median_sale_price=1_300_000),
        )

        d = ctx.to_dict()
        restored = ResearchContext.from_dict(d)
        assert restored.buyer.profile.intent == "invest"
        assert restored.buyer.segment_id == "cash_buyer"
        assert restored.market.mortgage_rate_30yr == 6.75

    def test_serialization_with_market_delta(self):
        from homebuyer.services.faketor.state.market import MarketDelta

        ctx = ResearchContext()
        ctx.market_delta = MarketDelta(rate_change=-0.25, rate_material=True)
        d = ctx.to_dict()
        restored = ResearchContext.from_dict(d)
        assert restored.market_delta is not None
        assert restored.market_delta.rate_change == -0.25
        assert restored.market_delta.rate_material is True


# ---------------------------------------------------------------------------
# TurnState — promote()
# ---------------------------------------------------------------------------


class TestTurnStatePromote:
    def test_promote_buyer_extractions(self):
        ctx = ResearchContext()
        turn = TurnState()
        turn.buyer_extractions = {
            "intent": ("invest", FieldSource(
                source="extracted", confidence=0.8, evidence="rental property", extracted_at=1.0,
            )),
        }
        promoted = turn.promote(ctx)
        assert len(promoted) == 1
        assert "buyer profile" in promoted[0].lower()
        assert ctx.buyer.profile.intent == "invest"

    def test_promote_segment_update(self):
        ctx = ResearchContext()
        ctx.buyer.segment_id = "first_time_buyer"
        ctx.buyer.segment_confidence = 0.6

        turn = TurnState()
        turn.segment_update = ("cash_buyer", 0.9)
        promoted = turn.promote(ctx)
        assert any("Segment" in p for p in promoted)
        assert ctx.buyer.segment_id == "cash_buyer"
        assert ctx.buyer.segment_confidence == 0.9

    def test_promote_segment_no_change_same_id_lower_confidence(self):
        ctx = ResearchContext()
        ctx.buyer.segment_id = "cash_buyer"
        ctx.buyer.segment_confidence = 0.95

        turn = TurnState()
        turn.segment_update = ("cash_buyer", 0.8)  # Same segment, lower confidence
        promoted = turn.promote(ctx)
        # Should NOT promote since same segment and lower confidence
        assert not any("Segment" in p for p in promoted)

    def test_promote_analysis_records(self):
        ctx = ResearchContext()
        ctx.market = MarketSnapshot(snapshot_at=1000.0)

        turn = TurnState()
        turn.analysis_records = [
            {
                "property_id": 42,
                "address": "123 Test St",
                "tool_name": "get_price_prediction",
                "result_summary": "$1.35M",
                "conclusion": "fair price",
            },
        ]
        promoted = turn.promote(ctx)
        assert any("1 analyses" in p for p in promoted)
        assert 42 in ctx.property.analyses

    def test_promote_filter_update(self):
        ctx = ResearchContext()
        turn = TurnState()
        turn.filter_update = {
            "criteria": {"min_beds": 3},
            "description": "3+ beds",
        }
        promoted = turn.promote(ctx)
        assert any("filter" in p.lower() for p in promoted)
        assert ctx.property.filter_intent is not None
        assert ctx.property.filter_intent.criteria["min_beds"] == 3

    def test_promote_focus_update(self):
        ctx = ResearchContext()
        turn = TurnState()
        turn.focus_update = {
            "property_id": 42,
            "address": "123 Test St",
            "property_context": {"beds": 3},
        }
        promoted = turn.promote(ctx)
        assert any("Focus property" in p for p in promoted)
        assert ctx.property.focus_property is not None
        assert ctx.property.focus_property.property_id == 42

    def test_promote_touches_context(self):
        ctx = ResearchContext(last_active=0.0)
        turn = TurnState()
        before = time.time()
        turn.promote(ctx)
        assert ctx.last_active >= before

    def test_promote_empty_turn_no_changes(self):
        ctx = ResearchContext()
        turn = TurnState()
        promoted = turn.promote(ctx)
        assert promoted == []


# ---------------------------------------------------------------------------
# ResearchContextStore — load_or_create
# ---------------------------------------------------------------------------


class TestResearchContextStore:
    def test_create_for_authenticated_user(self):
        store = ResearchContextStore()
        ctx = store.load_or_create(user_id="u1", session_id="s1")
        assert ctx.user_id == "u1"
        assert ctx.session_id == "s1"
        assert ctx.created_at > 0

    def test_reload_returns_same_context(self):
        store = ResearchContextStore()
        ctx1 = store.load_or_create(user_id="u1")
        ctx1.buyer.profile.intent = "invest"
        ctx2 = store.load_or_create(user_id="u1")
        assert ctx2.buyer.profile.intent == "invest"

    def test_create_anonymous_session(self):
        store = ResearchContextStore()
        ctx = store.load_or_create(session_id="anon-123")
        assert ctx.session_id == "anon-123"
        assert ctx.user_id is None

    def test_reload_anonymous_session(self):
        store = ResearchContextStore()
        ctx1 = store.load_or_create(session_id="anon-123")
        ctx1.buyer.profile.capital = 100_000
        ctx2 = store.load_or_create(session_id="anon-123")
        assert ctx2.buyer.profile.capital == 100_000

    def test_ephemeral_context_when_no_ids(self):
        store = ResearchContextStore()
        ctx = store.load_or_create()
        assert ctx.user_id is None
        assert ctx.session_id is None
        assert ctx.created_at > 0

    def test_persist_authenticated_user(self):
        store = ResearchContextStore()
        ctx = ResearchContext(user_id="u1")
        store.persist(ctx)
        loaded = store.load_or_create(user_id="u1")
        assert loaded is ctx

    def test_persist_anonymous_session(self):
        store = ResearchContextStore()
        ctx = ResearchContext(session_id="s1", last_active=time.time())
        store.persist(ctx)
        loaded = store.load_or_create(session_id="s1")
        assert loaded is ctx


# ---------------------------------------------------------------------------
# ResearchContextStore — confidence decay on stale load
# ---------------------------------------------------------------------------


class TestResearchContextStoreDecay:
    def test_confidence_decay_on_stale_load(self):
        store = ResearchContextStore()
        ctx = store.load_or_create(user_id="u1")
        ctx.buyer.profile.intent = "invest"
        ctx.buyer.profile.intent_source = FieldSource(
            source="explicit", confidence=1.0, evidence="test", extracted_at=1.0,
        )
        # Make it stale (>4 hours ago)
        ctx.last_active = time.time() - 5 * 3600

        reloaded = store.load_or_create(user_id="u1")
        assert reloaded.buyer.profile.intent_source.confidence < 1.0
        assert reloaded.buyer.profile.intent_source.stale is True

    def test_no_decay_when_recent(self):
        store = ResearchContextStore()
        ctx = store.load_or_create(user_id="u1")
        ctx.buyer.profile.intent = "occupy"
        ctx.buyer.profile.intent_source = FieldSource(
            source="explicit", confidence=1.0, evidence="test", extracted_at=1.0,
        )
        ctx.last_active = time.time() - 1 * 3600  # 1 hour ago (within 4h)

        reloaded = store.load_or_create(user_id="u1")
        assert reloaded.buyer.profile.intent_source.confidence == 1.0
        assert reloaded.buyer.profile.intent_source.stale is False


# ---------------------------------------------------------------------------
# ResearchContextStore — eviction
# ---------------------------------------------------------------------------


class TestResearchContextStoreEviction:
    def test_expired_sessions_evicted(self):
        store = ResearchContextStore(ttl_seconds=1)  # 1 second TTL
        ctx = store.load_or_create(session_id="old-session")
        ctx.last_active = time.time() - 10  # 10 seconds ago, past TTL

        # Loading a different session triggers eviction
        store.load_or_create(session_id="new-session")

        # Old session should be gone — creates new context
        reloaded = store.load_or_create(session_id="old-session")
        assert reloaded.buyer.profile.intent is None  # Fresh context

    def test_authenticated_users_not_evicted(self):
        store = ResearchContextStore(ttl_seconds=1)
        ctx = store.load_or_create(user_id="u1")
        ctx.buyer.profile.intent = "invest"
        ctx.last_active = time.time() - 100  # Well past TTL

        # Eviction only affects anonymous sessions
        store.load_or_create(session_id="trigger-eviction")
        reloaded = store.load_or_create(user_id="u1")
        assert reloaded.buyer.profile.intent == "invest"
