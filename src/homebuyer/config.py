"""Configuration constants and settings for the HomeBuyer application."""

import dataclasses
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Project paths (relative to project root)
# ---------------------------------------------------------------------------
# When installed via pip (e.g. on Render), __file__ is in site-packages and
# the 3-parent trick lands inside the venv, not the repo checkout.  Fall back
# to cwd() when the computed root doesn't contain the expected data/ dir.
_computed_root = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = _computed_root if (_computed_root / "data").is_dir() else Path.cwd()
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
GEO_DIR = DATA_DIR / "geo"
DB_PATH = DATA_DIR / "berkeley_homebuyer.db"

# Regulation data (JSON knowledge base)
REGULATIONS_DIR = DATA_DIR / "regulations"
REGULATIONS_SEED_DIR = REGULATIONS_DIR / "seed"
REGULATIONS_SOURCES_DIR = REGULATIONS_DIR / "sources"

# Glossary data (JSON knowledge base — financial & real estate terms)
GLOSSARY_DIR = DATA_DIR / "glossary"
GLOSSARY_SEED_DIR = GLOSSARY_DIR / "seed"

# FHFA conforming loan limits (annual XLSX — used by glossary collector)
# URL pattern: replace year as needed. Published each November for next year.
FHFA_LOAN_LIMITS_URL = (
    "https://www.fhfa.gov/document/data/"
    "fullcountyloanlimitlist2026_hera-based_final_flat.xlsx"
)
FHFA_LOAN_LIMITS_YEAR = 2026
# Alameda County FIPS codes (state=06, county=001)
ALAMEDA_FIPS_STATE = "06"
ALAMEDA_FIPS_COUNTY = "001"

# PostgreSQL connection URL (when set, overrides SQLite file path)
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# Environment (controls security header strictness, CSP policy, etc.)
# ---------------------------------------------------------------------------
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

# ---------------------------------------------------------------------------
# Authentication / JWT
# ---------------------------------------------------------------------------
JWT_SECRET_KEY = os.environ.get(
    "JWT_SECRET_KEY",
    "dev-secret-DO-NOT-USE-IN-PRODUCTION",
)
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# Terms of Service — bump this version when TOS changes to require re-acceptance
CURRENT_TOS_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Google OAuth (optional — enables "Sign in with Google")
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8787/api/auth/google/callback",
)

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

# Additional economic indicator series
FRED_ECONOMIC_SERIES: dict[str, str] = {
    "NASDAQCOM": "NASDAQ Composite Index (daily)",
    "GS10": "10-Year Treasury Constant Maturity Rate (monthly)",
    "UMCSENT": "University of Michigan Consumer Sentiment (monthly)",
    "CUURA422SA0": "CPI All Items: San Francisco-Oakland-Hayward (bimonthly)",
    "SANF806UR": "Unemployment Rate: SF-Oakland-Hayward MSA (monthly)",
}

# Census ACS API
CENSUS_ACS_BASE_URL = "https://api.census.gov/data"

# Berkeley Open Data (Socrata) — BESO energy benchmarking
BERKELEY_OPENDATA_BESO_URL = "https://data.cityofberkeley.info/resource/8k7b-6awf.json"

# Berkeley Open Data (Socrata) — City parcels
BERKELEY_OPENDATA_PARCELS_URL = "https://data.cityofberkeley.info/resource/rax9-nuvx.json"

# ---------------------------------------------------------------------------
# RentCast Property Data API (optional — property enrichment & sale history)
# ---------------------------------------------------------------------------
RENTCAST_API_KEY = os.environ.get("RENTCAST_API_KEY", "")

# ---------------------------------------------------------------------------
# Anthropic Claude API (optional — enables AI-powered property summaries)
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Resend Email API (optional — enables transactional emails for password
# reset and email verification)
# ---------------------------------------------------------------------------
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
# "From" address for transactional emails.  Must be a verified domain in Resend.
EMAIL_FROM = os.environ.get("EMAIL_FROM", "HomeBuyer <info@agentc.work>")
# Base URL for links in emails (password reset, verification).
# In production this should be the deployed frontend URL.
APP_URL = os.environ.get("APP_URL", "http://localhost:1420")

# ---------------------------------------------------------------------------
# Accela Citizen Access (Berkeley building permits)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Berkeley Municipal Code & regulation source URLs (for regulation scraping)
# ---------------------------------------------------------------------------
BMC_TITLE_23_BASE = "https://berkeley.municipal.codes/BMC/23"
BMC_ZONING_SECTIONS: dict[str, str] = {
    "residential": "https://berkeley.municipal.codes/BMC/23.202",
    "commercial": "https://berkeley.municipal.codes/BMC/23.204",
    "mixed_use": "https://berkeley.municipal.codes/BMC/23.206",
    "manufacturing": "https://berkeley.municipal.codes/BMC/23.208",
    "adu": "https://berkeley.municipal.codes/BMC/23.306",
    "hillside": "https://berkeley.municipal.codes/BMC/23.210",
}
BERKELEYCA_MIDDLE_HOUSING_URL = (
    "https://berkeleyca.gov/construction-development/"
    "land-use-development/middle-housing-zoning"
)
BERKELEYCA_TRANSFER_TAX_URL = (
    "https://berkeleyca.gov/city-services/report-pay/property-transfer-tax"
)
BERKELEYCA_BESO_INFO_URL = (
    "https://berkeleyca.gov/construction-development/green-building/"
    "building-emissions-saving-ordinance-beso"
)
BERKELEYCA_PERMITTING_URL = (
    "https://berkeleyca.gov/construction-development/"
    "permits-design-parameters/permit-process"
)
RENT_BOARD_URL = "https://rentboard.berkeleyca.gov/"
RENT_BOARD_RENT_CONTROL_URL = (
    "https://rentboard.berkeleyca.gov/rights-responsibilities/rent-control-101"
)

# ---------------------------------------------------------------------------
# Accela Citizen Access (Berkeley building permits)
# ---------------------------------------------------------------------------
ACCELA_SEARCH_URL = (
    "https://aca-prod.accela.com/BERKELEY/Cap/CapHome.aspx"
    "?module=Building&TabName=Home"
)
ACCELA_DETAIL_BASE = "https://aca-prod.accela.com"
ACCELA_REQUEST_DELAY = 2.0  # seconds between page loads (politeness)
ACCELA_BATCH_SIZE = 50  # upsert every N addresses

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
