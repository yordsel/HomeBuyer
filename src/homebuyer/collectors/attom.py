"""ATTOM Property Data API client for real-time property detail lookups.

Used by the map-click prediction endpoint to auto-fill property details
when the local database has no nearby match.  Gracefully degrades: if the
API key is missing or the request fails, returns ``None`` so the caller
can fall back to the manual-entry form.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ATTOM_BASE_URL = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"


# ---------------------------------------------------------------------------
# Parsed result
# ---------------------------------------------------------------------------


@dataclass
class AttomPropertyDetail:
    """Normalized property details extracted from an ATTOM API response."""

    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    property_type: Optional[str] = None
    source_fields: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True when all fields required for a prediction are present."""
        return all([
            self.beds is not None,
            self.baths is not None,
            self.sqft is not None,
            self.year_built is not None,
        ])

    def to_dict(self) -> dict:
        """Return only the non-None fields as a plain dict."""
        result: dict = {}
        if self.beds is not None:
            result["beds"] = self.beds
        if self.baths is not None:
            result["baths"] = self.baths
        if self.sqft is not None:
            result["sqft"] = self.sqft
        if self.year_built is not None:
            result["year_built"] = self.year_built
        if self.lot_size_sqft is not None:
            result["lot_size_sqft"] = self.lot_size_sqft
        if self.property_type is not None:
            result["property_type"] = self.property_type
        return result


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AttomClient:
    """Lightweight client for ATTOM property detail lookups."""

    def __init__(self, api_key: str = "") -> None:
        from homebuyer.config import ATTOM_API_KEY

        self.api_key = api_key or ATTOM_API_KEY
        self.enabled = bool(self.api_key)
        self._session: Optional[requests.Session] = None

        # In-memory cache: normalised address → (detail, timestamp)
        self._cache: dict[str, tuple[AttomPropertyDetail, float]] = {}
        self._cache_ttl = 86_400  # 24 hours

        if not self.enabled:
            logger.info("ATTOM API key not configured — property auto-fill disabled.")

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "apikey": self.api_key,
                "Accept": "application/json",
            })
        return self._session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup_property(
        self,
        address1: str,
        address2: str = "Berkeley, CA",
    ) -> Optional[AttomPropertyDetail]:
        """Look up property details by street address.

        Args:
            address1: Street address line (e.g. ``"1234 Cedar St"``).
            address2: City / state / zip (default ``"Berkeley, CA"``).

        Returns:
            ``AttomPropertyDetail`` if the property was found, ``None`` otherwise.
        """
        if not self.enabled:
            return None
        if not address1:
            return None

        # --- cache check ---
        cache_key = f"{address1}|{address2}".lower().strip()
        cached = self._cache.get(cache_key)
        if cached:
            detail, ts = cached
            if time.time() - ts < self._cache_ttl:
                logger.debug("ATTOM cache hit for %s", address1)
                return detail

        # --- API request ---
        try:
            resp = self.session.get(
                f"{ATTOM_BASE_URL}/property/detail",
                params={"address1": address1, "address2": address2},
                timeout=10,
            )

            if resp.status_code in (400, 404):
                logger.debug("ATTOM: no property found for %s (HTTP %d)", address1, resp.status_code)
                return None

            if resp.status_code == 429:
                logger.warning("ATTOM: rate-limited (429).")
                return None

            if resp.status_code in (401, 403):
                logger.error(
                    "ATTOM: authentication failed (%d). Check API key.",
                    resp.status_code,
                )
                return None

            resp.raise_for_status()
            data = resp.json()

            # Log raw response at DEBUG level for initial development
            logger.debug("ATTOM raw response keys: %s", list(data.keys()))

            detail = self._parse_response(data)
            if detail:
                self._cache[cache_key] = (detail, time.time())
            return detail

        except requests.Timeout:
            logger.warning("ATTOM: request timed out for %s", address1)
            return None
        except requests.RequestException as exc:
            logger.warning("ATTOM: request failed for %s: %s", address1, exc)
            return None
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("ATTOM: failed to parse response for %s: %s", address1, exc)
            return None

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, data: dict) -> Optional[AttomPropertyDetail]:
        """Extract property fields from the ATTOM JSON payload."""
        properties = data.get("property", [])
        if not properties:
            return None

        prop = properties[0]
        building = prop.get("building", {})
        lot = prop.get("lot", {})
        summary = prop.get("summary", {})

        detail = AttomPropertyDetail()
        source_fields: list[str] = []

        # --- Bedrooms ---
        rooms = building.get("rooms", {})
        beds = _safe_float(
            rooms.get("beds") or rooms.get("bedrooms") or rooms.get("Beds")
        )
        if beds is not None:
            detail.beds = beds
            source_fields.append("beds")

        # --- Bathrooms ---
        baths_total = _safe_float(
            rooms.get("bathstotal")
            or rooms.get("bathsTotal")
            or rooms.get("bathTotal")
        )
        baths_full = _safe_float(
            rooms.get("bathsfull") or rooms.get("bathsFull")
        )
        baths_half = _safe_float(
            rooms.get("bathshalf") or rooms.get("bathsHalf")
        )
        if baths_total is not None:
            detail.baths = baths_total
            source_fields.append("baths")
        elif baths_full is not None:
            detail.baths = baths_full + (baths_half or 0) * 0.5
            source_fields.append("baths")

        # --- Square footage ---
        size = building.get("size", {})
        sqft = _safe_int(
            size.get("universalsize")
            or size.get("universalSize")
            or size.get("livingsize")
            or size.get("livingSize")
        )
        if sqft is not None and sqft > 0:
            detail.sqft = sqft
            source_fields.append("sqft")

        # --- Year built ---
        year = _safe_int(
            summary.get("yearbuilt")
            or summary.get("yearBuilt")
            or building.get("summary", {}).get("yearbuilt")
        )
        if year is not None and 1800 <= year <= 2030:
            detail.year_built = year
            source_fields.append("year_built")

        # --- Lot size ---
        lot_sqft = _safe_int(lot.get("lotsize2") or lot.get("lotSize2"))
        lot_acres = _safe_float(lot.get("lotsize1") or lot.get("lotSize1"))
        if lot_sqft and lot_sqft > 0:
            detail.lot_size_sqft = lot_sqft
            source_fields.append("lot_size_sqft")
        elif lot_acres and lot_acres > 0:
            detail.lot_size_sqft = int(lot_acres * 43_560)
            source_fields.append("lot_size_sqft")

        # --- Property type ---
        # ATTOM uses multiple overlapping fields; check all of them
        prop_class = summary.get("propclass") or summary.get("propClass") or ""
        prop_subtype = summary.get("propsubtype") or summary.get("propSubType") or ""
        prop_type = summary.get("proptype") or summary.get("propType") or ""
        property_type = summary.get("propertyType") or ""
        mapped = _map_property_type(prop_class, prop_subtype, prop_type, property_type)
        if mapped:
            detail.property_type = mapped
            source_fields.append("property_type")

        detail.source_fields = source_fields
        return detail if source_fields else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _map_property_type(
    prop_class: str,
    prop_subtype: str,
    prop_type: str = "",
    property_type: str = "",
) -> Optional[str]:
    """Map ATTOM property class/subtype/type to our internal type strings.

    ATTOM returns type info across several overlapping fields:
    - ``propclass``: e.g. "Single Family Residence", "Apartment", or None
    - ``propsubtype``: e.g. "Residential", "COMMERCIAL"
    - ``proptype``: e.g. "Single Family Residence w/ ADU", "DUPLEX"
    - ``propertyType``: e.g. "SINGLE FAMILY RESIDENTIAL", "DUPLEX (2 UNITS, ...)"

    We combine all of them into a single uppercase string and pattern-match.
    """
    combined = " | ".join(
        s.upper() for s in (prop_class, prop_subtype, prop_type, property_type) if s
    )

    if "SINGLE FAMILY" in combined or "SFR" in combined:
        return "Single Family Residential"
    if "CONDO" in combined or "CO-OP" in combined:
        return "Condo/Co-op"
    if "TOWNHOUSE" in combined or "TOWNHOME" in combined:
        return "Townhouse"
    if "DUPLEX" in combined or "TRIPLEX" in combined or "QUADPLEX" in combined or "2-4" in combined:
        return "Multi-Family (2-4 Unit)"
    # Fall back: if subtype says "Residential" but nothing more specific, assume SFR
    if "RESIDENTIAL" in combined and "COMMERCIAL" not in combined:
        return "Single Family Residential"
    return None


def _safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(str(value).replace(",", ""))
        # Guard against NaN
        return result if result == result else None  # noqa: PLR0124
    except (ValueError, TypeError):
        return None


def _safe_int(value: object) -> Optional[int]:
    f = _safe_float(value)
    return int(f) if f is not None else None
