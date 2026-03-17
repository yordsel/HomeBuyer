"""Tests for the Faketor persistence schema (Phase G-1, #65).

Verifies that the three new tables (research_contexts, buyer_profiles,
property_analyses) are created during schema initialization, have the
correct columns, and support basic CRUD operations.
"""

import json

import pytest

from homebuyer.storage.database import Database


@pytest.fixture
def db(tmp_path):
    """Create a fresh test database with schema initialized."""
    db_path = tmp_path / "test_persistence.db"
    db = Database(db_path)
    db.connect()
    db.initialize_schema()
    yield db
    db.close()


def _create_test_user(db: Database) -> int:
    """Insert a minimal user and return the user_id."""
    db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        ("test@example.com", "hashed_pw"),
    )
    db.commit()
    row = db.fetchone("SELECT id FROM users WHERE email = ?", ("test@example.com",))
    return row["id"]


# ---------------------------------------------------------------------------
# Table existence tests
# ---------------------------------------------------------------------------


class TestSchemaTablesExist:
    def test_research_contexts_table_exists(self, db):
        assert db.table_exists("research_contexts")

    def test_buyer_profiles_table_exists(self, db):
        assert db.table_exists("buyer_profiles")

    def test_property_analyses_table_exists(self, db):
        assert db.table_exists("property_analyses")

    def test_schema_version_is_5(self, db):
        row = db.fetchone(
            "SELECT MAX(version) as v FROM schema_version"
        )
        assert row["v"] >= 5


# ---------------------------------------------------------------------------
# research_contexts table tests
# ---------------------------------------------------------------------------


class TestResearchContextsTable:
    def test_columns(self, db):
        cols = db.get_table_columns("research_contexts")
        expected = {
            "user_id", "session_id", "created_at", "last_active",
            "buyer_state", "market_snapshot", "property_state",
        }
        assert expected.issubset(cols)

    def test_insert_and_read(self, db):
        user_id = _create_test_user(db)
        buyer = json.dumps({"segment_id": "first_time_buyer"})
        market = json.dumps({"mortgage_rate_30yr": 6.5})
        prop = json.dumps({"filter_intent": None})

        db.execute(
            "INSERT INTO research_contexts "
            "(user_id, session_id, buyer_state, market_snapshot, property_state) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, "sess-123", buyer, market, prop),
        )
        db.commit()

        row = db.fetchone(
            "SELECT * FROM research_contexts WHERE user_id = ?", (user_id,)
        )
        assert row is not None
        assert row["session_id"] == "sess-123"
        assert json.loads(row["buyer_state"])["segment_id"] == "first_time_buyer"
        assert json.loads(row["market_snapshot"])["mortgage_rate_30yr"] == 6.5

    def test_user_id_is_primary_key(self, db):
        """Only one research context per user."""
        user_id = _create_test_user(db)
        db.execute(
            "INSERT INTO research_contexts (user_id, buyer_state) VALUES (?, ?)",
            (user_id, "{}"),
        )
        db.commit()

        with pytest.raises(Exception):
            db.execute(
                "INSERT INTO research_contexts (user_id, buyer_state) VALUES (?, ?)",
                (user_id, "{}"),
            )

    def test_upsert_via_replace(self, db):
        """INSERT OR REPLACE should update existing row."""
        user_id = _create_test_user(db)
        db.execute(
            "INSERT INTO research_contexts (user_id, buyer_state) VALUES (?, ?)",
            (user_id, '{"v": 1}'),
        )
        db.commit()

        db.execute(
            "INSERT OR REPLACE INTO research_contexts "
            "(user_id, buyer_state, market_snapshot, property_state) "
            "VALUES (?, ?, ?, ?)",
            (user_id, '{"v": 2}', '{}', '{}'),
        )
        db.commit()

        row = db.fetchone(
            "SELECT buyer_state FROM research_contexts WHERE user_id = ?",
            (user_id,),
        )
        assert json.loads(row["buyer_state"])["v"] == 2

    def test_cascade_delete(self, db):
        """Deleting a user should delete their research context."""
        user_id = _create_test_user(db)
        db.execute(
            "INSERT INTO research_contexts (user_id, buyer_state) VALUES (?, ?)",
            (user_id, "{}"),
        )
        db.commit()

        # Enable FK enforcement for cascade test
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()

        row = db.fetchone(
            "SELECT * FROM research_contexts WHERE user_id = ?", (user_id,)
        )
        assert row is None


# ---------------------------------------------------------------------------
# buyer_profiles table tests
# ---------------------------------------------------------------------------


class TestBuyerProfilesTable:
    def test_columns(self, db):
        cols = db.get_table_columns("buyer_profiles")
        expected = {
            "id", "user_id", "segment_id", "segment_confidence",
            "intent", "capital", "equity", "income", "current_rent",
            "profile_json", "updated_at",
        }
        assert expected.issubset(cols)

    def test_insert_and_read(self, db):
        user_id = _create_test_user(db)
        profile = json.dumps({"owns_current_home": True})

        db.execute(
            "INSERT INTO buyer_profiles "
            "(user_id, segment_id, segment_confidence, intent, capital, "
            "income, profile_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, "equity_trapped", 0.85, "occupy", 200_000, 180_000, profile),
        )
        db.commit()

        row = db.fetchone(
            "SELECT * FROM buyer_profiles WHERE user_id = ?", (user_id,)
        )
        assert row["segment_id"] == "equity_trapped"
        assert row["segment_confidence"] == pytest.approx(0.85)
        assert row["intent"] == "occupy"
        assert row["capital"] == 200_000

    def test_unique_user_id(self, db):
        """Each user has at most one buyer profile."""
        user_id = _create_test_user(db)
        db.execute(
            "INSERT INTO buyer_profiles (user_id, profile_json) VALUES (?, ?)",
            (user_id, "{}"),
        )
        db.commit()

        with pytest.raises(Exception):
            db.execute(
                "INSERT INTO buyer_profiles (user_id, profile_json) VALUES (?, ?)",
                (user_id, "{}"),
            )

    def test_nullable_financial_fields(self, db):
        """Financial fields should accept NULL (unknown)."""
        user_id = _create_test_user(db)
        db.execute(
            "INSERT INTO buyer_profiles "
            "(user_id, capital, equity, income, current_rent, profile_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, None, None, None, None, "{}"),
        )
        db.commit()

        row = db.fetchone(
            "SELECT * FROM buyer_profiles WHERE user_id = ?", (user_id,)
        )
        assert row["capital"] is None
        assert row["equity"] is None


# ---------------------------------------------------------------------------
# property_analyses table tests
# ---------------------------------------------------------------------------


class TestPropertyAnalysesTable:
    def test_columns(self, db):
        cols = db.get_table_columns("property_analyses")
        expected = {
            "id", "user_id", "property_id", "address", "tool_name",
            "result_summary", "conclusion", "computed_at", "market_snapshot_at",
        }
        assert expected.issubset(cols)

    def test_insert_and_read(self, db):
        user_id = _create_test_user(db)
        db.execute(
            "INSERT INTO property_analyses "
            "(user_id, property_id, address, tool_name, result_summary, "
            "conclusion, market_snapshot_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, 42, "123 Main St", "compute_true_cost",
             "Total: $8,500/mo", "15% more than rent", 1710000000.0),
        )
        db.commit()

        row = db.fetchone(
            "SELECT * FROM property_analyses WHERE user_id = ? AND property_id = ?",
            (user_id, 42),
        )
        assert row["tool_name"] == "compute_true_cost"
        assert row["result_summary"] == "Total: $8,500/mo"
        assert row["market_snapshot_at"] == pytest.approx(1710000000.0)

    def test_unique_user_property_tool(self, db):
        """Same user+property+tool should conflict (for upsert semantics)."""
        user_id = _create_test_user(db)
        db.execute(
            "INSERT INTO property_analyses "
            "(user_id, property_id, address, tool_name) "
            "VALUES (?, ?, ?, ?)",
            (user_id, 42, "123 Main St", "compute_true_cost"),
        )
        db.commit()

        with pytest.raises(Exception):
            db.execute(
                "INSERT INTO property_analyses "
                "(user_id, property_id, address, tool_name) "
                "VALUES (?, ?, ?, ?)",
                (user_id, 42, "123 Main St", "compute_true_cost"),
            )

    def test_multiple_tools_same_property(self, db):
        """Different tools for the same property should be allowed."""
        user_id = _create_test_user(db)
        for tool in ["compute_true_cost", "rent_vs_buy", "get_price_prediction"]:
            db.execute(
                "INSERT INTO property_analyses "
                "(user_id, property_id, address, tool_name) "
                "VALUES (?, ?, ?, ?)",
                (user_id, 42, "123 Main St", tool),
            )
        db.commit()

        rows = db.fetchall(
            "SELECT tool_name FROM property_analyses "
            "WHERE user_id = ? AND property_id = ?",
            (user_id, 42),
        )
        assert len(rows) == 3

    def test_multiple_properties_same_user(self, db):
        """Different properties for the same user should be allowed."""
        user_id = _create_test_user(db)
        for pid, addr in [(42, "123 Main St"), (99, "456 Oak Ave")]:
            db.execute(
                "INSERT INTO property_analyses "
                "(user_id, property_id, address, tool_name) "
                "VALUES (?, ?, ?, ?)",
                (user_id, pid, addr, "compute_true_cost"),
            )
        db.commit()

        rows = db.fetchall(
            "SELECT * FROM property_analyses WHERE user_id = ?",
            (user_id,),
        )
        assert len(rows) == 2

    def test_cascade_delete(self, db):
        """Deleting a user should delete their property analyses."""
        user_id = _create_test_user(db)
        db.execute(
            "INSERT INTO property_analyses "
            "(user_id, property_id, address, tool_name) "
            "VALUES (?, ?, ?, ?)",
            (user_id, 42, "123 Main St", "compute_true_cost"),
        )
        db.commit()

        db.execute("PRAGMA foreign_keys = ON")
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()

        rows = db.fetchall(
            "SELECT * FROM property_analyses WHERE user_id = ?",
            (user_id,),
        )
        assert len(rows) == 0
