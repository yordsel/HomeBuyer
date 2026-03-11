"""Fetch active Redfin listing details for price prediction.

Given a Redfin listing URL, extracts property details (beds, baths,
sqft, year_built, list_price, neighborhood, coordinates, etc.) by:

1. Primary: Fetching the listing HTML page and extracting the
   embedded JSON-LD (Schema.org) structured data.
2. Fallback: Parsing key property details from the initial-info
   stingray API endpoint.

The extracted data is normalized into a dict that matches the
FeatureBuilder's expected input format.
"""

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import requests

from homebuyer.processing.normalize import normalize_neighborhood
from homebuyer.utils.http import create_session, rate_limited_get
from homebuyer.utils.parse import safe_float, safe_int

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

_REDFIN_URL_PATTERN = re.compile(
    r"redfin\.com/[A-Z]{2}/[^/]+/[^/]+/home/(\d+)",
    re.IGNORECASE,
)

_PROPERTY_ID_PATTERN = re.compile(r"/home/(\d+)")


def extract_property_id(url: str) -> Optional[str]:
    """Extract the Redfin property ID from a listing URL.

    Args:
        url: A Redfin listing URL like
             https://www.redfin.com/CA/Berkeley/1234-Cedar-St-94702/home/12345678

    Returns:
        The numeric property ID string, or None if not found.
    """
    match = _PROPERTY_ID_PATTERN.search(url)
    if match:
        return match.group(1)
    return None


def extract_address_from_url(url: str) -> Optional[str]:
    """Extract a rough address from the URL path.

    Args:
        url: A Redfin listing URL.

    Returns:
        Address string parsed from the URL, or None.
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    # Typical: CA/Berkeley/1234-Cedar-St-94702/home/12345678
    if len(parts) >= 3:
        addr_part = parts[2]
        # Convert dashes to spaces, remove zip code suffix
        addr = addr_part.replace("-", " ")
        # Remove trailing zip code
        addr = re.sub(r"\s+\d{5}$", "", addr)
        return addr
    return None


# ---------------------------------------------------------------------------
# Listing fetcher
# ---------------------------------------------------------------------------


class ListingFetcher:
    """Fetches and parses Redfin listing details."""

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or create_session()

    def fetch_listing(self, url: str) -> dict:
        """Fetch property details from a Redfin listing URL.

        Tries HTML JSON-LD extraction first, then falls back to the
        stingray API if available.

        Args:
            url: Full Redfin listing URL.

        Returns:
            Dict with normalized property attributes:
                address, city, state, zip_code, neighborhood,
                beds, baths, sqft, lot_size_sqft, year_built,
                property_type, list_price, latitude, longitude,
                hoa_per_month, redfin_url, property_id

        Raises:
            ValueError: If the URL is not a valid Redfin listing.
            ConnectionError: If the listing cannot be fetched.
        """
        property_id = extract_property_id(url)
        if not property_id:
            raise ValueError(
                f"Could not extract property ID from URL: {url}\n"
                "Expected format: https://www.redfin.com/CA/Berkeley/.../home/NNNNNNN"
            )

        logger.info("Fetching listing %s from %s", property_id, url)

        # Try HTML page first (most reliable for JSON-LD)
        result = self._fetch_from_html(url, property_id)

        if result:
            result["redfin_url"] = url
            result["property_id"] = property_id
            return result

        # Fallback: try stingray API
        result = self._fetch_from_stingray(property_id)

        if result:
            result["redfin_url"] = url
            result["property_id"] = property_id
            return result

        raise ConnectionError(
            f"Could not fetch listing details for property {property_id}. "
            "Redfin may have changed their page structure."
        )

    def _fetch_from_html(self, url: str, property_id: str) -> Optional[dict]:
        """Extract listing details from the HTML page's JSON-LD data.

        Redfin embeds Schema.org structured data in a
        <script type="application/ld+json"> tag.  After parsing JSON-LD
        we supplement missing fields by scraping structured text from
        the page body (lot size, HOA, etc.).
        """
        try:
            response = rate_limited_get(self.session, url, delay=2.0)
        except (requests.HTTPError, requests.ConnectionError) as e:
            logger.warning("Failed to fetch HTML page: %s", e)
            return None

        html = response.text
        result: Optional[dict] = None

        # Extract JSON-LD blocks
        json_ld_pattern = re.compile(
            r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
            re.DOTALL,
        )

        for match in json_ld_pattern.finditer(html):
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

            # Handle both single objects and arrays
            if isinstance(data, list):
                for item in data:
                    result = self._parse_json_ld(item)
                    if result:
                        break
            else:
                result = self._parse_json_ld(data)

            if result:
                break

        # Fallback: try to extract from inline JavaScript state
        if not result:
            result = self._parse_from_inline_js(html)

        if not result:
            logger.warning("No JSON-LD or inline data found for property %s.", property_id)
            return None

        # Supplement missing fields from page HTML
        self._supplement_from_html(result, html)

        return result

    def _parse_json_ld(self, data: dict) -> Optional[dict]:
        """Parse a JSON-LD object for property details.

        Handles Schema.org SingleFamilyResidence, House, and
        RealEstateListing/Product wrapper types (which nest the
        property inside a ``mainEntity`` key).
        """
        schema_type = data.get("@type", "")
        if isinstance(schema_type, list):
            type_set = set(schema_type)
            schema_type = schema_type[0] if schema_type else ""
        else:
            type_set = {schema_type}

        # Check for property-related types
        property_types = {
            "SingleFamilyResidence",
            "House",
            "Apartment",
            "Residence",
            "RealEstateListing",
            "Product",
        }

        if not type_set & property_types:
            return None

        # If this is a RealEstateListing/Product wrapper, the actual
        # property data lives inside ``mainEntity``.  Extract offers
        # (list price) from the wrapper, then drill into mainEntity.
        wrapper_offers = data.get("offers", {})
        main_entity = data.get("mainEntity", {})

        if main_entity and isinstance(main_entity, dict):
            # Use the nested entity for property details
            entity = main_entity
            entity_type = entity.get("@type", "")
            if isinstance(entity_type, list):
                entity_type = entity_type[0] if entity_type else ""
        else:
            # Direct property object (no wrapper)
            entity = data
            entity_type = schema_type

        result: dict = {}

        # Address
        address = entity.get("address", {})
        if isinstance(address, dict):
            result["address"] = address.get("streetAddress", "")
            result["city"] = address.get("addressLocality", "")
            result["state"] = address.get("addressRegion", "")
            result["zip_code"] = address.get("postalCode", "")

        # Coordinates
        geo = entity.get("geo", {})
        if isinstance(geo, dict):
            result["latitude"] = safe_float(geo.get("latitude"))
            result["longitude"] = safe_float(geo.get("longitude"))

        # Property details
        result["beds"] = safe_float(
            entity.get("numberOfBedrooms") or entity.get("numberOfRooms")
        )
        result["baths"] = safe_float(entity.get("numberOfBathroomsTotal"))
        result["sqft"] = safe_int(
            entity.get("floorSize", {}).get("value")
            if isinstance(entity.get("floorSize"), dict)
            else entity.get("floorSize")
        )
        result["year_built"] = safe_int(entity.get("yearBuilt"))
        result["lot_size_sqft"] = safe_int(
            entity.get("lotSize", {}).get("value")
            if isinstance(entity.get("lotSize"), dict)
            else entity.get("lotSize")
        )

        # Property type from entity or accommodationCategory
        accom = entity.get("accommodationCategory", "")
        type_map = {
            "SingleFamilyResidence": "Single Family Residential",
            "Single Family Residential": "Single Family Residential",
            "House": "Single Family Residential",
            "Apartment": "Condo/Co-op",
            "Residence": "Single Family Residential",
        }
        result["property_type"] = type_map.get(
            entity_type,
            type_map.get(accom, "Single Family Residential"),
        )

        # List price — prefer wrapper offers, then entity offers
        offers = wrapper_offers or entity.get("offers", {})
        if isinstance(offers, dict):
            result["list_price"] = safe_int(offers.get("price"))
        elif isinstance(offers, list) and offers:
            result["list_price"] = safe_int(offers[0].get("price"))

        # Only return if we got at least an address
        if result.get("address"):
            # Neighborhood will be geocoded later
            if result.get("city", "").lower() == "berkeley":
                result["neighborhood"] = None
            return result

        return None

    def _supplement_from_html(self, result: dict, html: str) -> None:
        """Fill in missing property fields by scraping the page HTML.

        Redfin pages contain structured property facts as text in the
        page body that aren't always present in the JSON-LD.  This
        method extracts lot size, HOA, and other fields when they are
        missing from the JSON-LD result.
        """
        # Lot size — try structured field first, then description
        if not result.get("lot_size_sqft"):
            match = re.search(
                r"Lot Size Square Feet[:\"]?\s*[:\"]?\s*([\d,]+)", html
            )
            if match:
                result["lot_size_sqft"] = safe_int(match.group(1))
                logger.debug("Scraped lot_size_sqft=%s from HTML.", result["lot_size_sqft"])

        if not result.get("lot_size_sqft"):
            # Try acres and convert (1 acre = 43,560 sqft)
            # Matches "Lot Size Acres: 0.29" or "Lot Size: 0.29 acres"
            for acres_pattern in [
                r"Lot Size Acres[:\"]?\s*[:\"]?\s*([\d.]+)",
                r"Lot Size[:\"]?\s*[:\"]?\s*([\d.]+)\s*acres?",
            ]:
                match = re.search(acres_pattern, html, re.IGNORECASE)
                if match:
                    acres = safe_float(match.group(1))
                    if acres and acres > 0:
                        result["lot_size_sqft"] = int(acres * 43_560)
                        logger.debug(
                            "Scraped lot_size_sqft=%s from acres (%.2f) in HTML.",
                            result["lot_size_sqft"], acres,
                        )
                        break

        # HOA dues
        if not result.get("hoa_per_month"):
            # Pattern: "HOA Dues: $NNN/month" or hoaDues: NNN
            match = re.search(
                r"(?:HOA Dues|hoaDues)[^0-9]{0,20}\$?([\d,]+)\s*/?\s*(?:month|mo)",
                html,
                re.IGNORECASE,
            )
            if match:
                result["hoa_per_month"] = safe_int(match.group(1))
                logger.debug("Scraped hoa_per_month=%s from HTML.", result["hoa_per_month"])

        # Year built (if missing from JSON-LD)
        if not result.get("year_built"):
            match = re.search(r"Year Built[:\"]?\s*[:\"]?\s*(\d{4})", html)
            if match:
                result["year_built"] = safe_int(match.group(1))

        # Garage spaces (useful context, store for future use)
        if not result.get("garage_spaces"):
            match = re.search(
                r"Garage Spaces[:\"]?\s*[:\"]?\s*(\d+)", html
            )
            if match:
                result["garage_spaces"] = safe_int(match.group(1))

    def _parse_from_inline_js(self, html: str) -> Optional[dict]:
        """Try to extract property data from inline JavaScript state.

        Some Redfin pages embed property data in a JavaScript variable.
        """
        # Look for __NEXT_DATA__ or similar patterns
        patterns = [
            r'"propertyId"\s*:\s*(\d+).*?"streetAddress"\s*:\s*"([^"]+)"',
            r'"basicInfo"\s*:\s*\{[^}]*"beds"\s*:\s*(\d+)',
        ]

        result: dict = {}

        # Try to find beds, baths, sqft from meta tags
        meta_patterns = {
            "beds": r'<meta[^>]*name="[^"]*bed[^"]*"[^>]*content="(\d+)"',
            "baths": r'<meta[^>]*name="[^"]*bath[^"]*"[^>]*content="([\d.]+)"',
            "sqft": r'<meta[^>]*name="[^"]*sqft[^"]*"[^>]*content="([\d,]+)"',
        }

        for key, pattern in meta_patterns.items():
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                result[key] = safe_float(match.group(1).replace(",", ""))

        # Try to find list price
        price_match = re.search(
            r'"price"\s*:\s*(\d+)|"listPrice"\s*:\s*(\d+)',
            html,
        )
        if price_match:
            result["list_price"] = safe_int(
                price_match.group(1) or price_match.group(2)
            )

        # Only return if we found at least some data
        if result.get("list_price") or result.get("beds"):
            return result

        return None

    def _fetch_from_stingray(self, property_id: str) -> Optional[dict]:
        """Try to fetch listing details from the Redfin stingray API.

        The aboveTheFold endpoint returns detailed property JSON.
        """
        api_url = (
            f"https://www.redfin.com/stingray/api/home/details/"
            f"aboveTheFold?propertyId={property_id}"
        )

        try:
            response = rate_limited_get(self.session, api_url, delay=2.0)
        except (requests.HTTPError, requests.ConnectionError) as e:
            logger.warning("Stingray API failed for property %s: %s", property_id, e)
            return None

        text = response.text

        # Redfin stingray responses start with "{}&&" prefix
        if text.startswith("{}&&"):
            text = text[4:]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse stingray response for property %s.", property_id)
            return None

        return self._parse_stingray_response(data)

    def _parse_stingray_response(self, data: dict) -> Optional[dict]:
        """Parse a stingray API response into normalized property dict."""
        payload = data.get("payload", {})
        if not payload:
            return None

        # Navigate the nested structure
        listing = payload.get("listingDetail", payload)
        basic_info = listing.get("basicInfo", {})
        address_info = listing.get("address", basic_info.get("address", {}))

        result: dict = {}

        # Address
        result["address"] = address_info.get("streetAddress", "")
        result["city"] = address_info.get("city", "")
        result["state"] = address_info.get("stateOrProvince", "")
        result["zip_code"] = address_info.get("postalCode", "")

        # Coordinates
        result["latitude"] = safe_float(address_info.get("latitude"))
        result["longitude"] = safe_float(address_info.get("longitude"))

        # Property details
        result["beds"] = safe_float(basic_info.get("beds"))
        result["baths"] = safe_float(basic_info.get("baths"))
        result["sqft"] = safe_int(basic_info.get("sqFt"))
        result["year_built"] = safe_int(basic_info.get("yearBuilt"))
        result["lot_size_sqft"] = safe_int(basic_info.get("lotSqFt"))
        result["hoa_per_month"] = safe_int(basic_info.get("hoa", {}).get("amount"))
        result["list_price"] = safe_int(basic_info.get("price"))

        # Property type
        prop_type = basic_info.get("propertyType", "")
        type_map = {
            "SINGLE_FAMILY_RESIDENTIAL": "Single Family Residential",
            "CONDO": "Condo/Co-op",
            "TOWNHOUSE": "Townhouse",
            "MULTI_FAMILY": "Multi-Family (2-4 Unit)",
        }
        result["property_type"] = type_map.get(prop_type, "Single Family Residential")

        if result.get("address"):
            return result

        return None


def resolve_neighborhood(
    property_dict: dict,
    db=None,
) -> str:
    """Resolve the neighborhood for a property.

    Tries in order:
    1. Normalize the raw neighborhood name if available
    2. Geocode from lat/lon using the neighborhood boundaries

    Args:
        property_dict: Dict with latitude, longitude, and optionally
                      neighborhood_raw.
        db: Optional Database for looking up by coordinates.

    Returns:
        Canonical neighborhood name, or "Unknown" if unresolvable.
    """
    # Try raw neighborhood normalization
    raw = property_dict.get("neighborhood_raw", "")
    if raw:
        normalized = normalize_neighborhood(raw)
        if normalized:
            return normalized

    # Try geocoding from coordinates
    lat = property_dict.get("latitude")
    lon = property_dict.get("longitude")
    if lat and lon:
        try:
            from homebuyer.processing.geocode import NeighborhoodGeocoder

            geocoder = NeighborhoodGeocoder()
            neighborhood = geocoder.geocode_point(lat, lon)
            if neighborhood:
                return neighborhood

            # Point may be just outside a polygon boundary.
            # Fall back to nearest neighborhood within ~500 m.
            neighborhood = _nearest_neighborhood(lat, lon)
            if neighborhood:
                return neighborhood
        except Exception as e:
            logger.warning("Geocoding failed: %s", e)

    return "Unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nearest_neighborhood(lat: float, lon: float, max_distance_deg: float = 0.005) -> Optional[str]:
    """Find the nearest neighborhood polygon within a tolerance.

    Uses a simple geographic distance (~0.005 degrees ≈ 500 m) to handle
    points that fall just outside a polygon boundary.

    Args:
        lat: Latitude.
        lon: Longitude.
        max_distance_deg: Maximum distance in degrees (~111 m per 0.001°).

    Returns:
        Nearest neighborhood name, or None if nothing is close enough.
    """
    try:
        import warnings

        import geopandas as gpd
        from shapely.geometry import Point

        from homebuyer.config import GEO_DIR

        gdf = gpd.read_file(GEO_DIR / "berkeley_neighborhoods.geojson")

        # Drop polygons with null/empty names
        gdf = gdf[gdf["name"].notna() & (gdf["name"] != "")].reset_index(drop=True)

        point = Point(lon, lat)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            gdf["distance"] = gdf.geometry.distance(point)
        closest = gdf.loc[gdf["distance"].idxmin()]
        if closest["distance"] <= max_distance_deg:
            logger.info(
                "Nearest neighborhood for (%.4f, %.4f): %s (%.0f m away)",
                lat, lon, closest["name"],
                closest["distance"] * 111_139,
            )
            return closest["name"]
    except Exception as e:
        logger.warning("Nearest-neighborhood lookup failed: %s", e)
    return None


