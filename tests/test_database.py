"""Tests for the database storage layer."""

from datetime import date

from homebuyer.storage.database import Database
from homebuyer.storage.models import MarketMetric, MortgageRate, PropertySale


def test_initialize_schema(tmp_db: Database):
    """Schema initialization creates all tables."""
    tables = tmp_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {r[0] for r in tables}
    assert "property_sales" in table_names
    assert "market_metrics" in table_names
    assert "mortgage_rates" in table_names
    assert "neighborhoods" in table_names
    assert "collection_runs" in table_names
    assert "schema_version" in table_names


def test_upsert_sale(tmp_db: Database, sample_sale: PropertySale):
    """Insert a sale and verify it's stored."""
    result = tmp_db.upsert_sale(sample_sale)
    assert result is True

    row = tmp_db.conn.execute(
        "SELECT * FROM property_sales WHERE mls_number = ?",
        (sample_sale.mls_number,),
    ).fetchone()

    assert row is not None
    assert row["address"] == "123 Test St"
    assert row["sale_price"] == 1_200_000
    assert row["beds"] == 3.0


def test_upsert_sale_duplicate_skipped(tmp_db: Database, sample_sale: PropertySale):
    """Duplicate MLS numbers are silently skipped."""
    tmp_db.upsert_sale(sample_sale)
    result = tmp_db.upsert_sale(sample_sale)
    assert result is False

    count = tmp_db.conn.execute("SELECT COUNT(*) FROM property_sales").fetchone()[0]
    assert count == 1


def test_upsert_sales_batch(tmp_db: Database, sample_sale: PropertySale):
    """Batch insert with dedup counting."""
    sale2 = PropertySale(
        mls_number="ML99999",
        address="456 Another St",
        city="Berkeley",
        state="CA",
        zip_code="94703",
        sale_date=date(2024, 7, 1),
        sale_price=900_000,
        latitude=37.87,
        longitude=-122.27,
    )

    inserted, dupes = tmp_db.upsert_sales_batch([sample_sale, sale2, sample_sale])
    assert inserted == 2
    assert dupes == 1


def test_upsert_mortgage_rate(tmp_db: Database):
    """Insert and update mortgage rates."""
    rate = MortgageRate(
        observation_date=date(2024, 1, 4),
        rate_30yr=6.62,
        rate_15yr=5.89,
    )
    result = tmp_db.upsert_mortgage_rate(rate)
    assert result is True

    # Update with new values
    rate.rate_30yr = 6.75
    result = tmp_db.upsert_mortgage_rate(rate)
    assert result is True

    row = tmp_db.conn.execute(
        "SELECT rate_30yr FROM mortgage_rates WHERE observation_date = '2024-01-04'"
    ).fetchone()
    assert row["rate_30yr"] == 6.75


def test_get_statistics(tmp_db: Database, sample_sale: PropertySale):
    """Statistics include all table counts."""
    tmp_db.upsert_sale(sample_sale)
    stats = tmp_db.get_statistics()

    assert stats["property_sales"]["count"] == 1
    assert stats["market_metrics"]["count"] == 0
    assert stats["mortgage_rates"]["count"] == 0


def test_collection_run_tracking(tmp_db: Database):
    """Collection runs are tracked with start/completion."""
    from homebuyer.storage.models import CollectionResult

    run_id = tmp_db.start_collection_run("test_source", {"key": "value"})
    assert run_id is not None
    assert run_id > 0

    result = CollectionResult(
        source="test_source",
        records_fetched=100,
        records_inserted=95,
        records_duplicates=5,
    )
    tmp_db.complete_collection_run(run_id, result)

    row = tmp_db.conn.execute(
        "SELECT * FROM collection_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert row["status"] == "success"
    assert row["records_fetched"] == 100
    assert row["records_inserted"] == 95
