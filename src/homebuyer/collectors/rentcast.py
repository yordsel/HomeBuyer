"""RentCast Property Data API client for property detail lookups.

Primary source for property enrichment data including beds, baths, sqft,
year_built, property_type, last_sale_price, last_sale_date, lot_size,
tax history, sale transaction history, and more.

API docs: https://developers.rentcast.io/reference/property-data

Rate limit: 20 requests/second per API key.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from homebuyer.utils.parse import safe_float, safe_int

logger = logging.getLogger(__name__)

RENTCAST_BASE_URL = "https://api.rentcast.io/v1"


# ---------------------------------------------------------------------------
# Parsed results
# ---------------------------------------------------------------------------


@dataclass
class RentcastSaleTransaction:
    """A single sale transaction from RentCast property history."""

    sale_date: str  # ISO YYYY-MM-DD
    sale_price: int
    event_type: Optional[str] = None  # e.g. "Sold"


@dataclass
class RentcastPropertyDetail:
    """Normalized property details extracted from a RentCast API response."""

    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    property_type: Optional[str] = None
    last_sale_price: Optional[int] = None
    last_sale_date: Optional[str] = None  # ISO YYYY-MM-DD
    assessed_value: Optional[int] = None
    tax_amount: Optional[int] = None
    owner_occupied: Optional[bool] = None
    resolved_address: Optional[str] = None
    source_fields: list[str] = field(default_factory=list)
    sale_history: list[RentcastSaleTransaction] = field(default_factory=list)
    _raw_json: Optional[dict] = field(default=None, repr=False)

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
        if self.last_sale_price is not None:
            result["last_sale_price"] = self.last_sale_price
        if self.last_sale_date is not None:
            result["last_sale_date"] = self.last_sale_date
        return result


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class RentcastClient:
    """Client for RentCast property detail and sale history lookups."""

    def __init__(self, api_key: str = "") -> None:
        from homebuyer.config import RENTCAST_API_KEY

        self.api_key = api_key or RENTCAST_API_KEY
        self.enabled = bool(self.api_key)
        self._session: Optional[requests.Session] = None

        # In-memory cache: normalised address -> (detail, timestamp)
        self._cache: dict[str, tuple[RentcastPropertyDetail, float]] = {}
        self._cache_ttl = 86_400  # 24 hours

        if not self.enabled:
            logger.info("RentCast API key not configured — RentCast enrichment disabled.")

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "X-Api-Key": self.api_key,
                "Accept": "application/json",
            })
        return self._session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup_property(
        self,
        address: str,
        city: str = "Berkeley",
        state: str = "CA",
        zip_code: str = "",
    ) -> Optional[RentcastPropertyDetail]:
        """Look up property details by full address.

        Args:
            address: Full address (e.g. "1615 Alcatraz Ave, Berkeley, CA 94703")
                     or just the street part.
            city: City name (default "Berkeley").
            state: State abbreviation (default "CA").
            zip_code: Zip code (optional but improves matching).

        Returns:
            ``RentcastPropertyDetail`` if the property was found, ``None`` otherwise.
            The ``_raw_json`` field contains the full API response for caching.
        """
        if not self.enabled:
            return None
        if not address:
            return None

        # Build the full address string for the API
        full_address = self._build_full_address(address, city, state, zip_code)

        # --- cache check ---
        cache_key = full_address.lower().strip()
        cached = self._cache.get(cache_key)
        if cached:
            detail, ts = cached
            if time.time() - ts < self._cache_ttl:
                logger.debug("RentCast cache hit for %s", full_address)
                return detail

        # --- API request ---
        try:
            resp = self.session.get(
                f"{RENTCAST_BASE_URL}/properties",
                params={"address": full_address},
                timeout=10,
            )

            if resp.status_code in (400, 404):
                logger.debug(
                    "RentCast: no property found for '%s' (HTTP %d)",
                    full_address, resp.status_code,
                )
                return None

            if resp.status_code == 429:
                logger.warning("RentCast: rate-limited (429).")
                return None

            if resp.status_code in (401, 403):
                logger.error(
                    "RentCast: authentication/billing error (%d). Check API key and subscription.",
                    resp.status_code,
                )
                return None

            resp.raise_for_status()
            data = resp.json()

            # RentCast returns an array of matching properties
            if not data or not isinstance(data, list) or len(data) == 0:
                logger.debug("RentCast: empty result for '%s'", full_address)
                return None

            detail = self._parse_property(data[0])
            if detail:
                detail._raw_json = data[0]
                self._cache[cache_key] = (detail, time.time())
            return detail

        except requests.Timeout:
            logger.warning("RentCast: request timed out for '%s'", full_address)
            return None
        except requests.RequestException as exc:
            logger.warning("RentCast: request failed for '%s': %s", full_address, exc)
            return None
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("RentCast: failed to parse response for '%s': %s", full_address, exc)
            return None

    def lookup_sale_history(
        self,
        address: str,
        city: str = "Berkeley",
        state: str = "CA",
        zip_code: str = "",
    ) -> list[RentcastSaleTransaction]:
        """Return parsed sale history for a property.

        Uses the history field from /v1/properties (no extra API call if cached).

        Returns:
            List of ``RentcastSaleTransaction`` sorted by date ascending.
        """
        detail = self.lookup_property(address, city, state, zip_code)
        if not detail or not detail.sale_history:
            return []
        return detail.sale_history

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_property(self, prop: dict) -> Optional[RentcastPropertyDetail]:
        """Extract property fields from a single RentCast property JSON object."""
        detail = RentcastPropertyDetail()
        source_fields: list[str] = []

        # --- Bedrooms ---
        beds = safe_float(prop.get("bedrooms"))
        if beds is not None:
            detail.beds = beds
            source_fields.append("beds")

        # --- Bathrooms ---
        baths = safe_float(prop.get("bathrooms"))
        if baths is not None:
            detail.baths = baths
            source_fields.append("baths")

        # --- Square footage ---
        sqft = safe_int(prop.get("squareFootage"))
        if sqft is not None and sqft > 0:
            detail.sqft = sqft
            source_fields.append("sqft")

        # --- Year built ---
        year = safe_int(prop.get("yearBuilt"))
        if year is not None and 1800 <= year <= 2030:
            detail.year_built = year
            source_fields.append("year_built")

        # --- Lot size ---
        lot_sqft = safe_int(prop.get("lotSize"))
        if lot_sqft is not None and lot_sqft > 0:
            detail.lot_size_sqft = lot_sqft
            source_fields.append("lot_size_sqft")

        # --- Property type ---
        prop_type = prop.get("propertyType")
        if prop_type:
            detail.property_type = _map_property_type(prop_type)
            source_fields.append("property_type")

        # --- Last sale ---
        sale_price = safe_int(prop.get("lastSalePrice"))
        if sale_price is not None and sale_price > 0:
            detail.last_sale_price = sale_price
            source_fields.append("last_sale_price")

        sale_date_raw = prop.get("lastSaleDate") or ""
        if sale_date_raw and len(sale_date_raw) >= 10:
            detail.last_sale_date = sale_date_raw[:10]
            source_fields.append("last_sale_date")

        # --- Tax / assessment (latest year) ---
        tax_assessments = prop.get("taxAssessments") or {}
        if tax_assessments:
            latest_year = max(tax_assessments.keys(), default=None)
            if latest_year:
                detail.assessed_value = safe_int(
                    tax_assessments[latest_year].get("value")
                )

        prop_taxes = prop.get("propertyTaxes") or {}
        if prop_taxes:
            latest_year = max(prop_taxes.keys(), default=None)
            if latest_year:
                detail.tax_amount = safe_int(
                    prop_taxes[latest_year].get("total")
                )

        # --- Owner occupied ---
        if prop.get("ownerOccupied") is not None:
            detail.owner_occupied = bool(prop["ownerOccupied"])

        # --- Resolved address ---
        detail.resolved_address = prop.get("formattedAddress")

        # --- Sale history ---
        history = prop.get("history") or {}
        sale_transactions: list[RentcastSaleTransaction] = []
        for date_key in sorted(history.keys()):
            txn = history[date_key]
            price = safe_int(txn.get("price"))
            if price and price > 0:
                sale_transactions.append(RentcastSaleTransaction(
                    sale_date=date_key[:10],
                    sale_price=price,
                    event_type=txn.get("event"),
                ))
        detail.sale_history = sale_transactions

        detail.source_fields = source_fields
        return detail if source_fields else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_full_address(
        address: str,
        city: str,
        state: str,
        zip_code: str,
    ) -> str:
        """Build a full address string from components.

        If the address already contains the city/state, return as-is.
        Otherwise, append city, state, and zip.
        """
        addr_upper = address.upper()
        # Check if address already has city info
        if city.upper() in addr_upper and state.upper() in addr_upper:
            return address.strip()

        # Check if it at least has a comma (already formatted)
        if "," in address:
            return address.strip()

        # Build from components
        parts = [address.strip()]
        if city:
            parts.append(city.strip())
        if state:
            # Combine state and zip
            state_zip = state.strip()
            if zip_code:
                state_zip += f" {zip_code.strip()}"
            parts.append(state_zip)

        return ", ".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _map_property_type(rentcast_type: str) -> str:
    """Map RentCast propertyType to our internal type strings.

    RentCast types: "Single Family", "Condo", "Townhouse", "Multi Family",
    "Apartment", "Mobile", "Land", "Other"
    """
    t = rentcast_type.upper()

    if "SINGLE FAMILY" in t:
        return "Single Family Residential"
    if "CONDO" in t or "CO-OP" in t:
        return "Condo/Co-op"
    if "TOWNHOUSE" in t or "TOWNHOME" in t:
        return "Townhouse"
    if "MULTI" in t or "DUPLEX" in t or "TRIPLEX" in t or "QUADPLEX" in t:
        return "Multi-Family (2-4 Unit)"
    if "APARTMENT" in t:
        return "Multi-Family (5+ Unit)"
    # Fallback
    return rentcast_type


