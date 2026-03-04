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
    last_sale_price: Optional[int] = None
    last_sale_date: Optional[str] = None  # ISO YYYY-MM-DD
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

    def lookup_last_sale(
        self,
        address1: str,
        address2: str = "Berkeley, CA",
    ) -> tuple[Optional[int], Optional[str]]:
        """Look up the most recent sale price and date for a property.

        Calls the ATTOM ``/sale/detail`` endpoint.

        Args:
            address1: Street address line (e.g. ``"898 Contra Costa Ave"``).
            address2: City / state / zip (e.g. ``"Berkeley, CA 94706"``).

        Returns:
            ``(sale_price, sale_date)`` where *sale_date* is ISO ``YYYY-MM-DD``,
            or ``(None, None)`` on any failure.
        """
        if not self.enabled or not address1:
            return None, None

        try:
            resp = self.session.get(
                f"{ATTOM_BASE_URL}/sale/detail",
                params={"address1": address1, "address2": address2},
                timeout=10,
            )

            if resp.status_code in (400, 404):
                logger.debug("ATTOM sale/detail: no data for %s (HTTP %d)", address1, resp.status_code)
                return None, None
            if resp.status_code == 429:
                logger.warning("ATTOM sale/detail: rate-limited (429).")
                return None, None
            if resp.status_code in (401, 403):
                logger.error("ATTOM sale/detail: auth failed (%d).", resp.status_code)
                return None, None

            resp.raise_for_status()
            data = resp.json()

            properties = data.get("property", [])
            if not properties:
                return None, None

            sale = properties[0].get("sale", {})
            amount = sale.get("amount", {})

            # /sale/detail uses lowercase 'saleamt'
            sale_price = _safe_int(amount.get("saleamt") or amount.get("saleAmt"))

            # Date field varies: try multiple known field names
            sale_date_raw = (
                sale.get("saleTransDate")
                or sale.get("saletransdate")
                or amount.get("salerecdate")
                or amount.get("saleRecDate")
                or sale.get("salesearchdate")
                or sale.get("saleSearchDate")
                or ""
            )

            if not sale_price or sale_price <= 0:
                return None, None

            # Normalise date to YYYY-MM-DD
            sale_date = sale_date_raw[:10] if len(sale_date_raw) >= 10 else None

            logger.debug(
                "ATTOM last sale for %s: $%s on %s",
                address1, f"{sale_price:,}", sale_date,
            )
            return sale_price, sale_date

        except requests.Timeout:
            logger.warning("ATTOM sale/detail: timed out for %s", address1)
            return None, None
        except requests.RequestException as exc:
            logger.warning("ATTOM sale/detail: request failed for %s: %s", address1, exc)
            return None, None
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("ATTOM sale/detail: parse error for %s: %s", address1, exc)
            return None, None

    def lookup_sale_history(
        self,
        address1: str,
        address2: str = "Berkeley, CA",
    ) -> list[dict]:
        """Fetch the full sale history for a property.

        Calls the ATTOM ``/saleshistory/expandedhistory`` endpoint and returns
        only *real* sale transactions (``saleAmt > 0``), filtering out
        refinances, quit-claims, and stand-alone financing.

        Building details (beds, baths, sqft, year_built) come from the
        **property level** and are copied to every sale record.

        Args:
            address1: Street address line.
            address2: City / state / zip.

        Returns:
            A list of dicts with keys: ``sale_price``, ``sale_date``,
            ``sale_type``, ``beds``, ``baths``, ``sqft``, ``year_built``,
            ``lot_size_sqft``, ``property_type``, ``latitude``, ``longitude``,
            ``price_per_sqft``.  Empty list on any failure.
        """
        if not self.enabled or not address1:
            return []

        try:
            resp = self.session.get(
                f"{ATTOM_BASE_URL}/saleshistory/expandedhistory",
                params={"address1": address1, "address2": address2},
                timeout=15,
            )

            if resp.status_code in (400, 404):
                logger.debug(
                    "ATTOM saleshistory: no data for %s (HTTP %d)",
                    address1, resp.status_code,
                )
                return []
            if resp.status_code == 429:
                logger.warning("ATTOM saleshistory: rate-limited (429).")
                return []
            if resp.status_code in (401, 403):
                logger.error("ATTOM saleshistory: auth failed (%d).", resp.status_code)
                return []

            resp.raise_for_status()
            data = resp.json()

            properties = data.get("property", [])
            if not properties:
                return []

            prop = properties[0]
            return self._parse_sale_history(prop)

        except requests.Timeout:
            logger.warning("ATTOM saleshistory: timed out for %s", address1)
            return []
        except requests.RequestException as exc:
            logger.warning("ATTOM saleshistory: request failed for %s: %s", address1, exc)
            return []
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("ATTOM saleshistory: parse error for %s: %s", address1, exc)
            return []

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

    def _parse_sale_history(self, prop: dict) -> list[dict]:
        """Parse a single property object from ``/saleshistory/expandedhistory``.

        Building details live at the **property** level and are shared across
        all sale transactions.  We only return real sales (``saleAmt > 0``),
        filtering out refinances, quit-claims, and stand-alone financing.
        """
        # --- Property-level details (shared by all sales) ---
        building = prop.get("building", {})
        lot = prop.get("lot", {})
        summary = prop.get("summary", {})
        location = prop.get("location", {})

        rooms = building.get("rooms", {})
        beds = _safe_float(rooms.get("beds") or rooms.get("bedrooms"))
        baths = _safe_float(
            rooms.get("bathstotal") or rooms.get("bathsTotal")
        )
        size = building.get("size", {})
        sqft = _safe_int(
            size.get("universalsize") or size.get("universalSize")
            or size.get("livingsize") or size.get("livingSize")
        )
        year_built = _safe_int(
            summary.get("yearbuilt") or summary.get("yearBuilt")
        )
        lot_sqft = _safe_int(lot.get("lotsize2") or lot.get("lotSize2"))
        lot_acres = _safe_float(lot.get("lotsize1") or lot.get("lotSize1"))
        if not lot_sqft and lot_acres and lot_acres > 0:
            lot_sqft = int(lot_acres * 43_560)

        # Property type mapping
        prop_class = summary.get("propclass") or summary.get("propClass") or ""
        prop_subtype = summary.get("propsubtype") or summary.get("propSubType") or ""
        prop_type = summary.get("proptype") or summary.get("propType") or ""
        property_type_raw = summary.get("propertyType") or ""
        property_type = _map_property_type(
            prop_class, prop_subtype, prop_type, property_type_raw
        )

        # Location
        lat = _safe_float(location.get("latitude"))
        lng = _safe_float(location.get("longitude"))

        # --- Per-sale transactions ---
        # ATTOM uses camelCase 'saleHistory' in expanded history responses
        sale_history = prop.get("saleHistory") or prop.get("salehistory") or []
        if not sale_history:
            return []

        results: list[dict] = []
        for txn in sale_history:
            amount = txn.get("amount", {})
            # expanded history uses camelCase 'saleAmt'
            sale_price = _safe_int(
                amount.get("saleAmt") or amount.get("saleamt")
            )
            if not sale_price or sale_price <= 0:
                continue  # skip refinances, quit-claims, etc.

            sale_date_raw = (
                txn.get("saleTransDate")
                or txn.get("saletransdate")
                or ""
            )
            if len(sale_date_raw) < 10:
                continue  # need at least YYYY-MM-DD
            sale_date = sale_date_raw[:10]

            # Sale type description (e.g. "Resale", "New Construction")
            # saleTransType can be at transaction level OR inside amount
            sale_type = (
                txn.get("saleTransType")
                or txn.get("saletranstype")
                or amount.get("saleTransType")
                or amount.get("saletranstype")
                or None
            )

            # Price per sqft
            price_per_sqft: Optional[float] = None
            if sqft and sqft > 0:
                price_per_sqft = round(sale_price / sqft, 2)

            results.append({
                "sale_price": sale_price,
                "sale_date": sale_date,
                "sale_type": sale_type,
                "beds": beds,
                "baths": baths,
                "sqft": sqft,
                "year_built": year_built,
                "lot_size_sqft": lot_sqft,
                "property_type": property_type,
                "latitude": lat,
                "longitude": lng,
                "price_per_sqft": price_per_sqft,
            })

        logger.debug(
            "ATTOM sale history: %d real sales out of %d transactions",
            len(results), len(sale_history),
        )
        return results


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
