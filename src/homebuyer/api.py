"""FastAPI backend for HomeBuyer Tauri app.

Thin wrapper around existing prediction, analysis, and data modules.
Designed to run as a sidecar process spawned by the Tauri shell.

Usage:
    python -m homebuyer.api          # Runs on port 8787
    uvicorn homebuyer.api:app --port 8787
"""

import logging
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

        # ATTOM property data client (optional — auto-fills property details)
        from homebuyer.collectors.attom import AttomClient

        self.attom = AttomClient()

    def get_analyzer(self):
        from homebuyer.analysis.market_analysis import MarketAnalyzer
        return MarketAnalyzer(self.db)

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

    # Run prediction
    result = model.predict_single(_state.db, listing)

    # Find comparable sales
    analyzer = _state.get_analyzer()
    comps = analyzer.find_comparables(
        neighborhood=listing.get("neighborhood", ""),
        beds=listing.get("beds"),
        baths=listing.get("baths"),
        sqft=listing.get("sqft"),
        year_built=listing.get("year_built"),
    )

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

    # Step 1: Neighborhood lookup (also serves as "in Berkeley?" check)
    if not _state.geocoder:
        raise HTTPException(
            status_code=503,
            detail="Neighborhood geocoder not available.",
        )
    neighborhood = _state.geocoder.geocode_point(req.latitude, req.longitude)
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
    nearest = _state.db.find_nearest_sale(req.latitude, req.longitude, max_distance_m=50)

    if nearest:
        # Full prediction from existing property record
        prop = dict(nearest)
        prop["neighborhood"] = neighborhood  # ensure current geocoded neighborhood

        result = model.predict_single(_state.db, prop)

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

    # Step 5: No nearby property — reverse geocode for address
    address = _reverse_geocode(req.latitude, req.longitude)

    # Step 5b: Try ATTOM property detail lookup (if configured)
    attom_detail = None
    if address and _state.attom and _state.attom.enabled:
        attom_detail = _state.attom.lookup_property(
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
            "listing": _attom_to_listing(prop, neighborhood, zone_class),
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
    }


def _attom_to_listing(
    prop: dict, neighborhood: str, zone_class: str | None = None,
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
    }


# ---------------------------------------------------------------------------
# Entrypoint for `python -m homebuyer.api`
# ---------------------------------------------------------------------------


def main():
    import uvicorn
    uvicorn.run(
        "homebuyer.api:app",
        host="127.0.0.1",
        port=8787,
        log_level="info",
    )


if __name__ == "__main__":
    main()
