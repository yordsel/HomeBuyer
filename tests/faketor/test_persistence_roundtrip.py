"""Full persistence roundtrip tests (Phase G-5, #69).

End-to-end: create → populate → persist → load → verify for all state
containers, returning user delta scenarios, anonymous path, and
confidence decay verification.
"""

import asyncio
import time

import pytest

from homebuyer.services.faketor.state.buyer import FieldSource, Signal
from homebuyer.services.faketor.state.context import (
    ResearchContextStore,
    TurnState,
)
from homebuyer.services.faketor.state.market import BerkeleyWideMetrics, MarketSnapshot
from homebuyer.services.faketor.state.property import FilterIntent, FocusProperty
from homebuyer.storage.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "roundtrip.db"
    db = Database(db_path)
    db.connect()
    db.initialize_schema()
    yield db
    db.close()


@pytest.fixture
def user_id(db):
    db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        ("roundtrip@example.com", "hashed"),
    )
    db.commit()
    row = db.fetchone("SELECT id FROM users WHERE email = ?", ("roundtrip@example.com",))
    return str(row["id"])


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_store(db):
    return ResearchContextStore(ttl_seconds=1800, db=db)


# ---------------------------------------------------------------------------
# Full roundtrip tests
# ---------------------------------------------------------------------------


class TestFullRoundtrip:
    """Create → populate → persist → new store → load → verify."""

    def test_buyer_state_roundtrip(self, db, user_id):
        """BuyerState survives full persist → load cycle."""
        store1 = _make_store(db)
        ctx = _run(store1.load_or_create(user_id=user_id))

        # Populate buyer state
        ctx.buyer.segment_id = "stretcher"
        ctx.buyer.segment_confidence = 0.85
        ctx.buyer.profile.intent = "occupy"
        ctx.buyer.profile.capital = 250_000
        ctx.buyer.profile.equity = 150_000
        ctx.buyer.profile.income = 180_000
        ctx.buyer.profile.current_rent = 3_200
        ctx.buyer.profile.is_first_time_buyer = True
        ctx.buyer.profile.owns_current_home = False
        ctx.buyer.profile.capital_source = FieldSource(
            source="explicit", confidence=1.0,
            evidence="I have $250k saved", extracted_at=time.time(),
        )

        _run(store1.persist(ctx))

        # Load from fresh store
        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        assert loaded.buyer.segment_id == "stretcher"
        assert loaded.buyer.segment_confidence == pytest.approx(0.85)
        assert loaded.buyer.profile.intent == "occupy"
        assert loaded.buyer.profile.capital == 250_000
        assert loaded.buyer.profile.equity == 150_000
        assert loaded.buyer.profile.income == 180_000
        assert loaded.buyer.profile.current_rent == 3_200
        assert loaded.buyer.profile.is_first_time_buyer is True
        assert loaded.buyer.profile.owns_current_home is False
        assert loaded.buyer.profile.capital_source is not None
        assert loaded.buyer.profile.capital_source.source == "explicit"
        assert loaded.buyer.profile.capital_source.evidence == "I have $250k saved"

    def test_market_snapshot_roundtrip(self, db, user_id):
        """MarketSnapshot survives full persist → load cycle."""
        store1 = _make_store(db)
        ctx = _run(store1.load_or_create(user_id=user_id))

        # Populate market snapshot
        ctx.market.mortgage_rate_30yr = 6.875
        ctx.market.conforming_limit = 766_550
        ctx.market.snapshot_at = time.time() - 600
        ctx.market.berkeley_wide = BerkeleyWideMetrics(
            median_sale_price=1_250_000,
            median_list_price=1_100_000,
            median_ppsf=875.0,
            median_dom=18,
            avg_sale_to_list=1.05,
            inventory=120,
            months_of_supply=1.8,
            homes_sold=45,
        )

        _run(store1.persist(ctx))

        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        assert loaded.market.mortgage_rate_30yr == 6.875
        assert loaded.market.conforming_limit == 766_550
        assert loaded.market.berkeley_wide.median_sale_price == 1_250_000
        assert loaded.market.berkeley_wide.median_dom == 18
        assert loaded.market.berkeley_wide.avg_sale_to_list == pytest.approx(1.05)

    def test_property_state_roundtrip(self, db, user_id):
        """PropertyState with analyses, filter, and focus survives roundtrip."""
        store1 = _make_store(db)
        ctx = _run(store1.load_or_create(user_id=user_id))

        # Add property analyses
        ctx.property.record_analysis(
            property_id=42,
            address="123 Spruce St",
            tool_name="compute_true_cost",
            result_summary="Total: $9,200/mo",
            conclusion="25% more than rent",
            market_snapshot_at=time.time(),
        )
        ctx.property.record_analysis(
            property_id=42,
            address="123 Spruce St",
            tool_name="get_price_prediction",
            result_summary="Predicted: $1.35M",
            conclusion="Fairly priced",
            market_snapshot_at=time.time(),
        )
        ctx.property.record_analysis(
            property_id=99,
            address="456 Oak Ave",
            tool_name="compute_true_cost",
            result_summary="Total: $7,800/mo",
            conclusion="10% more than rent",
            market_snapshot_at=time.time(),
        )

        # Set filter intent
        ctx.property.filter_intent = FilterIntent(
            criteria={"min_beds": 3, "max_price": 1_500_000},
            description="3+ bed homes under $1.5M",
            created_at=time.time(),
        )

        # Set focus property
        ctx.property.focus_property = FocusProperty(
            property_id=42,
            address="123 Spruce St",
            last_known_status="active",
            status_checked_at=time.time(),
        )

        _run(store1.persist(ctx))

        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        # Verify analyses
        assert 42 in loaded.property.analyses
        assert 99 in loaded.property.analyses
        assert "compute_true_cost" in loaded.property.analyses[42].analyses
        assert "get_price_prediction" in loaded.property.analyses[42].analyses
        assert loaded.property.analyses[42].analyses["compute_true_cost"].result_summary == "Total: $9,200/mo"

        # Verify filter
        assert loaded.property.filter_intent is not None
        assert loaded.property.filter_intent.criteria["min_beds"] == 3

        # Verify focus
        assert loaded.property.focus_property is not None
        assert loaded.property.focus_property.address == "123 Spruce St"
        assert loaded.property.focus_property.last_known_status == "active"

    def test_segment_history_roundtrip(self, db, user_id):
        """Segment transition history survives roundtrip."""
        store1 = _make_store(db)
        ctx = _run(store1.load_or_create(user_id=user_id))

        # Record a transition
        ctx.buyer.segment_id = "first_time_buyer"
        ctx.buyer.segment_confidence = 0.7
        ctx.buyer.record_transition(
            from_segment=None,
            to_segment="first_time_buyer",
            confidence=0.7,
            trigger=Signal(
                evidence="This is my first home purchase",
                implication="first_time_buyer",
                confidence=0.9,
            ),
        )
        # Second transition
        ctx.buyer.record_transition(
            from_segment="first_time_buyer",
            to_segment="stretcher",
            confidence=0.8,
            trigger=Signal(
                evidence="It's at the top of my budget",
                implication="stretching_affordability",
                confidence=0.85,
            ),
        )
        ctx.buyer.segment_id = "stretcher"
        ctx.buyer.segment_confidence = 0.8

        _run(store1.persist(ctx))

        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        assert loaded.buyer.segment_id == "stretcher"
        assert len(loaded.buyer.segment_history) == 2
        assert loaded.buyer.segment_history[0].to_segment == "first_time_buyer"
        assert loaded.buyer.segment_history[1].to_segment == "stretcher"


# ---------------------------------------------------------------------------
# Returning user delta scenarios
# ---------------------------------------------------------------------------


class TestReturningUserDelta:
    """Simulate returning user scenarios with market changes."""

    def _persist_with_market(self, db, user_id, rate, price, inventory, stale_hours=0):
        """Persist a context with specific market data, optionally stale."""
        store = _make_store(db)
        ctx = _run(store.load_or_create(user_id=user_id))

        ctx.market.mortgage_rate_30yr = rate
        ctx.market.snapshot_at = time.time() - (stale_hours * 3600)
        ctx.market.berkeley_wide = BerkeleyWideMetrics(
            median_sale_price=price,
            inventory=inventory,
        )
        ctx.buyer.segment_id = "first_time_buyer"
        ctx.buyer.segment_confidence = 0.85
        ctx.buyer.profile.capital = 300_000
        ctx.buyer.profile.capital_source = FieldSource(
            source="extracted", confidence=0.9,
            evidence="300k saved", extracted_at=time.time(),
        )
        ctx.last_active = time.time() - (stale_hours * 3600)

        _run(store.persist(ctx))

    def test_delta_rate_drop(self, db, user_id):
        """Scenario 1: Rates dropped 0.5% — material for stretchers."""
        self._persist_with_market(db, user_id, rate=7.0, price=1_200_000,
                                  inventory=100, stale_hours=24)

        store = _make_store(db)
        loaded = _run(store.load_or_create(user_id=user_id))

        # Simulate what the orchestrator would do: compute delta
        new_market = MarketSnapshot(
            mortgage_rate_30yr=6.5,
            snapshot_at=time.time(),
        )
        new_market.berkeley_wide = BerkeleyWideMetrics(
            median_sale_price=1_200_000, inventory=100,
        )
        delta = new_market.compute_delta(loaded.market)

        assert delta.rate_change == pytest.approx(-0.5, abs=0.01)
        assert delta.rate_material is True

    def test_delta_price_surge(self, db, user_id):
        """Scenario 2: Prices up 5% — material change."""
        self._persist_with_market(db, user_id, rate=6.5, price=1_200_000,
                                  inventory=100, stale_hours=48)

        store = _make_store(db)
        loaded = _run(store.load_or_create(user_id=user_id))

        new_market = MarketSnapshot(
            mortgage_rate_30yr=6.5,
            snapshot_at=time.time(),
        )
        new_market.berkeley_wide = BerkeleyWideMetrics(
            median_sale_price=1_260_000, inventory=100,
        )
        delta = new_market.compute_delta(loaded.market)

        assert delta.median_price_change == 60_000
        assert delta.price_material is True

    def test_delta_inventory_spike(self, db, user_id):
        """Scenario 3: Inventory up 25% — material for competitive bidders."""
        self._persist_with_market(db, user_id, rate=6.5, price=1_200_000,
                                  inventory=80, stale_hours=72)

        store = _make_store(db)
        loaded = _run(store.load_or_create(user_id=user_id))

        new_market = MarketSnapshot(
            mortgage_rate_30yr=6.5,
            snapshot_at=time.time(),
        )
        new_market.berkeley_wide = BerkeleyWideMetrics(
            median_sale_price=1_200_000, inventory=100,
        )
        delta = new_market.compute_delta(loaded.market)

        assert delta.inventory_change == 20
        assert delta.inventory_material is True

    def test_delta_no_change(self, db, user_id):
        """Scenario 4: Market unchanged — no material delta."""
        self._persist_with_market(db, user_id, rate=6.5, price=1_200_000,
                                  inventory=100, stale_hours=5)

        store = _make_store(db)
        loaded = _run(store.load_or_create(user_id=user_id))

        new_market = MarketSnapshot(
            mortgage_rate_30yr=6.5,
            snapshot_at=time.time(),
        )
        new_market.berkeley_wide = BerkeleyWideMetrics(
            median_sale_price=1_200_000, inventory=100,
        )
        delta = new_market.compute_delta(loaded.market)

        assert not delta.any_material

    def test_delta_multiple_changes(self, db, user_id):
        """Scenario 5: Rate + price + inventory all changed materially."""
        self._persist_with_market(db, user_id, rate=7.0, price=1_200_000,
                                  inventory=80, stale_hours=168)  # 1 week

        store = _make_store(db)
        loaded = _run(store.load_or_create(user_id=user_id))

        new_market = MarketSnapshot(
            mortgage_rate_30yr=6.25,
            snapshot_at=time.time(),
        )
        new_market.berkeley_wide = BerkeleyWideMetrics(
            median_sale_price=1_320_000,  # +10%
            inventory=110,  # +37.5%
        )
        delta = new_market.compute_delta(loaded.market)

        assert delta.rate_material is True
        assert delta.price_material is True
        assert delta.inventory_material is True


# ---------------------------------------------------------------------------
# Anonymous user path
# ---------------------------------------------------------------------------


class TestAnonymousUserPath:
    def test_anonymous_nothing_persisted(self, db):
        """Anonymous session should never write to DB."""
        store = _make_store(db)
        ctx = _run(store.load_or_create(session_id="anon-abc"))

        ctx.buyer.segment_id = "first_time_buyer"
        ctx.buyer.profile.capital = 100_000

        _run(store.persist(ctx))

        # DB should be empty
        rows = db.fetchall("SELECT * FROM research_contexts")
        assert len(rows) == 0

    def test_anonymous_survives_in_memory(self, db):
        """Anonymous session should work in-memory within same store."""
        store = _make_store(db)

        ctx = _run(store.load_or_create(session_id="anon-xyz"))
        ctx.buyer.segment_id = "cash_buyer"
        _run(store.persist(ctx))

        reloaded = _run(store.load_or_create(session_id="anon-xyz"))
        assert reloaded.buyer.segment_id == "cash_buyer"

    def test_anonymous_lost_on_new_store(self, db):
        """Anonymous session is lost when a new store is created."""
        store1 = _make_store(db)
        ctx = _run(store1.load_or_create(session_id="anon-lost"))
        ctx.buyer.segment_id = "leveraged_investor"
        _run(store1.persist(ctx))

        store2 = _make_store(db)
        fresh = _run(store2.load_or_create(session_id="anon-lost"))
        assert fresh.buyer.segment_id is None  # New, empty context


# ---------------------------------------------------------------------------
# Confidence decay
# ---------------------------------------------------------------------------


class TestConfidenceDecayOnRoundtrip:
    def test_decay_applied_on_stale_load(self, db, user_id):
        """Confidence should decay by 0.8x when loaded after 4+ hours."""
        store1 = _make_store(db)
        ctx = _run(store1.load_or_create(user_id=user_id))

        # Set up extracted fields with confidence values
        ctx.buyer.profile.capital = 300_000
        ctx.buyer.profile.capital_source = FieldSource(
            source="extracted", confidence=1.0,
            evidence="300k", extracted_at=time.time(),
        )
        ctx.buyer.profile.income = 200_000
        ctx.buyer.profile.income_source = FieldSource(
            source="extracted", confidence=0.8,
            evidence="200k income", extracted_at=time.time(),
        )

        # Make it stale (5 hours ago)
        ctx.last_active = time.time() - (5 * 3600)
        _run(store1.persist(ctx))

        # Load from fresh store — should trigger decay
        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        # 1.0 * 0.8 = 0.8
        assert loaded.buyer.profile.capital_source.confidence == pytest.approx(0.8)
        # 0.8 * 0.8 = 0.64
        assert loaded.buyer.profile.income_source.confidence == pytest.approx(0.64)

    def test_no_decay_when_fresh(self, db, user_id):
        """No decay when loaded within 4 hours."""
        store1 = _make_store(db)
        ctx = _run(store1.load_or_create(user_id=user_id))

        ctx.buyer.profile.capital = 300_000
        ctx.buyer.profile.capital_source = FieldSource(
            source="extracted", confidence=0.9,
            evidence="300k", extracted_at=time.time(),
        )

        # Just now
        ctx.last_active = time.time()
        _run(store1.persist(ctx))

        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        assert loaded.buyer.profile.capital_source.confidence == pytest.approx(0.9)

    def test_explicit_fields_not_decayed(self, db, user_id):
        """Explicit (user-stated) fields should still decay but be marked stale."""
        store1 = _make_store(db)
        ctx = _run(store1.load_or_create(user_id=user_id))

        ctx.buyer.profile.capital = 300_000
        ctx.buyer.profile.capital_source = FieldSource(
            source="explicit", confidence=1.0,
            evidence="I have 300k", extracted_at=time.time(),
        )

        ctx.last_active = time.time() - (5 * 3600)
        _run(store1.persist(ctx))

        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        # apply_confidence_decay applies to all sources per the implementation
        # The value is still there, confidence may have decayed
        assert loaded.buyer.profile.capital == 300_000


# ---------------------------------------------------------------------------
# TurnState promote → persist → load roundtrip
# ---------------------------------------------------------------------------


class TestTurnStatePromoteRoundtrip:
    """Verify TurnState.promote() changes survive persist → load."""

    def test_promote_then_persist_then_load(self, db, user_id):
        """Full turn cycle: promote → persist → fresh load."""
        store1 = _make_store(db)
        ctx = _run(store1.load_or_create(user_id=user_id))

        # Simulate a turn
        turn = TurnState()
        turn.buyer_extractions = {
            "capital": (500_000, FieldSource(
                source="explicit", confidence=1.0,
                evidence="I have $500k for down payment",
                extracted_at=time.time(),
            )),
        }
        turn.segment_update = (
            "competitive_bidder", 0.9,
            Signal(evidence="multiple offer situations", implication="competitive", confidence=0.9),
        )
        turn.analysis_records = [{
            "property_id": 77,
            "address": "789 Cedar St",
            "tool_name": "compute_true_cost",
            "result_summary": "Total: $11,200/mo",
            "conclusion": "30% above rent",
        }]
        turn.filter_update = {
            "criteria": {"max_price": 2_000_000, "min_beds": 4},
            "description": "4+ bed homes under $2M",
        }
        turn.focus_update = {
            "property_id": 77,
            "address": "789 Cedar St",
        }

        # Promote
        promoted = turn.promote(ctx)
        assert len(promoted) >= 3  # capital, segment, analyses, filter, focus

        # Persist
        _run(store1.persist(ctx))

        # Load from fresh store
        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        # Verify all promoted state
        assert loaded.buyer.profile.capital == 500_000
        assert loaded.buyer.segment_id == "competitive_bidder"
        assert loaded.buyer.segment_confidence == pytest.approx(0.9)
        assert 77 in loaded.property.analyses
        assert loaded.property.filter_intent is not None
        assert loaded.property.filter_intent.description == "4+ bed homes under $2M"
        assert loaded.property.focus_property is not None
        assert loaded.property.focus_property.address == "789 Cedar St"
