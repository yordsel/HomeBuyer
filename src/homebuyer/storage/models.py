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
    latitude: float
    longitude: float
    sale_date: Optional[date] = None
    sale_price: Optional[int] = None
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
    zoning_class: Optional[str] = None
    redfin_url: Optional[str] = None
    days_on_market: Optional[int] = None
    price_range_bucket: Optional[str] = None
    data_source: Optional[str] = None


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
class EconomicIndicator:
    """A single economic indicator observation from FRED.

    Stores data for any FRED series (NASDAQ, Treasury, CPI, etc.)
    in a generic (series_id, date, value) format.
    """

    series_id: str
    observation_date: date
    value: float


@dataclass
class CensusIncome:
    """Median household income from the Census ACS for a zip code.

    Each record represents one ACS vintage year's 5-year estimate
    for a specific zip code (ZCTA).
    """

    zip_code: str
    acs_year: int  # e.g. 2023 means the 2019-2023 5-year estimate
    median_household_income: int
    margin_of_error: Optional[int] = None


@dataclass
class BuildingPermit:
    """A building permit record from the Accela Citizen Access portal."""

    record_number: str
    address: str
    permit_type: Optional[str] = None
    status: Optional[str] = None
    zip_code: Optional[str] = None
    parcel_id: Optional[str] = None
    description: Optional[str] = None
    job_value: Optional[float] = None
    construction_type: Optional[str] = None
    contractor_cslb: Optional[str] = None
    owner_name: Optional[str] = None
    filed_date: Optional[str] = None
    detail_url: Optional[str] = None


@dataclass
class BESORecord:
    """A BESO (Building Energy Saving Ordinance) record from Berkeley Open Data.

    Tracks energy benchmarking data for commercial and large residential
    buildings. Required at time of sale since Jan 1, 2026.
    """

    beso_id: str
    building_address: str
    beso_property_type: Optional[str] = None
    floor_area: Optional[int] = None
    energy_star_score: Optional[int] = None
    site_eui: Optional[float] = None
    benchmark_status: Optional[str] = None
    assessment_status: Optional[str] = None
    reporting_year: Optional[int] = None


@dataclass
class UseCode:
    """Alameda County Assessor use code reference data.

    Maps use codes to property categories, ownership types, and semantic
    metadata about what lot_size and building_ar mean for each type.
    """

    use_code: str
    description: str
    property_category: str  # sfr, duplex, triplex, fourplex, apartment, condo, townhouse, pud, land, mixed_use, other
    ownership_type: str  # fee_simple, common_interest, cooperative
    record_type: str  # 'lot' (physical lot) or 'unit' (sellable unit within a lot)
    estimated_units: Optional[int] = None
    is_residential: bool = True
    lot_size_meaning: Optional[str] = None  # 'parcel' or 'shared'
    building_ar_meaning: Optional[str] = None  # 'building_footprint' or 'unit_area'


@dataclass
class BerkeleyParcel:
    """A property parcel from the City of Berkeley Open Data / Alameda County Assessor.

    Represents a physical parcel of land with its county-assessed characteristics.
    API-enriched fields (beds, baths, year_built, etc.) are populated later
    via batch enrichment (RentCast) and are nullable until then.

    Parcels may represent physical lots (SFR, apartments) or individual
    sellable units (condos). The record_type and lot_group_key fields
    distinguish these cases for development analysis and ML features.
    """

    apn: str  # Assessor Parcel Number (primary key)
    address: str  # Full situs address (e.g., "1234 CEDAR ST BERKELEY 94702")
    street_number: str  # House number
    street_name: str  # Street name
    zip_code: str
    latitude: float
    longitude: float
    lot_size_sqft: int  # From county data (for condo units, may be shared parcel size or 0)
    building_sqft: Optional[int] = None  # From county data (building_ar field)
    use_code: str = ""  # County land use code (e.g., "1100")
    use_description: Optional[str] = None  # Human-readable (e.g., "Single Family Residential")
    neighborhood: Optional[str] = None  # From spatial join
    zoning_class: Optional[str] = None  # From spatial join
    # New fields from use_code reference
    situs_unit: Optional[str] = None  # Unit identifier (A, B, C, etc.) from Berkeley data
    property_category: Optional[str] = None  # From use_codes table (sfr, condo, etc.)
    ownership_type: Optional[str] = None  # fee_simple, common_interest, cooperative
    record_type: Optional[str] = None  # 'lot' or 'unit'
    lot_group_key: Optional[str] = None  # Grouping key for condo/unit aggregation
    parcel_lot_size_sqft: Optional[int] = None  # Raw lot_size from Berkeley data
    # API-enriched fields (nullable until enriched via RentCast)
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None  # API sqft (may differ from building_sqft)
    year_built: Optional[int] = None
    property_type: Optional[str] = None  # Standardized type
    last_sale_date: Optional[str] = None
    last_sale_price: Optional[int] = None
    rentcast_enriched: bool = False  # Flag: has RentCast API enrichment been fetched?


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
