"""FastAPI backend for HomeBuyer Tauri app.

Thin wrapper around existing prediction, analysis, and data modules.
Designed to run as a sidecar process spawned by the Tauri shell.

Usage:
    python -m homebuyer.api          # Runs on port 8787
    uvicorn homebuyer.api:app --port 8787
"""

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import json

from fastapi.responses import JSONResponse

from homebuyer.config import DB_PATH, GEO_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class ListingPredictRequest(BaseModel):
    url: str


class ManualPredictRequest(BaseModel):
    neighborhood: str
    zip_code: str = "94702"
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    hoa_per_month: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    property_type: str = "Single Family Residential"
    list_price: Optional[int] = None


class MapClickRequest(BaseModel):
    latitude: float
    longitude: float


class CompsRequest(BaseModel):
    neighborhood: str
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    lookback_months: int = 24
    max_results: int = 10


class PropertyPotentialRequest(BaseModel):
    latitude: float
    longitude: float
    address: Optional[str] = None
    lot_size_sqft: Optional[int] = None
    sqft: Optional[int] = None


class PotentialSummaryRequest(BaseModel):
    latitude: float
    longitude: float
    address: Optional[str] = None
    lot_size_sqft: Optional[int] = None
    sqft: Optional[int] = None
    neighborhood: Optional[str] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    year_built: Optional[int] = None


class ImprovementSimRequest(BaseModel):
    latitude: float
    longitude: float
    address: Optional[str] = None
    neighborhood: Optional[str] = None
    zip_code: Optional[str] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    year_built: Optional[int] = None
    property_type: str = "Single Family Residential"
    hoa_per_month: Optional[int] = None


class RentalAnalysisRequest(BaseModel):
    latitude: float
    longitude: float
    address: Optional[str] = None
    neighborhood: Optional[str] = None
    zip_code: Optional[str] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    year_built: Optional[int] = None
    property_type: str = "Single Family Residential"
    hoa_per_month: Optional[int] = None
    list_price: Optional[int] = None
    down_payment_pct: float = 20.0
    self_managed: bool = True


# ---------------------------------------------------------------------------
# Application state — loaded once at startup, kept warm
# ---------------------------------------------------------------------------


class AppState:
    """Holds long-lived resources: DB connection, ML model, analyzer."""

    def __init__(self) -> None:
        from homebuyer.prediction.model import ModelArtifact
        from homebuyer.storage.database import Database

        logger.info("Loading database from %s", DB_PATH)
        self.db = Database(DB_PATH)
        self.db.connect(check_same_thread=False)
        self.db.initialize_schema()

        logger.info("Loading ML model...")
        try:
            self.model = ModelArtifact.load()
            self.model_loaded = True
            logger.info("Model loaded (trained %s)", self.model.trained_at)
        except FileNotFoundError:
            self.model = None
            self.model_loaded = False
            logger.warning("No trained model found. Prediction endpoints disabled.")

        # Pre-load geospatial classifiers for map-click endpoint
        try:
            from homebuyer.processing.zoning import ZoningClassifier

            self.zoning = ZoningClassifier()
        except Exception:
            self.zoning = None
            logger.warning("Zoning GeoJSON not found. Map-click zoning check disabled.")

        try:
            from homebuyer.processing.geocode import NeighborhoodGeocoder

            self.geocoder = NeighborhoodGeocoder()
        except Exception:
            self.geocoder = None
            logger.warning("Neighborhood boundaries not found. Map-click geocoding disabled.")

        # Development potential calculator
        try:
            from homebuyer.processing.development import DevelopmentPotentialCalculator

            if self.zoning:
                self.dev_calc = DevelopmentPotentialCalculator(self.zoning, self.db)
            else:
                self.dev_calc = None
                logger.warning("Development calculator disabled (no zoning data).")
        except Exception:
            self.dev_calc = None
            logger.warning("Development calculator initialization failed.")

        # ATTOM property data client (optional — auto-fills property details)
        from homebuyer.collectors.attom import AttomClient

        self.attom = AttomClient()

        # AI-powered development potential summarizer (optional)
        from homebuyer.services.ai_summary import PotentialSummarizer

        self.potential_summarizer = PotentialSummarizer()
        if self.potential_summarizer.enabled:
            logger.info("AI potential summarizer enabled (Claude API)")
        else:
            logger.info("AI potential summarizer disabled (no ANTHROPIC_API_KEY)")

        # Rental income & investment analyzer
        from homebuyer.analysis.rental_analysis import RentalAnalyzer

        self.rental_analyzer = RentalAnalyzer(self.db, self.dev_calc)
        logger.info("Rental analyzer initialized")

        # Faketor AI chat advisor
        from homebuyer.services.faketor import FaketorService

        self.faketor = FaketorService()
        if self.faketor.enabled:
            logger.info("Faketor AI advisor enabled (Claude API)")
        else:
            logger.info("Faketor AI advisor disabled (no ANTHROPIC_API_KEY)")

        # In-memory TTL cache for frequently-accessed analytics
        self._ttl_cache: dict[str, tuple[float, object]] = {}

    def get_analyzer(self):
        from homebuyer.analysis.market_analysis import MarketAnalyzer
        return MarketAnalyzer(self.db)

    # ------------------------------------------------------------------
    # In-memory TTL cache for frequently-requested analytics
    # ------------------------------------------------------------------
    _TTL_SECONDS = 3600  # 1 hour default

    def cache_get(self, key: str) -> object | None:
        """Get a value from the in-memory TTL cache, or None if expired/missing."""
        entry = self._ttl_cache.get(key)
        if entry is None:
            return None
        cached_at, value = entry
        if time.time() - cached_at > self._TTL_SECONDS:
            del self._ttl_cache[key]
            return None
        return value

    def cache_set(self, key: str, value: object) -> None:
        """Store a value in the in-memory TTL cache."""
        self._ttl_cache[key] = (time.time(), value)

    def close(self) -> None:
        if self.db:
            self.db.close()


_state: Optional[AppState] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global _state
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("Starting HomeBuyer API server...")
    _state = AppState()
    yield
    logger.info("Shutting down HomeBuyer API server...")
    _state.close()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HomeBuyer API",
    version="0.1.0",
    description="Berkeley home price prediction and market analysis",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_model():
    """Raise 503 if model is not loaded."""
    if not _state or not _state.model_loaded:
        raise HTTPException(
            status_code=503,
            detail="ML model not loaded. Run 'homebuyer train' first.",
        )
    return _state.model


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health():
    """Health check for sidecar readiness."""
    return {
        "status": "ok",
        "model_loaded": _state.model_loaded if _state else False,
    }


@app.get("/api/status")
def status():
    """Database statistics and data freshness."""
    return _state.db.get_statistics()


# --- Prediction ---


@app.post("/api/predict/listing")
def predict_listing(req: ListingPredictRequest):
    """Predict sale price for a Redfin listing URL."""
    model = _require_model()

    from homebuyer.collectors.redfin_listing import ListingFetcher, resolve_neighborhood

    fetcher = ListingFetcher()
    try:
        listing = fetcher.fetch_listing(req.url)
    except (ValueError, ConnectionError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Resolve neighborhood
    if not listing.get("neighborhood"):
        listing["neighborhood"] = resolve_neighborhood(listing, _state.db)

    # Run prediction (with caching)
    result = model.predict_single(_state.db, listing)

    # Store in predictions cache
    if listing.get("latitude") and listing.get("longitude"):
        _state.db.store_prediction(
            latitude=listing["latitude"],
            longitude=listing["longitude"],
            predicted_price=result.predicted_price,
            price_lower=result.price_lower,
            price_upper=result.price_upper,
            neighborhood=result.neighborhood or listing.get("neighborhood"),
            zip_code=listing.get("zip_code"),
            beds=listing.get("beds"),
            baths=listing.get("baths"),
            sqft=listing.get("sqft"),
            year_built=listing.get("year_built"),
            lot_size_sqft=listing.get("lot_size_sqft"),
            property_type=listing.get("property_type"),
            list_price=listing.get("list_price"),
            hoa_per_month=listing.get("hoa_per_month"),
            base_value=result.base_value,
            predicted_premium_pct=result.predicted_premium_pct,
            feature_contributions=result.feature_contributions,
            source="predict",
        )

    # Find comparable sales
    analyzer = _state.get_analyzer()
    comps = analyzer.find_comparables(
        neighborhood=listing.get("neighborhood", ""),
        beds=listing.get("beds"),
        baths=listing.get("baths"),
        sqft=listing.get("sqft"),
        year_built=listing.get("year_built"),
    )

    # Persist ATTOM sale history for this listing address
    # Build a lightweight AttomPropertyDetail from listing for property-only fallback
    from homebuyer.collectors.attom import AttomPropertyDetail as _APD
    _listing_detail = _APD(
        beds=listing.get("beds"),
        baths=listing.get("baths"),
        sqft=listing.get("sqft"),
        year_built=listing.get("year_built"),
        lot_size_sqft=listing.get("lot_size_sqft"),
        property_type=listing.get("property_type"),
    )
    _persist_attom_sales(
        address=listing.get("address", ""),
        city=listing.get("city", "Berkeley"),
        state=listing.get("state", "CA"),
        zip_code=listing.get("zip_code", ""),
        latitude=listing.get("latitude", 0),
        longitude=listing.get("longitude", 0),
        neighborhood=listing.get("neighborhood"),
        attom_detail=_listing_detail,
    )

    # Collect building permits in background (Playwright, ~8-10s)
    listing_addr = listing.get("address", "")
    if listing_addr:
        _collect_permits_background(listing_addr)

    return {
        "listing": listing,
        "prediction": _prediction_to_dict(result),
        "comparables": [_comp_to_dict(c) for c in comps[:7]],
    }


@app.post("/api/predict/manual")
def predict_manual(req: ManualPredictRequest):
    """Predict sale price from manually entered property details."""
    model = _require_model()

    prop = req.model_dump(exclude_none=True)
    result = model.predict_single(_state.db, prop)

    # Store in predictions cache
    if prop.get("latitude") and prop.get("longitude"):
        _state.db.store_prediction(
            latitude=prop["latitude"],
            longitude=prop["longitude"],
            predicted_price=result.predicted_price,
            price_lower=result.price_lower,
            price_upper=result.price_upper,
            neighborhood=result.neighborhood or prop.get("neighborhood"),
            zip_code=prop.get("zip_code"),
            beds=prop.get("beds"),
            baths=prop.get("baths"),
            sqft=prop.get("sqft"),
            year_built=prop.get("year_built"),
            lot_size_sqft=prop.get("lot_size_sqft"),
            property_type=prop.get("property_type"),
            list_price=prop.get("list_price"),
            hoa_per_month=prop.get("hoa_per_month"),
            base_value=result.base_value,
            predicted_premium_pct=result.predicted_premium_pct,
            feature_contributions=result.feature_contributions,
            source="manual",
        )

    return {
        "prediction": _prediction_to_dict(result),
    }


@app.post("/api/predict/map-click")
def predict_map_click(req: MapClickRequest):
    """Predict sale price for a map-clicked location in Berkeley.

    Validates the location is within Berkeley and in a residential zone,
    then tries to find an existing property in the database nearby.
    If found, runs the full prediction; otherwise returns location metadata
    so the frontend can show a manual-entry form.
    """
    model = _require_model()

    # Step 1: Neighborhood lookup
    if not _state.geocoder:
        raise HTTPException(
            status_code=503,
            detail="Neighborhood geocoder not available.",
        )
    neighborhood = _state.geocoder.geocode_point(req.latitude, req.longitude)
    if not neighborhood:
        # Point may be in a gap between neighborhood polygons — try nearest
        neighborhood = _state.geocoder.geocode_nearest(req.latitude, req.longitude)

    # Step 1b: "In Berkeley?" check — use ATTOM city as fallback when
    # neighborhood polygons have gaps
    if not neighborhood and _state.attom and _state.attom.enabled:
        attom_check = _state.attom.lookup_property_by_coords(
            latitude=req.latitude, longitude=req.longitude, radius_m=50,
        )
        if attom_check and attom_check.resolved_city:
            if attom_check.resolved_city.upper() == "BERKELEY":
                # We're in Berkeley but outside known neighborhood polygons
                neighborhood = "Berkeley"
                logger.info(
                    "ATTOM confirmed Berkeley via city field (no polygon match)"
                )
    if not neighborhood:
        return {
            "status": "error",
            "error": "This location is not within Berkeley city boundaries.",
            "error_code": "not_in_berkeley",
        }

    # Step 2: Zoning check — must be residential (R-*)
    zone_class = None
    if _state.zoning:
        zone_class = _state.zoning.classify_point(req.latitude, req.longitude)

    # Allow residential zones (R-*), mixed-use residential (MUR, MRD, R-SMU, R-BMU),
    # and ES-R (Environmental Safety Residential)
    _RESIDENTIAL_PREFIXES = ("R", "ES-R", "MUR", "MRD")
    if zone_class and not zone_class.upper().startswith(_RESIDENTIAL_PREFIXES):
        zone_desc = _ZONE_DESCRIPTIONS.get(zone_class, zone_class)
        return {
            "status": "error",
            "error": f"This location is zoned {zone_class} ({zone_desc}). Please select a residential area.",
            "error_code": "not_residential",
        }

    # Step 3: Estimate zip code from nearby sales
    zip_code = _estimate_zip_from_coords(req.latitude, req.longitude)

    # Step 4: Try to find an existing property sale near the clicked point
    nearest = _state.db.find_nearest_sale(req.latitude, req.longitude, max_distance_m=5)

    if nearest:
        prop = dict(nearest)
        prop["neighborhood"] = neighborhood  # ensure current geocoded neighborhood

        # If the DB record is missing key property details, try ATTOM to fill gaps
        _key_fields = ("beds", "baths", "sqft", "property_type")
        if any(prop.get(f) is None for f in _key_fields):
            if _state.attom and _state.attom.enabled:
                _enrich_detail = None
                address = prop.get("address")
                zip_code_val = prop.get("zip_code") or zip_code
                if address:
                    _enrich_detail = _state.attom.lookup_property(
                        address1=address,
                        address2=f"Berkeley, CA {zip_code_val}",
                    )
                if not _enrich_detail:
                    _enrich_detail = _state.attom.lookup_property_by_coords(
                        latitude=req.latitude,
                        longitude=req.longitude,
                        radius_m=5,
                    )
                if _enrich_detail:
                    enriched = _enrich_detail.to_dict()
                    for field in ("beds", "baths", "sqft", "lot_size_sqft",
                                  "year_built", "property_type"):
                        if prop.get(field) is None and enriched.get(field) is not None:
                            prop[field] = enriched[field]
                    logger.info(
                        "Enriched DB record for %s with ATTOM data: %s",
                        address, list(enriched.keys()),
                    )

        result = model.predict_single(_state.db, prop)

        # Store in predictions cache
        _state.db.store_prediction(
            latitude=prop.get("latitude", req.latitude),
            longitude=prop.get("longitude", req.longitude),
            predicted_price=result.predicted_price,
            price_lower=result.price_lower,
            price_upper=result.price_upper,
            neighborhood=result.neighborhood or neighborhood,
            zip_code=prop.get("zip_code") or zip_code,
            beds=prop.get("beds"),
            baths=prop.get("baths"),
            sqft=prop.get("sqft"),
            year_built=prop.get("year_built"),
            lot_size_sqft=prop.get("lot_size_sqft"),
            property_type=prop.get("property_type"),
            list_price=prop.get("list_price"),
            base_value=result.base_value,
            predicted_premium_pct=result.predicted_premium_pct,
            feature_contributions=result.feature_contributions,
            source="map-click",
        )

        analyzer = _state.get_analyzer()
        comps = analyzer.find_comparables(
            neighborhood=neighborhood,
            beds=prop.get("beds"),
            baths=prop.get("baths"),
            sqft=prop.get("sqft"),
            year_built=prop.get("year_built"),
        )

        return {
            "status": "prediction",
            "listing": _sale_to_listing(prop, neighborhood),
            "prediction": _prediction_to_dict(result),
            "comparables": [_comp_to_dict(c) for c in comps[:7]],
        }

    # Step 5: Try ATTOM coords-based property lookup first (most reliable)
    address = None
    attom_detail = None
    last_sale_price, last_sale_date = None, None

    if _state.attom and _state.attom.enabled:
        attom_detail = _state.attom.lookup_property_by_coords(
            latitude=req.latitude,
            longitude=req.longitude,
            radius_m=5,
        )
        if attom_detail and attom_detail.resolved_address:
            address = attom_detail.resolved_address
            logger.info("ATTOM coords lookup resolved address: %s", address)

            # Fetch last sale using the resolved address
            last_sale_price, last_sale_date = _state.attom.lookup_last_sale(
                address1=address,
                address2=f"Berkeley, CA {zip_code}",
            )

    # Step 5a: Fall back to Nominatim reverse geocode if ATTOM didn't resolve
    if not address:
        address = _reverse_geocode(req.latitude, req.longitude)

    # Step 5b: If we have an address but no ATTOM detail yet, try address-based lookup
    if address and not attom_detail and _state.attom and _state.attom.enabled:
        attom_detail = _state.attom.lookup_property(
            address1=address,
            address2=f"Berkeley, CA {zip_code}",
        )
        last_sale_price, last_sale_date = _state.attom.lookup_last_sale(
            address1=address,
            address2=f"Berkeley, CA {zip_code}",
        )

    # Step 5c: If ATTOM returned complete data, run prediction immediately
    if attom_detail and attom_detail.is_complete:
        prop = attom_detail.to_dict()
        prop["neighborhood"] = neighborhood
        prop["zip_code"] = zip_code
        prop["latitude"] = req.latitude
        prop["longitude"] = req.longitude
        prop["address"] = address

        result = model.predict_single(_state.db, prop)

        # Store in predictions cache
        _state.db.store_prediction(
            latitude=req.latitude,
            longitude=req.longitude,
            predicted_price=result.predicted_price,
            price_lower=result.price_lower,
            price_upper=result.price_upper,
            neighborhood=result.neighborhood or neighborhood,
            zip_code=zip_code,
            beds=prop.get("beds"),
            baths=prop.get("baths"),
            sqft=prop.get("sqft"),
            year_built=prop.get("year_built"),
            lot_size_sqft=prop.get("lot_size_sqft"),
            property_type=prop.get("property_type"),
            list_price=prop.get("list_price"),
            base_value=result.base_value,
            predicted_premium_pct=result.predicted_premium_pct,
            feature_contributions=result.feature_contributions,
            source="map-click",
        )

        analyzer = _state.get_analyzer()
        comps = analyzer.find_comparables(
            neighborhood=neighborhood,
            beds=prop.get("beds"),
            baths=prop.get("baths"),
            sqft=prop.get("sqft"),
            year_built=prop.get("year_built"),
        )

        # Persist ATTOM sale history for future predictions & model training
        _persist_attom_sales(
            address=address,
            city="Berkeley",
            state="CA",
            zip_code=zip_code,
            latitude=req.latitude,
            longitude=req.longitude,
            neighborhood=neighborhood,
            attom_detail=attom_detail,
        )

        # Collect building permits in background (Playwright, ~8-10s)
        if address:
            _collect_permits_background(address)

        return {
            "status": "prediction",
            "listing": _attom_to_listing(
                prop, neighborhood, zone_class,
                last_sale_price=last_sale_price,
                last_sale_date=last_sale_date,
            ),
            "prediction": _prediction_to_dict(result),
            "comparables": [_comp_to_dict(c) for c in comps[:7]],
        }

    # Step 6: Return location info so frontend can show the manual entry form
    location_info: dict = {
        "latitude": req.latitude,
        "longitude": req.longitude,
        "neighborhood": neighborhood,
        "zip_code": zip_code,
        "zoning_class": zone_class,
        "address": address,
    }

    # Enrich with partial ATTOM data for form pre-fill
    if attom_detail:
        location_info["attom_prefill"] = attom_detail.to_dict()

    return {
        "status": "needs_details",
        "location_info": location_info,
    }


# --- Neighborhoods ---


@app.get("/api/neighborhoods")
def neighborhoods(
    min_sales: int = Query(5, ge=1),
    years: int = Query(2, ge=1, le=10),
):
    """Rank all neighborhoods by median price."""
    analyzer = _state.get_analyzer()
    rankings = analyzer.get_all_neighborhood_rankings(
        lookback_years=years, min_sales=min_sales,
    )
    return [_neighborhood_stats_to_dict(s) for s in rankings]


@app.get("/api/neighborhoods/geojson")
def neighborhoods_geojson():
    """Serve Berkeley neighborhood boundary polygons as GeoJSON."""
    geojson_path = GEO_DIR / "berkeley_neighborhoods.geojson"
    if not geojson_path.exists():
        raise HTTPException(status_code=404, detail="GeoJSON file not found")
    with open(geojson_path) as f:
        data = json.load(f)
    return JSONResponse(content=data)


@app.get("/api/neighborhoods/{name}")
def neighborhood_detail(
    name: str,
    years: int = Query(2, ge=1, le=10),
):
    """Detailed stats for a specific neighborhood."""
    analyzer = _state.get_analyzer()
    stats = analyzer.get_neighborhood_stats(name, lookback_years=years)
    if stats.sale_count == 0:
        raise HTTPException(status_code=404, detail=f"No sales found for '{name}'.")
    return _neighborhood_stats_to_dict(stats)


# --- Market ---


@app.get("/api/market/trend")
def market_trend(months: int = Query(24, ge=1, le=120)):
    """Monthly market trend data."""
    analyzer = _state.get_analyzer()
    trend = analyzer.get_market_trend(months=months)
    return [asdict(s) for s in trend]


@app.get("/api/market/summary")
def market_summary():
    """Comprehensive market summary report."""
    analyzer = _state.get_analyzer()
    return analyzer.generate_summary_report()


# --- Model ---


@app.get("/api/model/info")
def model_info():
    """Model metadata, metrics, and feature importances."""
    model = _require_model()
    analyzer = _state.get_analyzer()
    return {
        "trained_at": model.trained_at.isoformat(),
        "data_cutoff_date": model.data_cutoff_date,
        "train_size": model.train_size,
        "test_size": model.test_size,
        "feature_count": len(model.feature_names),
        "feature_names": model.feature_names,
        "metrics": model.training_metrics,
        "hyperparameters": model.hyperparameters,
        "feature_importances": model.feature_importances,
        "neighborhood_metrics": model.neighborhood_metrics,
        "data_completeness": analyzer.get_data_completeness(),
    }


# --- Affordability ---


@app.get("/api/afford/{budget}")
def affordability(
    budget: int,
    down_pct: float = Query(20.0, ge=0, le=100),
    hoa: int = Query(0, ge=0),
):
    """Affordability analysis for a given monthly budget."""
    analyzer = _state.get_analyzer()
    return analyzer.assess_affordability(
        monthly_budget=budget,
        down_payment_pct=down_pct,
        hoa_monthly=hoa,
    )


# --- Development Potential ---


@app.post("/api/property/potential")
def property_potential(req: PropertyPotentialRequest):
    """Compute development potential for a Berkeley property.

    Returns zoning details, unit potential (base + Middle Housing),
    ADU feasibility, SB 9 eligibility, BESO status, and improvement ROI.
    """
    if not _state or not _state.dev_calc:
        raise HTTPException(
            status_code=503,
            detail="Development potential calculator not available.",
        )

    # Try to enrich from DB if address is provided but lot_size/sqft missing
    lot_size = req.lot_size_sqft
    sqft = req.sqft
    address = req.address

    if (lot_size is None or sqft is None) and _state.db:
        nearest = _state.db.find_nearest_sale(req.latitude, req.longitude, max_distance_m=50)
        if nearest:
            if lot_size is None:
                lot_size = nearest.get("lot_size_sqft")
            if sqft is None:
                sqft = nearest.get("sqft")
            if address is None:
                address = nearest.get("address")

    result = _state.dev_calc.compute(
        lat=req.latitude,
        lon=req.longitude,
        lot_size_sqft=lot_size,
        sqft=sqft,
        address=address,
    )

    return _development_potential_to_dict(result)


@app.post("/api/property/potential/summary")
def property_potential_summary(req: PotentialSummaryRequest):
    """Compute development potential AND generate an AI summary.

    Returns the full potential data plus a Claude-generated summary
    with recommendation, caveats, and highlights. Results are cached
    for 24 hours per location.
    """
    if not _state or not _state.dev_calc:
        raise HTTPException(
            status_code=503,
            detail="Development potential calculator not available.",
        )

    # Reuse existing logic to enrich missing fields from DB
    lot_size = req.lot_size_sqft
    sqft = req.sqft
    address = req.address

    if (lot_size is None or sqft is None) and _state.db:
        nearest = _state.db.find_nearest_sale(req.latitude, req.longitude, max_distance_m=50)
        if nearest:
            if lot_size is None:
                lot_size = nearest.get("lot_size_sqft")
            if sqft is None:
                sqft = nearest.get("sqft")
            if address is None:
                address = nearest.get("address")

    result = _state.dev_calc.compute(
        lat=req.latitude,
        lon=req.longitude,
        lot_size_sqft=lot_size,
        sqft=sqft,
        address=address,
    )

    potential_dict = _development_potential_to_dict(result)

    # Build property context for the AI prompt
    property_context = {
        "address": address or req.address,
        "neighborhood": req.neighborhood,
        "lot_size_sqft": lot_size,
        "sqft": sqft,
        "beds": req.beds,
        "baths": req.baths,
        "year_built": req.year_built,
    }

    # Generate AI summary (cached internally)
    summary_resp = _state.potential_summarizer.generate_summary(
        potential_dict=potential_dict,
        property_context=property_context,
        lat=req.latitude,
        lon=req.longitude,
    )

    resp: dict = {"potential": summary_resp.potential}

    if summary_resp.ai_summary:
        resp["ai_summary"] = {
            "summary": summary_resp.ai_summary.summary,
            "recommendation": summary_resp.ai_summary.recommendation,
            "caveats": summary_resp.ai_summary.caveats,
            "highlights": summary_resp.ai_summary.highlights,
        }
    else:
        resp["ai_summary"] = None

    if summary_resp.ai_error:
        resp["ai_error"] = summary_resp.ai_error

    return resp


@app.post("/api/property/improvement-sim")
def improvement_simulation(req: ImprovementSimRequest):
    """Simulate the effect of home improvements on predicted price.

    Uses the ML model to predict current price, then simulates how modifying
    permit-related features affects the prediction. Also returns market-wide
    cost data per improvement category from Berkeley building permits.
    """
    model = _require_model()

    if not _state or not _state.dev_calc:
        raise HTTPException(
            status_code=503,
            detail="Development potential calculator not available.",
        )

    # Resolve property details from DB if needed
    neighborhood = req.neighborhood
    zip_code = req.zip_code or "94702"
    sqft = req.sqft
    lot_size_sqft = req.lot_size_sqft
    address = req.address

    if _state.db:
        nearest = _state.db.find_nearest_sale(req.latitude, req.longitude, max_distance_m=50)
        if nearest:
            if not neighborhood:
                neighborhood = nearest.get("neighborhood")
            if sqft is None:
                sqft = nearest.get("sqft")
            if lot_size_sqft is None:
                lot_size_sqft = nearest.get("lot_size_sqft")
            if not address:
                address = nearest.get("address")
            if not req.zip_code:
                zip_code = nearest.get("zip_code") or zip_code

    if not neighborhood:
        if _state.geocoder:
            neighborhood = _state.geocoder.geocode_point(req.latitude, req.longitude)
            if not neighborhood:
                neighborhood = _state.geocoder.geocode_nearest(req.latitude, req.longitude)
        if not neighborhood:
            neighborhood = "Berkeley"

    # Build property dict for the ML model
    prop = {
        "latitude": req.latitude,
        "longitude": req.longitude,
        "neighborhood": neighborhood,
        "zip_code": zip_code,
        "beds": req.beds,
        "baths": req.baths,
        "sqft": sqft,
        "lot_size_sqft": lot_size_sqft,
        "year_built": req.year_built,
        "property_type": req.property_type,
        "hoa_per_month": req.hoa_per_month,
        "address": address,
    }

    # Get improvement cost data from permits DB
    roi_data = _state.dev_calc._compute_improvement_roi()

    # Build improvement list with average costs from permit data
    improvements = []
    for roi in roi_data:
        improvements.append({
            "category": roi.category,
            "estimated_cost": roi.avg_job_value,
        })

    if not improvements:
        return {
            "error": "No improvement data available (building permits not collected).",
            "categories": [],
            "simulation": None,
        }

    # Run ML simulation
    try:
        sim_result = model.simulate_improvements(_state.db, prop, improvements)
    except Exception as e:
        logger.warning("Improvement simulation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Simulation failed: {e}")

    # Merge ROI correlation data with ML simulation data
    categories = []
    roi_by_cat = {r.category: r for r in roi_data}

    for ind in sim_result["individual"]:
        cat_name = ind["category"]
        roi = roi_by_cat.get(cat_name)
        categories.append({
            "category": cat_name,
            "avg_permit_cost": ind["estimated_cost"],
            "ml_predicted_delta": ind["predicted_delta"],
            "ml_roi_ratio": ind["roi_ratio"],
            "correlation_premium_pct": roi.avg_ppsf_premium_pct if roi else None,
            "sample_count": roi.sample_count if roi else 0,
        })

    # Sort by ml_predicted_delta descending (best improvements first)
    categories.sort(key=lambda c: c["ml_predicted_delta"], reverse=True)

    return {
        "current_price": sim_result["current_price"],
        "improved_price": sim_result["improved_price"],
        "total_delta": sim_result["total_delta"],
        "total_cost": sim_result["total_cost"],
        "roi_ratio": sim_result["roi_ratio"],
        "categories": categories,
    }


# --- Rental Income & Investment Analysis ---


@app.post("/api/property/rental-analysis")
def rental_analysis(req: RentalAnalysisRequest):
    """Run comprehensive rental income and investment scenario analysis.

    Compares multiple strategies: rent as-is, add ADU, SB9 lot split,
    and multi-unit development. Returns cash flow projections, mortgage
    analysis, tax benefits, and key investment metrics for each scenario.
    """
    if not _state:
        raise HTTPException(status_code=503, detail="Server not ready.")

    # Resolve property details from DB (same pattern as improvement_simulation)
    neighborhood = req.neighborhood
    zip_code = req.zip_code or "94702"
    sqft = req.sqft
    lot_size_sqft = req.lot_size_sqft
    address = req.address
    beds = req.beds
    baths = req.baths
    year_built = req.year_built

    if _state.db:
        nearest = _state.db.find_nearest_sale(req.latitude, req.longitude, max_distance_m=50)
        if nearest:
            if not neighborhood:
                neighborhood = nearest.get("neighborhood")
            if sqft is None:
                sqft = nearest.get("sqft")
            if lot_size_sqft is None:
                lot_size_sqft = nearest.get("lot_size_sqft")
            if not address:
                address = nearest.get("address")
            if beds is None:
                beds = nearest.get("beds")
            if baths is None:
                baths = nearest.get("baths")
            if year_built is None:
                year_built = nearest.get("year_built")
            if not req.zip_code:
                zip_code = nearest.get("zip_code") or zip_code

    if not neighborhood:
        if _state.geocoder:
            neighborhood = _state.geocoder.geocode_point(req.latitude, req.longitude)
            if not neighborhood:
                neighborhood = _state.geocoder.geocode_nearest(req.latitude, req.longitude)
        if not neighborhood:
            neighborhood = "Berkeley"

    prop = {
        "latitude": req.latitude,
        "longitude": req.longitude,
        "neighborhood": neighborhood,
        "zip_code": zip_code,
        "beds": beds,
        "baths": baths,
        "sqft": sqft,
        "lot_size_sqft": lot_size_sqft,
        "year_built": year_built,
        "property_type": req.property_type,
        "hoa_per_month": req.hoa_per_month,
        "address": address,
        "list_price": req.list_price,
    }

    from homebuyer.analysis.rental_analysis import rental_analysis_to_dict

    result = _state.rental_analyzer.analyze(
        prop,
        down_payment_pct=req.down_payment_pct,
        self_managed=req.self_managed,
    )
    return rental_analysis_to_dict(result)


@app.post("/api/property/rent-estimate")
def rent_estimate(req: RentalAnalysisRequest):
    """Quick single-unit rent estimate for a property."""
    if not _state:
        raise HTTPException(status_code=503, detail="Server not ready.")

    # Resolve neighborhood
    neighborhood = req.neighborhood
    if not neighborhood and _state.db:
        nearest = _state.db.find_nearest_sale(req.latitude, req.longitude, max_distance_m=50)
        if nearest:
            neighborhood = nearest.get("neighborhood")
    if not neighborhood and _state.geocoder:
        neighborhood = _state.geocoder.geocode_point(req.latitude, req.longitude)

    beds = int(req.beds or 3)
    baths = float(req.baths or 2.0)
    sqft = req.sqft

    rent = _state.rental_analyzer.estimate_rent(
        beds=beds,
        baths=baths,
        sqft=sqft,
        neighborhood=neighborhood,
        property_value=req.list_price,
    )

    from homebuyer.analysis.rental_analysis import _rent_to_dict

    return _rent_to_dict(rent)


# --- Faketor Chat ---


class FaketorChatRequest(BaseModel):
    latitude: float
    longitude: float
    message: str
    history: list[dict] = []
    address: Optional[str] = None
    neighborhood: Optional[str] = None
    zip_code: Optional[str] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    year_built: Optional[int] = None
    property_type: Optional[str] = "Single Family Residential"


def _faketor_tool_executor(tool_name: str, tool_input: dict) -> str:
    """Execute a Faketor tool and return JSON string result."""

    if tool_name == "get_development_potential":
        if not _state or not _state.dev_calc:
            return json.dumps({"error": "Development calculator not available"})
        lat = tool_input["latitude"]
        lon = tool_input["longitude"]
        lot_size, sqft, address = None, None, tool_input.get("address")
        if _state.db:
            nearest = _state.db.find_nearest_sale(lat, lon, max_distance_m=50)
            if nearest:
                lot_size = nearest.get("lot_size_sqft")
                sqft = nearest.get("sqft")
                if not address:
                    address = nearest.get("address")
        result = _state.dev_calc.compute(lat=lat, lon=lon,
                                          lot_size_sqft=lot_size, sqft=sqft,
                                          address=address)
        return json.dumps(_development_potential_to_dict(result), default=str)

    elif tool_name == "get_improvement_simulation":
        model = _require_model()
        if not _state or not _state.dev_calc:
            return json.dumps({"error": "Development calculator not available"})
        lat = tool_input["latitude"]
        lon = tool_input["longitude"]
        neighborhood = tool_input.get("neighborhood")
        sqft = tool_input.get("sqft")
        lot_size = tool_input.get("lot_size_sqft")
        address = tool_input.get("address")
        if _state.db:
            nearest = _state.db.find_nearest_sale(lat, lon, max_distance_m=50)
            if nearest:
                if not neighborhood:
                    neighborhood = nearest.get("neighborhood")
                if sqft is None:
                    sqft = nearest.get("sqft")
                if lot_size is None:
                    lot_size = nearest.get("lot_size_sqft")
        if not neighborhood and _state.geocoder:
            neighborhood = _state.geocoder.geocode_point(lat, lon) or "Berkeley"
        prop = {
            "latitude": lat, "longitude": lon,
            "neighborhood": neighborhood or "Berkeley",
            "zip_code": tool_input.get("zip_code", "94702"),
            "beds": tool_input.get("beds"), "baths": tool_input.get("baths"),
            "sqft": sqft, "lot_size_sqft": lot_size,
            "year_built": tool_input.get("year_built"),
            "property_type": tool_input.get("property_type", "Single Family Residential"),
            "address": address,
        }
        roi_data = _state.dev_calc._compute_improvement_roi()
        improvements = [{"category": r.category, "estimated_cost": r.avg_job_value}
                        for r in roi_data]
        if not improvements:
            return json.dumps({"error": "No improvement data available"})
        sim = model.simulate_improvements(_state.db, prop, improvements)
        roi_by_cat = {r.category: r for r in roi_data}
        categories = []
        for ind in sim["individual"]:
            roi = roi_by_cat.get(ind["category"])
            categories.append({
                "category": ind["category"],
                "avg_cost": ind["estimated_cost"],
                "ml_delta": ind["predicted_delta"],
                "roi": ind["roi_ratio"],
                "market_premium_pct": roi.avg_ppsf_premium_pct if roi else None,
            })
        return json.dumps({
            "current_price": sim["current_price"],
            "improved_price": sim["improved_price"],
            "total_delta": sim["total_delta"],
            "total_cost": sim["total_cost"],
            "roi": sim["roi_ratio"],
            "categories": categories,
        })

    elif tool_name == "get_comparable_sales":
        analyzer = _state.get_analyzer()
        comps = analyzer.find_comparables(
            neighborhood=tool_input["neighborhood"],
            beds=tool_input.get("beds"),
            baths=tool_input.get("baths"),
            sqft=tool_input.get("sqft"),
            year_built=tool_input.get("year_built"),
        )
        return json.dumps([_comp_to_dict(c) for c in comps[:7]], default=str)

    elif tool_name == "get_neighborhood_stats":
        neighborhood = tool_input["neighborhood"]
        years = tool_input.get("years", 2)
        cache_key = f"neighborhood_stats:{neighborhood}:{years}"
        cached = _state.cache_get(cache_key)
        if cached:
            logger.info("TTL cache HIT for %s", cache_key)
            return json.dumps(cached, default=str)
        analyzer = _state.get_analyzer()
        from dataclasses import asdict
        stats = analyzer.get_neighborhood_stats(neighborhood, lookback_years=years)
        result_dict = _neighborhood_stats_to_dict(stats)
        _state.cache_set(cache_key, result_dict)
        logger.info("TTL cache MISS for %s — stored", cache_key)
        return json.dumps(result_dict, default=str)

    elif tool_name == "get_market_summary":
        cache_key = "market_summary"
        cached = _state.cache_get(cache_key)
        if cached:
            logger.info("TTL cache HIT for %s", cache_key)
            return json.dumps(cached, default=str)
        analyzer = _state.get_analyzer()
        result_dict = analyzer.generate_summary_report()
        _state.cache_set(cache_key, result_dict)
        logger.info("TTL cache MISS for %s — stored", cache_key)
        return json.dumps(result_dict, default=str)

    elif tool_name == "get_price_prediction":
        return json.dumps(
            _get_or_compute_prediction(tool_input, source="chat"),
            default=str,
        )

    elif tool_name == "estimate_sell_vs_hold":
        analyzer = _state.get_analyzer()
        # Reuse cached prediction
        pred_dict = _get_or_compute_prediction(tool_input, source="chat")
        current_value = pred_dict["predicted_price"]

        # Get neighborhood YoY appreciation
        neighborhood = tool_input.get("neighborhood", "Berkeley")
        stats = analyzer.get_neighborhood_stats(neighborhood, lookback_years=2)
        yoy_pct = stats.yoy_price_change_pct or 3.0  # default 3% if unknown

        # Get current market conditions
        market = analyzer.generate_summary_report()
        mortgage_rate = None
        if market and market.get("current_market"):
            mortgage_rate = market["current_market"].get("mortgage_rate_30yr")

        # Project future values
        scenarios = {}
        for years in [1, 3, 5]:
            appreciation = (1 + yoy_pct / 100) ** years
            projected = int(round(current_value * appreciation, -3))
            gain = projected - current_value
            # Rough selling costs: 5% agent fees + 1% closing
            sell_costs = int(round(projected * 0.06, -3))
            net_gain = gain - sell_costs
            scenarios[f"{years}yr"] = {
                "projected_value": projected,
                "appreciation_pct": round((appreciation - 1) * 100, 1),
                "gross_gain": gain,
                "estimated_sell_costs": sell_costs,
                "net_gain": net_gain,
            }

        # Use RentalAnalyzer for data-driven rent estimate
        beds = int(tool_input.get("beds") or 3)
        rent_est = _state.rental_analyzer.estimate_rent(
            beds=beds,
            baths=float(tool_input.get("baths") or 2.0),
            sqft=tool_input.get("sqft"),
            neighborhood=neighborhood,
            property_value=current_value,
        )
        expenses = _state.rental_analyzer.calculate_expenses(
            current_value, rent_est.annual_rent,
        )
        noi = rent_est.annual_rent - expenses.total_annual
        cap_rate = round(noi / current_value * 100, 2) if current_value > 0 else 0
        price_to_rent = round(current_value / rent_est.annual_rent, 1) if rent_est.annual_rent > 0 else 0

        return json.dumps({
            "current_predicted_value": current_value,
            "confidence_range": [pred_dict["price_lower"], pred_dict["price_upper"]],
            "neighborhood": neighborhood,
            "yoy_appreciation_pct": yoy_pct,
            "mortgage_rate_30yr": mortgage_rate,
            "hold_scenarios": scenarios,
            "rental_estimate": {
                "monthly_rent": rent_est.monthly_rent,
                "annual_gross_rent": rent_est.annual_rent,
                "annual_net_rent": noi,
                "cap_rate_pct": cap_rate,
                "price_to_rent_ratio": price_to_rent,
                "expense_ratio_pct": expenses.expense_ratio_pct,
                "estimation_method": rent_est.estimation_method,
                "note": rent_est.notes,
            },
        }, default=str)

    elif tool_name == "estimate_rental_income":
        prop = {
            "latitude": tool_input["latitude"],
            "longitude": tool_input["longitude"],
            "neighborhood": tool_input.get("neighborhood"),
            "beds": tool_input.get("beds"),
            "baths": tool_input.get("baths"),
            "sqft": tool_input.get("sqft"),
            "year_built": tool_input.get("year_built"),
            "lot_size_sqft": tool_input.get("lot_size_sqft"),
            "property_type": tool_input.get("property_type", "Single Family Residential"),
        }
        scenario = _state.rental_analyzer.build_scenario_as_is(
            prop,
            down_payment_pct=tool_input.get("down_payment_pct", 20.0),
        )
        from homebuyer.analysis.rental_analysis import _scenario_to_dict
        return json.dumps(_scenario_to_dict(scenario), default=str)

    elif tool_name == "analyze_investment_scenarios":
        prop = {
            "latitude": tool_input["latitude"],
            "longitude": tool_input["longitude"],
            "neighborhood": tool_input.get("neighborhood"),
            "beds": tool_input.get("beds"),
            "baths": tool_input.get("baths"),
            "sqft": tool_input.get("sqft"),
            "year_built": tool_input.get("year_built"),
            "lot_size_sqft": tool_input.get("lot_size_sqft"),
            "property_type": tool_input.get("property_type", "Single Family Residential"),
        }
        from homebuyer.analysis.rental_analysis import rental_analysis_to_dict
        result = _state.rental_analyzer.analyze(
            prop,
            down_payment_pct=tool_input.get("down_payment_pct", 20.0),
            self_managed=tool_input.get("self_managed", True),
        )
        return json.dumps(rental_analysis_to_dict(result), default=str)

    elif tool_name == "lookup_property":
        if not _state or not _state.db:
            return json.dumps({"error": "Database not available"})
        address_query = tool_input.get("address", "")
        results = _state.db.search_properties(address_query, limit=3)
        if not results:
            return json.dumps({"error": f"No properties found matching '{address_query}'"})
        # Return the best match with all details
        best = results[0]
        return json.dumps({
            "id": best.get("id"),
            "address": best.get("address"),
            "apn": best.get("apn"),
            "latitude": best.get("latitude"),
            "longitude": best.get("longitude"),
            "neighborhood": best.get("neighborhood"),
            "zip_code": best.get("zip_code"),
            "zoning_class": best.get("zoning_class"),
            "lot_size_sqft": best.get("lot_size_sqft"),
            "building_sqft": best.get("building_sqft"),
            "beds": best.get("beds"),
            "baths": best.get("baths"),
            "sqft": best.get("sqft"),
            "year_built": best.get("year_built"),
            "property_type": best.get("property_type"),
            "use_description": best.get("use_description"),
            "last_sale_price": best.get("last_sale_price"),
            "last_sale_date": best.get("last_sale_date"),
            "attom_enriched": bool(best.get("attom_enriched")),
        }, default=str)

    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})


@app.post("/api/faketor/chat")
def faketor_chat(req: FaketorChatRequest):
    """Chat with Faketor, the AI real estate advisor.

    Faketor uses Claude with tool-use to call development potential,
    improvement simulation, comps, market, and sell-vs-hold analysis tools.
    """
    if not _state:
        raise HTTPException(status_code=503, detail="Server not initialized")

    # Resolve property context from DB if needed
    neighborhood = req.neighborhood
    sqft = req.sqft
    lot_size = req.lot_size_sqft
    beds = req.beds
    baths = req.baths
    year_built = req.year_built
    address = req.address
    zip_code = req.zip_code

    if _state.db:
        nearest = _state.db.find_nearest_sale(req.latitude, req.longitude, max_distance_m=50)
        if nearest:
            if not neighborhood:
                neighborhood = nearest.get("neighborhood")
            if sqft is None:
                sqft = nearest.get("sqft")
            if lot_size is None:
                lot_size = nearest.get("lot_size_sqft")
            if beds is None:
                beds = nearest.get("beds")
            if baths is None:
                baths = nearest.get("baths")
            if year_built is None:
                year_built = nearest.get("year_built")
            if not address:
                address = nearest.get("address")
            if not zip_code:
                zip_code = nearest.get("zip_code")

    if not neighborhood and _state.geocoder:
        neighborhood = _state.geocoder.geocode_point(req.latitude, req.longitude)
        if not neighborhood:
            neighborhood = _state.geocoder.geocode_nearest(req.latitude, req.longitude)
    if not neighborhood:
        neighborhood = "Berkeley"

    property_context = {
        "latitude": req.latitude,
        "longitude": req.longitude,
        "address": address or req.address,
        "neighborhood": neighborhood,
        "zip_code": zip_code or "94702",
        "beds": beds,
        "baths": baths,
        "sqft": sqft,
        "lot_size_sqft": lot_size,
        "year_built": year_built,
        "property_type": req.property_type,
    }

    result = _state.faketor.chat(
        message=req.message,
        history=req.history,
        property_context=property_context,
        tool_executor=_faketor_tool_executor,
    )

    return result


# --- Comparables ---


@app.post("/api/comps")
def comparables(req: CompsRequest):
    """Find comparable recent sales."""
    analyzer = _state.get_analyzer()
    comps = analyzer.find_comparables(
        neighborhood=req.neighborhood,
        beds=req.beds,
        baths=req.baths,
        sqft=req.sqft,
        year_built=req.year_built,
        lookback_months=req.lookback_months,
        max_results=req.max_results,
    )
    return [_comp_to_dict(c) for c in comps]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _comp_to_dict(comp) -> dict:
    """Convert ComparableProperty to JSON-serializable dict."""
    return {
        "address": comp.address,
        "sale_date": comp.sale_date.isoformat(),
        "sale_price": comp.sale_price,
        "beds": comp.beds,
        "baths": comp.baths,
        "sqft": comp.sqft,
        "lot_size_sqft": comp.lot_size_sqft,
        "year_built": comp.year_built,
        "neighborhood": comp.neighborhood,
        "price_per_sqft": comp.price_per_sqft,
        "distance_score": comp.distance_score,
        "latitude": comp.latitude,
        "longitude": comp.longitude,
    }


def _get_or_compute_prediction(tool_input: dict, source: str = "chat") -> dict:
    """Get a cached prediction or compute a fresh one and store it.

    Checks the predictions table for a recent cached result matching the
    property parameters. If found, returns it directly. Otherwise computes
    via the ML model and stores the result for future lookups.

    Args:
        tool_input: The tool input dict with latitude, longitude, beds, etc.
        source: Origin label for the prediction ('chat', 'predict', 'manual').

    Returns:
        Prediction dict with predicted_price, price_lower, price_upper,
        feature_contributions, etc.
    """
    lat = tool_input["latitude"]
    lon = tool_input["longitude"]
    beds = tool_input.get("beds")
    baths = tool_input.get("baths")
    sqft = tool_input.get("sqft")
    year_built = tool_input.get("year_built")
    lot_size_sqft = tool_input.get("lot_size_sqft")
    property_type = tool_input.get("property_type", "Single Family Residential")
    neighborhood = tool_input.get("neighborhood", "Berkeley")
    zip_code = tool_input.get("zip_code", "94702")

    # 1) Check cache
    cached = _state.db.get_cached_prediction(
        latitude=lat,
        longitude=lon,
        beds=beds,
        baths=baths,
        sqft=sqft,
        year_built=year_built,
        lot_size_sqft=lot_size_sqft,
        property_type=property_type,
    )
    if cached:
        logger.info(
            "Cache HIT for prediction at (%s, %s) — returning stored result #%d",
            lat, lon, cached["id"],
        )
        return {
            "predicted_price": cached["predicted_price"],
            "price_lower": cached["price_lower"],
            "price_upper": cached["price_upper"],
            "neighborhood": cached["neighborhood"],
            "list_price": cached["list_price"],
            "predicted_premium_pct": cached["predicted_premium_pct"],
            "base_value": cached["base_value"],
            "feature_contributions": cached["feature_contributions"],
            "cached": True,
            "cached_at": cached["created_at"],
        }

    # 2) Compute fresh prediction
    logger.info("Cache MISS for prediction at (%s, %s) — computing fresh", lat, lon)
    model = _require_model()
    prop = {
        "latitude": lat,
        "longitude": lon,
        "neighborhood": neighborhood,
        "zip_code": zip_code,
        "beds": beds,
        "baths": baths,
        "sqft": sqft,
        "year_built": year_built,
        "lot_size_sqft": lot_size_sqft,
        "property_type": property_type,
    }
    result = model.predict_single(_state.db, prop)
    pred_dict = _prediction_to_dict(result)

    # 3) Store in cache
    _state.db.store_prediction(
        latitude=lat,
        longitude=lon,
        predicted_price=result.predicted_price,
        price_lower=result.price_lower,
        price_upper=result.price_upper,
        neighborhood=result.neighborhood or neighborhood,
        zip_code=zip_code,
        beds=beds,
        baths=baths,
        sqft=sqft,
        year_built=year_built,
        lot_size_sqft=lot_size_sqft,
        property_type=property_type,
        list_price=result.list_price,
        base_value=result.base_value,
        predicted_premium_pct=result.predicted_premium_pct,
        feature_contributions=result.feature_contributions,
        source=source,
    )

    return pred_dict


def _prediction_to_dict(result) -> dict:
    """Convert PredictionResult to JSON-serializable dict."""
    return {
        "predicted_price": result.predicted_price,
        "price_lower": result.price_lower,
        "price_upper": result.price_upper,
        "neighborhood": result.neighborhood,
        "list_price": result.list_price,
        "predicted_premium_pct": result.predicted_premium_pct,
        "base_value": result.base_value,
        "feature_contributions": result.feature_contributions,
    }


def _development_potential_to_dict(result) -> dict:
    """Convert DevelopmentPotential to JSON-serializable dict."""
    resp: dict = {}

    if result.zoning:
        resp["zoning"] = {
            "zone_class": result.zoning.zone_class,
            "zone_desc": result.zoning.zone_desc,
            "general_plan": result.zoning.general_plan,
        }
    else:
        resp["zoning"] = None

    if result.zone_rule:
        resp["zone_rule"] = {
            "max_lot_coverage_pct": result.zone_rule.max_lot_coverage_pct,
            "max_height_ft": result.zone_rule.max_height_ft,
            "is_hillside": result.zone_rule.is_hillside,
            "residential": result.zone_rule.residential,
        }
    else:
        resp["zone_rule"] = None

    if result.units:
        resp["units"] = {
            "base_max_units": result.units.base_max_units,
            "middle_housing_eligible": result.units.middle_housing_eligible,
            "middle_housing_max_units": result.units.middle_housing_max_units,
            "effective_max_units": result.units.effective_max_units,
        }
    else:
        resp["units"] = None

    if result.adu:
        resp["adu"] = {
            "eligible": result.adu.eligible,
            "max_adu_sqft": result.adu.max_adu_sqft,
            "remaining_lot_coverage_sqft": result.adu.remaining_lot_coverage_sqft,
            "notes": result.adu.notes,
        }
    else:
        resp["adu"] = None

    if result.sb9:
        resp["sb9"] = {
            "eligible": result.sb9.eligible,
            "can_split": result.sb9.can_split,
            "resulting_lot_sizes": result.sb9.resulting_lot_sizes,
            "max_total_units": result.sb9.max_total_units,
            "notes": result.sb9.notes,
        }
    else:
        resp["sb9"] = None

    resp["beso"] = result.beso or []

    resp["improvements"] = [
        {
            "category": imp.category,
            "avg_job_value": imp.avg_job_value,
            "avg_ppsf_premium_pct": imp.avg_ppsf_premium_pct,
            "sample_count": imp.sample_count,
        }
        for imp in result.improvements
    ]

    return resp


def _sale_to_listing(prop: dict, neighborhood: str | None = None) -> dict:
    """Convert a property_sales DB row to ListingData format for the frontend."""
    sale_date = prop.get("sale_date")
    if sale_date and hasattr(sale_date, "isoformat"):
        sale_date = sale_date.isoformat()
    return {
        "address": prop.get("address", ""),
        "city": prop.get("city", "Berkeley"),
        "state": prop.get("state", "CA"),
        "zip_code": prop.get("zip_code", ""),
        "latitude": prop.get("latitude", 0),
        "longitude": prop.get("longitude", 0),
        "beds": prop.get("beds"),
        "baths": prop.get("baths"),
        "sqft": prop.get("sqft"),
        "year_built": prop.get("year_built"),
        "lot_size_sqft": prop.get("lot_size_sqft"),
        "property_type": prop.get("property_type", "Single Family Residential"),
        "list_price": prop.get("sale_price"),  # use last sale price as reference
        "neighborhood": neighborhood or prop.get("neighborhood"),
        "redfin_url": prop.get("redfin_url", ""),
        "property_id": None,
        "sale_date": sale_date,
        "hoa_per_month": prop.get("hoa_per_month"),
        "garage_spaces": None,
        # For DB-sourced properties, the record IS the last sale
        "last_sale_price": prop.get("sale_price"),
        "last_sale_date": sale_date,
    }


def _attom_to_listing(
    prop: dict,
    neighborhood: str,
    zone_class: str | None = None,
    last_sale_price: int | None = None,
    last_sale_date: str | None = None,
) -> dict:
    """Convert ATTOM-sourced property details to ListingData format."""
    return {
        "address": prop.get("address", ""),
        "city": "Berkeley",
        "state": "CA",
        "zip_code": prop.get("zip_code", ""),
        "latitude": prop.get("latitude", 0),
        "longitude": prop.get("longitude", 0),
        "beds": prop.get("beds"),
        "baths": prop.get("baths"),
        "sqft": prop.get("sqft"),
        "year_built": prop.get("year_built"),
        "lot_size_sqft": prop.get("lot_size_sqft"),
        "property_type": prop.get("property_type", "Single Family Residential"),
        "list_price": None,
        "neighborhood": neighborhood,
        "redfin_url": "",
        "property_id": None,
        "sale_date": None,
        "hoa_per_month": prop.get("hoa_per_month"),
        "garage_spaces": None,
        "last_sale_price": last_sale_price,
        "last_sale_date": last_sale_date,
    }


def _reverse_geocode(lat: float, lon: float) -> str | None:
    """Reverse geocode lat/lng to street address via Nominatim (OpenStreetMap)."""
    import requests as _requests

    try:
        resp = _requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "addressdetails": 1},
            headers={"User-Agent": "HomeBuyer-Berkeley/0.1"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        address = data.get("address", {})
        house_number = address.get("house_number", "")
        road = address.get("road", "")
        if house_number and road:
            return f"{house_number} {road}"
        display = data.get("display_name", "")
        return display.split(",")[0] if display else None
    except Exception as e:
        logger.warning("Reverse geocode failed: %s", e)
        return None


def _estimate_zip_from_coords(lat: float, lon: float) -> str:
    """Estimate zip code from coordinates using nearby sales data."""
    delta = 0.003  # ~330 m
    row = _state.db.conn.execute(
        """
        SELECT zip_code, COUNT(*) AS cnt
        FROM property_sales
        WHERE latitude BETWEEN ? AND ?
          AND longitude BETWEEN ? AND ?
        GROUP BY zip_code
        ORDER BY cnt DESC
        LIMIT 1
        """,
        (lat - delta, lat + delta, lon - delta, lon + delta),
    ).fetchone()
    return dict(row)["zip_code"] if row else "94702"


def _persist_attom_sales(
    address: str,
    city: str,
    state: str,
    zip_code: str,
    latitude: float,
    longitude: float,
    neighborhood: str | None,
    attom_detail: "AttomPropertyDetail | None" = None,
) -> None:
    """Fetch full sale history from ATTOM and persist to the database.

    Called after a successful prediction for a property not already in the DB.
    If no sale history is found, persists a property-only record (null
    sale_price/sale_date) so the property is cached for future lookups.

    Errors are logged but never raised so the prediction response is unaffected.
    """
    if not _state.attom or not _state.attom.enabled:
        return
    if not address:
        return

    try:
        from datetime import date as date_type

        from homebuyer.storage.models import PropertySale

        address2 = f"{city}, {state} {zip_code}".strip()
        history = _state.attom.lookup_sale_history(
            address1=address, address2=address2,
        )

        inserted = 0

        if history:
            for txn in history:
                txn_lat = txn.get("latitude") or latitude
                txn_lng = txn.get("longitude") or longitude
                if not txn_lat or not txn_lng:
                    continue

                try:
                    sale_date_obj = date_type.fromisoformat(txn["sale_date"])
                except (KeyError, ValueError):
                    continue

                sale_price = txn.get("sale_price")
                if not sale_price or sale_price <= 0:
                    continue

                sqft = txn.get("sqft")
                price_per_sqft = (
                    round(sale_price / sqft, 2) if sqft and sqft > 0 else None
                )

                sale = PropertySale(
                    address=address,
                    city=city,
                    state=state,
                    zip_code=zip_code,
                    latitude=float(txn_lat),
                    longitude=float(txn_lng),
                    sale_date=sale_date_obj,
                    sale_price=sale_price,
                    sale_type=txn.get("sale_type"),
                    property_type=txn.get("property_type"),
                    beds=txn.get("beds"),
                    baths=txn.get("baths"),
                    sqft=sqft,
                    lot_size_sqft=txn.get("lot_size_sqft"),
                    year_built=txn.get("year_built"),
                    price_per_sqft=price_per_sqft,
                    neighborhood=neighborhood,
                    data_source="attom",
                )
                if _state.db.upsert_sale(sale):
                    inserted += 1

        # If no sale history was persisted, save a property-only record
        # from ATTOM property details so we don't re-query ATTOM next time
        if inserted == 0 and attom_detail:
            prop_record = PropertySale(
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                latitude=latitude,
                longitude=longitude,
                sale_date=None,
                sale_price=None,
                property_type=attom_detail.property_type,
                beds=attom_detail.beds,
                baths=attom_detail.baths,
                sqft=attom_detail.sqft,
                lot_size_sqft=attom_detail.lot_size_sqft,
                year_built=attom_detail.year_built,
                neighborhood=neighborhood,
                data_source="attom",
            )
            if _state.db.upsert_sale(prop_record):
                inserted = 1
                logger.info(
                    "Persisted property-only record for %s (no sale history)",
                    address,
                )

        if inserted and history:
            logger.info(
                "Persisted %d ATTOM sale records for %s", inserted, address,
            )
    except Exception:
        logger.warning(
            "Failed to persist ATTOM sales for %s", address, exc_info=True,
        )


def _collect_permits_background(address: str) -> None:
    """Collect building permits for an address in a background thread.

    Uses Playwright (headless Chromium) to scrape the Accela portal,
    which takes ~8-10 seconds per address.  Runs in a daemon thread so
    the prediction response is not delayed.

    Errors are logged but never propagated.
    """
    import threading

    def _run() -> None:
        try:
            from homebuyer.collectors.accela_permits import AccelaPermitCollector

            collector = AccelaPermitCollector(_state.db)
            permits = collector.collect_for_address(address)
            if permits:
                logger.info(
                    "Background permit collection: %d permits for %s",
                    len(permits), address,
                )
            else:
                logger.debug("Background permit collection: no permits for %s", address)
        except Exception:
            logger.warning(
                "Background permit collection failed for %s", address, exc_info=True,
            )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


# Common non-residential zone descriptions for user-friendly error messages
_ZONE_DESCRIPTIONS: dict[str, str] = {
    "C-AC": "Adeline Corridor Commercial",
    "C-C": "Community Commercial",
    "C-DMU": "Downtown Mixed Use",
    "C-DMU Buffer": "Downtown Mixed Use Buffer",
    "C-DMU Core": "Downtown Mixed Use Core",
    "C-DMU Corridor": "Downtown Mixed Use Corridor",
    "C-DMU Outer Core": "Downtown Mixed Use Outer Core",
    "C-E": "Employment",
    "C-N": "Neighborhood Commercial",
    "C-NS": "North Shattuck Commercial",
    "C-SA": "South Area Commercial",
    "C-SO": "Solano Avenue Commercial",
    "C-T": "Telegraph Avenue Commercial",
    "C-U": "University Avenue Commercial",
    "C-W": "West Berkeley Commercial",
    "M": "Manufacturing",
    "MM": "Mixed Manufacturing",
    "MRD": "Mixed Residential/Development",
    "MULI": "Mixed Use Light Industrial",
    "MUR": "Mixed Use Residential",
    "SP": "Specific Plan",
    "U": "Unclassified",
}


def _neighborhood_stats_to_dict(stats) -> dict:
    """Convert NeighborhoodStats to JSON-serializable dict."""
    return {
        "name": stats.name,
        "sale_count": stats.sale_count,
        "median_price": stats.median_price,
        "avg_price": stats.avg_price,
        "min_price": stats.min_price,
        "max_price": stats.max_price,
        "median_ppsf": stats.median_ppsf,
        "avg_ppsf": stats.avg_ppsf,
        "median_sqft": stats.median_sqft,
        "avg_year_built": stats.avg_year_built,
        "yoy_price_change_pct": stats.yoy_price_change_pct,
        "median_lot_size": stats.median_lot_size,
        "property_type_breakdown": stats.property_type_breakdown,
        "dominant_zoning": stats.dominant_zoning,
        "zoning_breakdown": stats.zoning_breakdown,
    }


# ---------------------------------------------------------------------------
# Static file serving for production (React SPA)
# ---------------------------------------------------------------------------

import os
from pathlib import Path as _Path

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Resolve the UI build directory relative to the project root.
# In production, the build script places the built frontend at ui/dist/.
_UI_DIST = _Path(__file__).resolve().parents[2] / "ui" / "dist"

if _UI_DIST.is_dir():
    # Serve static assets (JS, CSS, images) from the Vite build output.
    app.mount("/assets", StaticFiles(directory=_UI_DIST / "assets"), name="static-assets")

    @app.get("/{path:path}")
    async def _serve_spa(path: str):
        """Catch-all: serve index.html for SPA client-side routing."""
        # If a real file exists at the path, serve it (e.g. favicon.ico)
        file = _UI_DIST / path
        if path and file.is_file():
            return FileResponse(file)
        return FileResponse(_UI_DIST / "index.html")
else:
    logger.info("No UI build found at %s — API-only mode.", _UI_DIST)


# ---------------------------------------------------------------------------
# Entrypoint for `python -m homebuyer.api`
# ---------------------------------------------------------------------------


def main():
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "10000"))
    print(f"Starting uvicorn on {host}:{port}")
    uvicorn.run(
        "homebuyer.api:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
