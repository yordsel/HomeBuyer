"""Shared test fixtures."""

import tempfile
from pathlib import Path

import pytest

from homebuyer.storage.database import Database


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.connect()
    db.initialize_schema()
    yield db
    db.close()


@pytest.fixture
def sample_sale():
    """Return a sample PropertySale dict for testing."""
    from datetime import date
    from homebuyer.storage.models import PropertySale

    return PropertySale(
        mls_number="ML12345",
        address="123 Test St",
        city="Berkeley",
        state="CA",
        zip_code="94702",
        sale_date=date(2024, 6, 15),
        sale_price=1_200_000,
        sale_type="PAST SALE",
        property_type="Single Family Residential",
        beds=3.0,
        baths=2.0,
        sqft=1800,
        lot_size_sqft=5000,
        year_built=1925,
        price_per_sqft=666.67,
        hoa_per_month=None,
        latitude=37.8716,
        longitude=-122.2727,
        neighborhood_raw="N BERKELEY",
        redfin_url="https://www.redfin.com/CA/Berkeley/123-Test-St",
        days_on_market=None,
        price_range_bucket="$1,050,000-$1,200,000",
    )
