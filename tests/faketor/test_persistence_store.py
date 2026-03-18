"""Tests for ResearchContextStore DB persistence (Phase G-2/G-3, #66/#67).

Verifies persist() writes to DB, load_or_create() reads from DB on
cache miss, confidence decay on stale load, and anonymous-user-only
in-memory behavior.
"""

import asyncio
import json
import time

import pytest

from homebuyer.services.faketor.state.buyer import FieldSource
from homebuyer.services.faketor.state.context import (
    ResearchContext,
    ResearchContextStore,
    _epoch_to_iso,
    _iso_to_epoch,
)
from homebuyer.storage.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    """Create a fresh test database with schema initialized."""
    db_path = tmp_path / "test_persist.db"
    db = Database(db_path)
    db.connect()
    db.initialize_schema()
    yield db
    db.close()


@pytest.fixture
def user_id(db):
    """Create a test user and return their ID as a string."""
    db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        ("persist@example.com", "hashed"),
    )
    db.commit()
    row = db.fetchone("SELECT id FROM users WHERE email = ?", ("persist@example.com",))
    return str(row["id"])


def _run(coro):
    """Run an async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_store(db):
    """Create a ResearchContextStore with DB backing."""
    return ResearchContextStore(ttl_seconds=1800, db=db)


def _make_populated_context(user_id: str) -> ResearchContext:
    """Create a context with non-trivial state for roundtrip testing."""
    ctx = ResearchContext(
        user_id=user_id,
        session_id="sess-roundtrip",
        created_at=time.time() - 3600,
        last_active=time.time(),
    )
    # Set buyer state
    ctx.buyer.segment_id = "first_time_buyer"
    ctx.buyer.segment_confidence = 0.9
    ctx.buyer.profile.capital = 300_000
    ctx.buyer.profile.income = 200_000
    ctx.buyer.profile.intent = "occupy"
    ctx.buyer.profile.capital_source = FieldSource(
        source="explicit", confidence=1.0, evidence="I have 300k saved",
        extracted_at=time.time(),
    )

    # Set market snapshot
    ctx.market.mortgage_rate_30yr = 6.75
    ctx.market.snapshot_at = time.time() - 1800

    return ctx


# ---------------------------------------------------------------------------
# Timestamp helper tests
# ---------------------------------------------------------------------------


class TestTimestampHelpers:
    def test_epoch_to_iso_roundtrip(self):
        epoch = 1710000000.0  # 2024-03-09 16:00:00 UTC
        iso = _epoch_to_iso(epoch)
        # Now uses isoformat() for robust round-trip fidelity
        assert iso == "2024-03-09T16:00:00+00:00"
        back = _iso_to_epoch(iso)
        assert back == pytest.approx(epoch)

    def test_iso_to_epoch_legacy_format(self):
        """Bare timestamps (legacy DB rows) still parse correctly."""
        epoch = _iso_to_epoch("2024-03-09 16:00:00")
        assert epoch == pytest.approx(1710000000.0)

    def test_iso_to_epoch_with_timezone(self):
        """ISO strings with timezone offsets parse correctly."""
        epoch = _iso_to_epoch("2024-03-09T16:00:00+00:00")
        assert epoch == pytest.approx(1710000000.0)

    def test_iso_to_epoch_invalid(self):
        assert _iso_to_epoch("not-a-date") == 0.0
        assert _iso_to_epoch("") == 0.0


# ---------------------------------------------------------------------------
# persist() tests (G-2)
# ---------------------------------------------------------------------------


class TestPersistToDb:
    def test_persist_writes_to_db(self, db, user_id):
        """persist() should write context to research_contexts table."""
        store = _make_store(db)
        ctx = _make_populated_context(user_id)

        _run(store.persist(ctx))

        row = db.fetchone(
            "SELECT * FROM research_contexts WHERE user_id = ?",
            (int(user_id),),
        )
        assert row is not None
        buyer = json.loads(row["buyer_state"])
        assert buyer["segment_id"] == "first_time_buyer"
        assert buyer["segment_confidence"] == 0.9

    def test_persist_updates_existing(self, db, user_id):
        """persist() should upsert (overwrite) on subsequent calls."""
        store = _make_store(db)
        ctx = _make_populated_context(user_id)

        _run(store.persist(ctx))

        # Update and persist again
        ctx.buyer.segment_id = "stretcher"
        ctx.buyer.segment_confidence = 0.75
        _run(store.persist(ctx))

        row = db.fetchone(
            "SELECT buyer_state FROM research_contexts WHERE user_id = ?",
            (int(user_id),),
        )
        buyer = json.loads(row["buyer_state"])
        assert buyer["segment_id"] == "stretcher"
        assert buyer["segment_confidence"] == 0.75

    def test_persist_stores_market_snapshot(self, db, user_id):
        """Market snapshot should be serialized to DB."""
        store = _make_store(db)
        ctx = _make_populated_context(user_id)

        _run(store.persist(ctx))

        row = db.fetchone(
            "SELECT market_snapshot FROM research_contexts WHERE user_id = ?",
            (int(user_id),),
        )
        market = json.loads(row["market_snapshot"])
        assert market["mortgage_rate_30yr"] == 6.75

    def test_persist_stores_property_state(self, db, user_id):
        """Property state should be serialized to DB."""
        store = _make_store(db)
        ctx = _make_populated_context(user_id)

        # Add a property analysis
        ctx.property.record_analysis(
            property_id=42,
            address="123 Main St",
            tool_name="compute_true_cost",
            result_summary="Total: $8,500/mo",
            conclusion="15% more than rent",
            market_snapshot_at=time.time(),
        )

        _run(store.persist(ctx))

        row = db.fetchone(
            "SELECT property_state FROM research_contexts WHERE user_id = ?",
            (int(user_id),),
        )
        prop = json.loads(row["property_state"])
        assert "42" in prop["analyses"] or 42 in prop.get("analyses", {})

    def test_persist_anonymous_not_in_db(self, db):
        """Anonymous users should NOT be written to DB."""
        store = _make_store(db)
        ctx = ResearchContext(session_id="anon-sess", created_at=time.time())
        ctx.buyer.segment_id = "first_time_buyer"

        _run(store.persist(ctx))

        rows = db.fetchall("SELECT * FROM research_contexts")
        assert len(rows) == 0

    def test_persist_no_db_graceful(self, user_id):
        """Without a DB, persist should still work (in-memory only)."""
        store = ResearchContextStore(ttl_seconds=1800, db=None)
        ctx = _make_populated_context(user_id)
        _run(store.persist(ctx))  # Should not raise

    def test_persist_also_updates_cache(self, db, user_id):
        """persist() should update in-memory cache too."""
        store = _make_store(db)
        ctx = _make_populated_context(user_id)
        _run(store.persist(ctx))

        # Should be loadable from cache (no DB query needed)
        loaded = _run(store.load_or_create(user_id=user_id))
        assert loaded.buyer.segment_id == "first_time_buyer"


# ---------------------------------------------------------------------------
# load_or_create() tests (G-3)
# ---------------------------------------------------------------------------


class TestLoadOrCreateFromDb:
    def test_load_from_db_on_cache_miss(self, db, user_id):
        """load_or_create() should load from DB when not in cache."""
        # Persist with one store instance
        store1 = _make_store(db)
        ctx = _make_populated_context(user_id)
        _run(store1.persist(ctx))

        # Create a new store (empty cache) — should load from DB
        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        assert loaded.user_id == user_id
        assert loaded.buyer.segment_id == "first_time_buyer"
        assert loaded.buyer.segment_confidence == 0.9
        assert loaded.buyer.profile.capital == 300_000

    def test_load_from_cache_preferred(self, db, user_id):
        """Cache hit should be returned without DB query."""
        store = _make_store(db)
        ctx = _make_populated_context(user_id)
        _run(store.persist(ctx))

        # Modify the DB directly to prove cache is being used
        db.execute(
            "UPDATE research_contexts SET buyer_state = ? WHERE user_id = ?",
            ('{"segment_id": "modified_in_db"}', int(user_id)),
        )
        db.commit()

        loaded = _run(store.load_or_create(user_id=user_id))
        # Should get cached version, not the DB-modified one
        assert loaded.buyer.segment_id == "first_time_buyer"

    def test_load_new_user_creates_empty(self, db, user_id):
        """New user with no saved context gets an empty context."""
        store = _make_store(db)
        loaded = _run(store.load_or_create(user_id=user_id))

        assert loaded.user_id == user_id
        assert loaded.buyer.segment_id is None
        assert loaded.buyer.profile.capital is None

    def test_load_anonymous_never_hits_db(self, db):
        """Anonymous users should never query the DB."""
        store = _make_store(db)
        loaded = _run(store.load_or_create(session_id="anon-123"))

        assert loaded.session_id == "anon-123"
        assert loaded.user_id is None

    def test_confidence_decay_on_stale_load(self, db, user_id):
        """Loading a stale context (>4h) should apply confidence decay."""
        store1 = _make_store(db)
        ctx = _make_populated_context(user_id)

        # Set last_active to 5 hours ago
        ctx.last_active = time.time() - (5 * 3600)
        ctx.buyer.profile.capital_source = FieldSource(
            source="extracted", confidence=0.9, evidence="I have 300k",
            extracted_at=time.time(),
        )
        _run(store1.persist(ctx))

        # Load with a fresh store (cache miss → DB load)
        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        # Confidence should have decayed (0.9 * 0.8 = 0.72)
        assert loaded.buyer.profile.capital_source is not None
        assert loaded.buyer.profile.capital_source.confidence < 0.9

    def test_no_decay_when_fresh(self, db, user_id):
        """Loading a fresh context should NOT apply decay."""
        store1 = _make_store(db)
        ctx = _make_populated_context(user_id)
        ctx.last_active = time.time()  # Just now
        ctx.buyer.profile.capital_source = FieldSource(
            source="extracted", confidence=0.9, evidence="I have 300k",
            extracted_at=time.time(),
        )
        _run(store1.persist(ctx))

        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))

        # Should not have decayed
        assert loaded.buyer.profile.capital_source.confidence == pytest.approx(0.9)

    def test_roundtrip_market_snapshot(self, db, user_id):
        """Market snapshot should survive persist → load roundtrip."""
        store1 = _make_store(db)
        ctx = _make_populated_context(user_id)
        _run(store1.persist(ctx))

        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))
        assert loaded.market.mortgage_rate_30yr == 6.75

    def test_roundtrip_property_analyses(self, db, user_id):
        """Property analyses should survive persist → load roundtrip."""
        store1 = _make_store(db)
        ctx = _make_populated_context(user_id)
        ctx.property.record_analysis(
            property_id=42,
            address="123 Main St",
            tool_name="compute_true_cost",
            result_summary="Total: $8,500/mo",
            conclusion="15% more than rent",
            market_snapshot_at=time.time(),
        )
        _run(store1.persist(ctx))

        store2 = _make_store(db)
        loaded = _run(store2.load_or_create(user_id=user_id))
        assert 42 in loaded.property.analyses
        assert "compute_true_cost" in loaded.property.analyses[42].analyses


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestPersistenceEdgeCases:
    def test_ephemeral_context_no_persist(self, db):
        """Context with no user_id or session_id should not persist."""
        store = _make_store(db)
        ctx = ResearchContext(created_at=time.time())
        _run(store.persist(ctx))  # Should be a no-op

        rows = db.fetchall("SELECT * FROM research_contexts")
        assert len(rows) == 0

    def test_invalid_user_id_no_crash(self, db):
        """Non-integer user_id should not crash persist."""
        store = _make_store(db)
        ctx = ResearchContext(user_id="not-an-int", created_at=time.time())
        _run(store.persist(ctx))  # Should log warning, not crash

    def test_eviction_still_works(self, db):
        """TTL eviction of anonymous sessions should still function."""
        store = ResearchContextStore(ttl_seconds=1, db=db)
        ctx = ResearchContext(session_id="expire-me", created_at=time.time() - 10)
        ctx.last_active = time.time() - 10
        _run(store.persist(ctx))

        # Force eviction via load_or_create
        time.sleep(0.01)  # Ensure we're past TTL
        new_ctx = _run(store.load_or_create(session_id="new-session"))
        assert new_ctx.session_id == "new-session"

        # The expired session should have been evicted
        reloaded = _run(store.load_or_create(session_id="expire-me"))
        # Should be a fresh context (the old one was evicted)
        assert reloaded.buyer.segment_id is None
