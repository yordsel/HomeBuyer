"""Configuration constants and settings for the HomeBuyer application."""

import dataclasses
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Project paths (relative to project root)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
GEO_DIR = DATA_DIR / "geo"
DB_PATH = DATA_DIR / "berkeley_homebuyer.db"

# ---------------------------------------------------------------------------
# Redfin gis-csv API
# ---------------------------------------------------------------------------
REDFIN_GIS_CSV_BASE = "https://www.redfin.com/stingray/api/gis-csv"
REDFIN_MARKET_S3_CITY = (
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
    "redfin_market_tracker/city_market_tracker.tsv000.gz"
)
BERKELEY_REGION_ID = 1590
BERKELEY_REGION_TYPE = 6  # city
REDFIN_MARKET_NAME = "sanfrancisco"
REDFIN_MAX_RESULTS_PER_QUERY = 350
REDFIN_CAP_SAFETY_THRESHOLD = 345  # If we get this many rows, assume capped

# ---------------------------------------------------------------------------
# FRED (Federal Reserve Economic Data)
# ---------------------------------------------------------------------------
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SERIES_30YR = "MORTGAGE30US"
FRED_SERIES_15YR = "MORTGAGE15US"

# ---------------------------------------------------------------------------
# HTTP settings
# ---------------------------------------------------------------------------
REQUEST_DELAY_SECONDS = 3.0  # Politeness delay between Redfin requests
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 5

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Berkeley-specific constants
# ---------------------------------------------------------------------------
BERKELEY_CITY_NAME = "Berkeley"
BERKELEY_ZIP_CODES = ["94702", "94703", "94704", "94705", "94707", "94708", "94709", "94710"]

# Default years of sales data to collect
DEFAULT_SOLD_WITHIN_DAYS = 1825  # ~5 years

# ---------------------------------------------------------------------------
# Price range buckets for adaptive splitting
# Designed for Berkeley's price distribution to keep each bucket under 350 rows
# ---------------------------------------------------------------------------
DEFAULT_PRICE_RANGES: list[tuple[int, int]] = [
    (0, 500_000),
    (500_000, 750_000),
    (750_000, 900_000),
    (900_000, 1_050_000),
    (1_050_000, 1_200_000),
    (1_200_000, 1_400_000),
    (1_400_000, 1_600_000),
    (1_600_000, 1_900_000),
    (1_900_000, 2_300_000),
    (2_300_000, 3_000_000),
    (3_000_000, 5_000_000),
    (5_000_000, 20_000_000),
]


@dataclasses.dataclass
class PriceRange:
    """A price range bucket for querying Redfin."""

    min_price: int
    max_price: int

    @property
    def midpoint(self) -> int:
        return (self.min_price + self.max_price) // 2

    @property
    def width(self) -> int:
        return self.max_price - self.min_price

    def split(self) -> tuple["PriceRange", "PriceRange"]:
        """Split this range into two halves at the midpoint."""
        mid = self.midpoint
        return (
            PriceRange(self.min_price, mid),
            PriceRange(mid + 1, self.max_price),
        )

    def __str__(self) -> str:
        return f"${self.min_price:,}-${self.max_price:,}"
