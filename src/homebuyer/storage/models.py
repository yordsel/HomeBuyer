"""Data models for the HomeBuyer application."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class PropertySale:
    """A single property sale record."""

    address: str
    city: str
    state: str
    zip_code: str
    sale_date: date
    sale_price: int
    latitude: float
    longitude: float
    mls_number: Optional[str] = None
    sale_type: Optional[str] = None
    property_type: Optional[str] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    year_built: Optional[int] = None
    price_per_sqft: Optional[float] = None
    hoa_per_month: Optional[int] = None
    neighborhood_raw: Optional[str] = None
    neighborhood: Optional[str] = None
    redfin_url: Optional[str] = None
    days_on_market: Optional[int] = None
    price_range_bucket: Optional[str] = None


@dataclass
class MarketMetric:
    """An aggregated market metric observation (monthly or weekly)."""

    period_begin: date
    period_end: date
    period_duration: str  # 'monthly' or 'weekly'
    region_name: str
    property_type: Optional[str] = None
    median_sale_price: Optional[int] = None
    median_list_price: Optional[int] = None
    median_ppsf: Optional[float] = None
    homes_sold: Optional[int] = None
    new_listings: Optional[int] = None
    inventory: Optional[int] = None
    months_of_supply: Optional[float] = None
    median_dom: Optional[int] = None
    avg_sale_to_list: Optional[float] = None
    sold_above_list_pct: Optional[float] = None
    price_drops_pct: Optional[float] = None
    off_market_in_two_weeks_pct: Optional[float] = None


@dataclass
class MortgageRate:
    """A weekly mortgage rate observation from FRED."""

    observation_date: date
    rate_30yr: Optional[float] = None
    rate_15yr: Optional[float] = None


@dataclass
class CollectionResult:
    """Result summary from a data collection run."""

    source: str
    records_fetched: int = 0
    records_inserted: int = 0
    records_duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def __str__(self) -> str:
        status = "OK" if self.success else f"ERRORS ({len(self.errors)})"
        return (
            f"[{self.source}] {status}: "
            f"fetched={self.records_fetched}, "
            f"inserted={self.records_inserted}, "
            f"duplicates={self.records_duplicates}"
        )
