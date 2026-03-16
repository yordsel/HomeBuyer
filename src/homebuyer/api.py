"""FastAPI backend for HomeBuyer Tauri app.

Thin wrapper around existing prediction, analysis, and data modules.
Designed to run as a sidecar process spawned by the Tauri shell.

Usage:
    python -m homebuyer.api          # Runs on port 8787
    uvicorn homebuyer.api:app --port 8787
"""

import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path as _Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

import json

from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from homebuyer.auth import get_current_user_id
from homebuyer.config import (
    CURRENT_TOS_VERSION,
    DATABASE_URL,
    DB_PATH,
    ENVIRONMENT,
    GEO_DIR,
    APP_URL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)
from homebuyer.middleware.security_headers import SecurityHeadersMiddleware
from homebuyer.utils.serialization import safe_json_dumps

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Zone description lookup (used in predict_map_click and elsewhere)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Shared helpers (deduplicated from multiple endpoints)
# ---------------------------------------------------------------------------


def _store_prediction_from_result(db, result, prop: dict, source: str):
    """Store a prediction result in the cache. Used by all prediction endpoints."""
    lat = prop.get("latitude")
    lon = prop.get("longitude")
    if not lat or not lon:
        return
    db.store_prediction(
        latitude=lat,
        longitude=lon,
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
        source=source,
    )


def _resolve_property_from_db(
    lat: float,
    lon: float,
    overrides: dict,
    db,
    geocoder,
    *,
    extra_fields: tuple[str, ...] = (),
) -> dict:
    """Resolve property details from DB nearest-sale + geocoder fallback.

    ``overrides`` supplies caller-provided values that take precedence.
    Returns a property dict suitable for ML prediction or analysis.
    """
    # Start with caller values
    neighborhood = overrides.get("neighborhood")
    zip_code = overrides.get("zip_code") or "94702"
    sqft = overrides.get("sqft")
    lot_size_sqft = overrides.get("lot_size_sqft")
    address = overrides.get("address")
    beds = overrides.get("beds")
    baths = overrides.get("baths")
    year_built = overrides.get("year_built")

    # Fill gaps from nearest sale
    if db:
        nearest = db.find_nearest_sale(lat, lon, max_distance_m=50)
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
            if not overrides.get("zip_code"):
                zip_code = nearest.get("zip_code") or zip_code

    # Geocoder fallback for neighborhood
    if not neighborhood and geocoder:
        neighborhood = geocoder.geocode_point(lat, lon)
        if not neighborhood:
            neighborhood = geocoder.geocode_nearest(lat, lon)
    if not neighborhood:
        neighborhood = "Berkeley"

    prop = {
        "latitude": lat,
        "longitude": lon,
        "neighborhood": neighborhood,
        "zip_code": zip_code,
        "beds": beds,
        "baths": baths,
        "sqft": sqft,
        "lot_size_sqft": lot_size_sqft,
        "year_built": year_built,
        "property_type": overrides.get("property_type"),
        "hoa_per_month": overrides.get("hoa_per_month"),
        "address": address,
    }
    # Copy through any extra fields the caller needs
    for f in extra_fields:
        if f not in prop and f in overrides:
            prop[f] = overrides[f]
    return prop


def _validate_sql(sql: str, *, allow_create: bool = False) -> str | None:
    """Validate a SQL query for safety. Returns error message or None if OK."""
    sql_upper = sql.upper().lstrip()
    if not sql_upper.startswith("SELECT"):
        return (
            "Only SELECT queries are allowed. "
            "INSERT, UPDATE, DELETE, DROP, and other modifying statements are blocked."
        )
    blocked = [
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
        "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX",
    ]
    if not allow_create:
        blocked.append("CREATE")
    sql_words = set(re.findall(r'\b[A-Z]+\b', sql_upper))
    blocked_found = sql_words & set(blocked)
    if blocked_found:
        return (
            f"Query contains blocked keywords: {', '.join(sorted(blocked_found))}. "
            "Only read-only SELECT queries are allowed."
        )
    return None


def _enforce_sql_limit(sql: str) -> str:
    """Add LIMIT 100 to a SQL query if none is present."""
    if "LIMIT" not in sql.upper():
        return sql.rstrip(";") + " LIMIT 100"
    return sql


def _clean_address_for_rentcast(address: str, zip_code: str) -> str:
    """Strip city suffix from an address for RentCast API lookup."""
    street = re.sub(r"\s+\d{5}(-\d{4})?$", "", address.strip())
    for city in ("BERKELEY", "ALBANY", "EMERYVILLE", "OAKLAND", "KENSINGTON"):
        if street.upper().endswith(f" {city}"):
            street = street[:-(len(city) + 1)].strip()
            break
    return f"{street}, Berkeley, CA {zip_code}".strip()


def _build_working_set_metadata(working_set, session_id: str | None) -> dict:
    """Build working-set metadata dict for frontend sidebar.

    Always returns metadata (even when count is 0) so the frontend
    can synchronize its sidebar state with the server.
    """
    return {
        "count": working_set.count,
        "descriptor": working_set.get_descriptor(),
        "session_id": session_id,
        "sample": working_set.get_sample(25),
        "discussed": [p.to_dict() for p in working_set.discussed],
        "filter_depth": len(working_set.filter_stack),
    }


# Tools that operate on a single property (trigger discussed-property tracking)
_PER_PROPERTY_TOOLS = {
    "lookup_property",
    "get_development_potential",
    "get_improvement_simulation",
    "get_price_prediction",
    "get_comparable_sales",
    "estimate_sell_vs_hold",
    "estimate_rental_income",
    "analyze_investment_scenarios",
    "generate_investment_prospectus",
    "lookup_permits",
}


def _track_discussed_property(
    working_set,
    tool_name: str,
    tool_input: dict,
    result_str: str,
) -> None:
    """Mark a property as discussed after a per-property tool call.

    Tries to extract the property ID from the tool input first, then
    falls back to parsing the result JSON.  If the property is in the
    working set we use ``add_discussed``; otherwise we build a
    ``PropertyRecord`` from the result and use ``add_discussed_record``.
    """
    from homebuyer.services.session_cache import PropertyRecord, WORKING_SET_FIELDS

    # Parse result JSON once and reuse
    result_data: dict | None = None
    try:
        parsed = json.loads(result_str)
        if isinstance(parsed, dict):
            result_data = parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # 1. Try to get property_id from tool_input
    property_id = tool_input.get("property_id")

    # 2. Fallback: parse result JSON for "id" field
    if property_id is None and result_data is not None:
        property_id = result_data.get("id")

    if property_id is None:
        return

    # Ensure int
    try:
        property_id = int(property_id)
    except (ValueError, TypeError):
        return

    # 3. Try adding from working set first (most common case)
    if property_id in working_set.properties:
        working_set.add_discussed(property_id)
        logger.info("Discussed property %d tracked from working set", property_id)
        return

    # 4. Property not in working set — build a record from the result
    if result_data is not None:
        try:
            record_kwargs = {
                k: result_data.get(k) for k in WORKING_SET_FIELDS
            }
            record_kwargs["id"] = property_id
            record = PropertyRecord(**record_kwargs)
            working_set.add_discussed_record(record)
            logger.info(
                "Discussed property %d tracked (not in working set)",
                property_id,
            )
        except Exception as e:
            logger.warning("Could not build PropertyRecord for discussed tracking: %s", e)


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class AuthUserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    accepted_tos_version: Optional[str] = None


class AuthUserLogin(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordConfirmRequest(BaseModel):
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class CreateConversationRequest(BaseModel):
    session_id: str
    title: Optional[str] = None


class UpdateConversationRequest(BaseModel):
    title: str


class SaveMessageRequest(BaseModel):
    role: str
    content: str
    blocks_json: Optional[str] = None
    tools_used_json: Optional[str] = None
    tool_events_json: Optional[str] = None


class SaveMessagesRequest(BaseModel):
    messages: list[SaveMessageRequest]


class ListingPredictRequest(BaseModel):
    url: str


class ManualPredictRequest(BaseModel):
    model_config = {"coerce_numbers_to_str": True}

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
    model_config = {"coerce_numbers_to_str": True}

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
    model_config = {"coerce_numbers_to_str": True}

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


class ProspectusRequest(BaseModel):
    """Request body for the investment prospectus endpoint."""

    address: str  # required — used to look up property in DB
    down_payment_pct: float = 20.0
    investment_horizon_years: int = 5
    mode: Optional[str] = None  # "curated", "similar", "thesis", or None = auto


# ---------------------------------------------------------------------------
# Application state — loaded once at startup, kept warm
# ---------------------------------------------------------------------------


class AppState:
    """Holds long-lived resources: DB connection, ML model, analyzer."""

    def __init__(self) -> None:
        from homebuyer.prediction.model import ModelArtifact
        from homebuyer.storage.database import Database

        db_source = DATABASE_URL if DATABASE_URL else DB_PATH
        logger.info("Loading database from %s", db_source if isinstance(db_source, str) else DB_PATH)
        self.db = Database(db_source)
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

        # RentCast property data client (PRIMARY — property enrichment)
        from homebuyer.collectors.rentcast import RentcastClient

        self.rentcast = RentcastClient()
        if self.rentcast.enabled:
            logger.info("RentCast property enrichment enabled (primary)")
        else:
            logger.warning("RentCast API key not configured — on-demand enrichment limited")

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

        # Check email service status
        from homebuyer.services.email import is_email_configured

        if is_email_configured():
            logger.info("Transactional email enabled (Resend API)")
        else:
            logger.info("Transactional email disabled (no RESEND_API_KEY) — tokens will be logged")

        # In-memory TTL cache for frequently-accessed analytics
        self._ttl_cache: dict[str, tuple[float, object]] = {}

        # Session-scoped property cache for Faketor conversations
        from homebuyer.services.session_cache import SessionManager

        self.sessions = SessionManager(ttl_seconds=1800)

        # DataLayer facade for faketor package — wraps all infrastructure
        # behind a typed Protocol so faketor/ never imports from api.py.
        # Constructed after all services are initialized.
        from homebuyer.services.faketor._infra import AppStateDataLayer
        from homebuyer.services import berkeley_regulations as reg_module
        from homebuyer.services import glossary as glossary_module

        self.data_layer = AppStateDataLayer(
            db=self.db,
            model=self.model,
            dev_calc=self.dev_calc,
            rental_analyzer=self.rental_analyzer,
            geocoder=self.geocoder,
            regulation_service=reg_module,
            glossary_service=glossary_module,
            cache_get=self.cache_get,
            cache_set=self.cache_set,
        )

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
    # Generate fun facts at startup (non-blocking, non-fatal)
    try:
        from homebuyer.services.fun_facts import generate_fun_facts
        facts = generate_fun_facts(_state.db)
        logger.info("Generated %d fun facts at startup", len(facts))
    except Exception:
        logger.warning("Fun fact generation failed at startup", exc_info=True)
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

_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]
# Allow custom frontend URL for staging/preview deployments
_extra_origin = os.environ.get("FRONTEND_URL", "")
if _extra_origin:
    _cors_origins.append(_extra_origin.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers (CSP, X-Frame-Options, HSTS, etc.)
app.add_middleware(SecurityHeadersMiddleware, environment=ENVIRONMENT)

# ---------------------------------------------------------------------------
# Rate limiting (slowapi)
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return 429 with Retry-After header when rate limit is exceeded."""
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."},
        headers={"Retry-After": str(retry_after)},
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


@app.get("/api/fun-fact")
def random_fun_fact():
    """Return a random fun fact about the Berkeley market."""
    fact = _state.db.get_random_fun_fact()
    if not fact:
        return {
            "category": "meta",
            "display_text": (
                "I know everything about Berkeley real estate. "
                "Well, almost — nobody's generated my fun facts yet."
            ),
        }
    return fact


def _client_info(request: Request) -> tuple[str | None, str | None]:
    """Extract client IP and user-agent from a request."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


# --- Authentication ---


@app.post("/api/auth/register")
@limiter.limit("3/minute")
def auth_register(req: AuthUserCreate, request: Request):
    """Create a new user account and return JWT + refresh tokens."""
    from homebuyer.auth import (
        AuthResponse,
        UserResponse,
        create_access_token,
        create_refresh_token,
        hash_password,
        validate_password,
    )

    password_errors = validate_password(req.password)
    if password_errors:
        raise HTTPException(status_code=400, detail=password_errors[0])

    if not req.accepted_tos_version:
        raise HTTPException(status_code=400, detail="You must accept the Terms and Conditions")

    existing = _state.db.get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    password_hash = hash_password(req.password)
    user = _state.db.create_user(
        email=req.email, password_hash=password_hash, full_name=req.full_name
    )

    # Record TOS acceptance
    client_ip = request.client.host if request.client else None
    _state.db.create_tos_acceptance(
        user_id=user["id"],
        tos_version=req.accepted_tos_version,
        ip_address=client_ip,
    )

    access_token = create_access_token(data={"sub": str(user["id"])})
    refresh_token = create_refresh_token(_state.db, user["id"])
    auth_resp = AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(id=user["id"], email=user["email"], full_name=user["full_name"]),
    )
    response = JSONResponse(content=auth_resp.model_dump())
    from homebuyer.auth import set_access_cookie
    set_access_cookie(response, access_token)

    ip, ua = _client_info(request)
    _state.db.log_auth_event("register", user_id=user["id"], ip_address=ip, user_agent=ua)
    return response


@app.post("/api/auth/login")
@limiter.limit("5/minute")
def auth_login(req: AuthUserLogin, request: Request):
    """Authenticate a user and return JWT + refresh tokens."""
    from homebuyer.auth import (
        AuthResponse,
        UserResponse,
        create_access_token,
        create_refresh_token,
        verify_password,
    )

    ip, ua = _client_info(request)
    user = _state.db.get_user_by_email(req.email)
    if not user or not user.get("password_hash") or not verify_password(req.password, user["password_hash"]):
        _state.db.log_auth_event(
            "login_failure",
            user_id=user["id"] if user else None,
            ip_address=ip, user_agent=ua, success=False,
            detail=f"email={req.email}",
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("is_active", True):
        _state.db.log_auth_event(
            "login_failure", user_id=user["id"],
            ip_address=ip, user_agent=ua, success=False,
            detail="account_deactivated",
        )
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Check if user needs to re-accept TOS
    tos_acceptance = _state.db.get_latest_tos_acceptance(user["id"])
    tos_update_required = (
        tos_acceptance is None or tos_acceptance.get("tos_version") != CURRENT_TOS_VERSION
    )

    access_token = create_access_token(data={"sub": str(user["id"])})
    refresh_token = create_refresh_token(_state.db, user["id"])
    auth_resp = AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(id=user["id"], email=user["email"], full_name=user.get("full_name")),
        tos_update_required=tos_update_required,
    )
    response = JSONResponse(content=auth_resp.model_dump())
    from homebuyer.auth import set_access_cookie
    set_access_cookie(response, access_token)

    _state.db.log_auth_event("login_success", user_id=user["id"], ip_address=ip, user_agent=ua)
    return response


@app.get("/api/auth/me")
def auth_me(user_id: int = Depends(get_current_user_id)):
    """Return the profile of the currently authenticated user."""
    from homebuyer.auth import UserResponse

    user = _state.db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(id=user["id"], email=user["email"], full_name=user.get("full_name"))


@app.post("/api/auth/refresh")
@limiter.limit("10/minute")
def auth_refresh(req: RefreshTokenRequest, request: Request):
    """Exchange a valid refresh token for a new access + refresh token pair (rotation)."""
    from homebuyer.auth import (
        AuthResponse,
        UserResponse,
        create_access_token,
        create_refresh_token,
        validate_refresh_token,
    )

    # Validate the incoming refresh token
    token_row = validate_refresh_token(_state.db, req.refresh_token)
    user_id = token_row["user_id"]

    # Revoke the old refresh token (rotation — single use)
    _state.db.revoke_refresh_token(token_row["id"])

    # Verify user still exists and is active
    user = _state.db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Issue new pair
    new_access = create_access_token(data={"sub": str(user_id)})
    new_refresh = create_refresh_token(_state.db, user_id)
    auth_resp = AuthResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user=UserResponse(id=user["id"], email=user["email"], full_name=user.get("full_name")),
    )
    response = JSONResponse(content=auth_resp.model_dump())
    from homebuyer.auth import set_access_cookie
    set_access_cookie(response, new_access)
    return response


@app.post("/api/auth/logout")
def auth_logout(req: RefreshTokenRequest, request: Request):
    """Revoke a refresh token (server-side logout) and clear the access cookie."""
    from homebuyer.auth import _hash_token, clear_access_cookie

    token_hash = _hash_token(req.refresh_token)
    row = _state.db.get_refresh_token_by_hash(token_hash)
    user_id = row["user_id"] if row else None
    if row:
        _state.db.revoke_refresh_token(row["id"])
    response = JSONResponse(content={"detail": "Logged out"})
    clear_access_cookie(response)

    ip, ua = _client_info(request)
    _state.db.log_auth_event("logout", user_id=user_id, ip_address=ip, user_agent=ua)
    return response


@app.post("/api/auth/change-password")
def auth_change_password(
    req: ChangePasswordRequest,
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    """Change the authenticated user's password. Revokes all refresh tokens."""
    from homebuyer.auth import hash_password, validate_password, verify_password

    user = _state.db.get_user_with_password_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    ip, ua = _client_info(request)

    if not user.get("password_hash") or not verify_password(req.current_password, user["password_hash"]):
        _state.db.log_auth_event(
            "password_change", user_id=user_id,
            ip_address=ip, user_agent=ua, success=False,
            detail="incorrect_current_password",
        )
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    password_errors = validate_password(req.new_password)
    if password_errors:
        raise HTTPException(status_code=400, detail=password_errors[0])

    new_hash = hash_password(req.new_password)
    _state.db.update_user_password(user_id, new_hash)
    # Revoke all refresh tokens to force re-login on other devices
    _state.db.revoke_all_user_refresh_tokens(user_id)

    _state.db.log_auth_event("password_change", user_id=user_id, ip_address=ip, user_agent=ua)
    return {"detail": "Password changed successfully"}


# --- Terms of Service ---


@app.get("/api/terms/current")
def get_current_tos_version():
    """Return the current Terms of Service version."""
    return {"version": CURRENT_TOS_VERSION}


@app.post("/api/auth/accept-tos")
def accept_tos(request: Request, user_id: int = Depends(get_current_user_id)):
    """Record that the user accepted the current TOS version."""
    client_ip = request.client.host if request.client else None
    _state.db.create_tos_acceptance(
        user_id=user_id,
        tos_version=CURRENT_TOS_VERSION,
        ip_address=client_ip,
    )
    return {"detail": "Terms accepted", "version": CURRENT_TOS_VERSION}


@app.get("/api/auth/activity")
def auth_activity(
    request: Request,
    user_id: int = Depends(get_current_user_id),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Return recent authentication activity for the current user."""
    return _state.db.get_auth_activity(user_id, limit=limit, offset=offset)


@app.post("/api/auth/deactivate")
def auth_deactivate(
    req: PasswordConfirmRequest,
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    """Deactivate the user's account (reversible). Requires password confirmation."""
    from homebuyer.auth import verify_password

    user = _state.db.get_user_with_password_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.get("password_hash") or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Incorrect password")

    _state.db.deactivate_user(user_id)
    _state.db.revoke_all_user_refresh_tokens(user_id)

    ip, ua = _client_info(request)
    _state.db.log_auth_event("account_deactivate", user_id=user_id, ip_address=ip, user_agent=ua)

    from homebuyer.auth import clear_access_cookie
    response = JSONResponse(content={"detail": "Account deactivated"})
    clear_access_cookie(response)
    return response


@app.delete("/api/auth/account")
def auth_delete_account(
    req: PasswordConfirmRequest,
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    """Permanently delete the user's account and all associated data."""
    from homebuyer.auth import verify_password

    user = _state.db.get_user_with_password_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.get("password_hash") or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Incorrect password")

    ip, ua = _client_info(request)
    # Log before deletion since the user record will be gone
    _state.db.log_auth_event(
        "account_delete", user_id=user_id, ip_address=ip, user_agent=ua,
        detail=f"email={user['email']}",
    )

    _state.db.delete_user_cascade(user_id)

    from homebuyer.auth import clear_access_cookie
    response = JSONResponse(content={"detail": "Account permanently deleted"})
    clear_access_cookie(response)
    return response


@app.post("/api/auth/forgot-password")
@limiter.limit("3/hour")
def auth_forgot_password(req: ForgotPasswordRequest, request: Request):
    """Generate a password reset token and send a reset email.

    Always returns success to avoid email enumeration. If Resend is not
    configured the token is logged to the console for local development.
    """
    import secrets
    from datetime import datetime, timedelta, timezone
    from homebuyer.auth import _hash_token

    ip, ua = _client_info(request)
    user = _state.db.get_user_by_email(req.email)

    if user:
        raw_token = secrets.token_urlsafe(48)
        token_hash = _hash_token(raw_token)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        _state.db.create_password_reset_token(
            user_id=user["id"], token_hash=token_hash, expires_at=expires_at,
        )
        _state.db.log_auth_event(
            "password_reset_request", user_id=user["id"],
            ip_address=ip, user_agent=ua,
        )
        # Send reset email (falls back to logging in dev if Resend is not configured)
        from homebuyer.services.email import send_password_reset

        send_password_reset(to=req.email, token=raw_token)
    else:
        _state.db.log_auth_event(
            "password_reset_request", user_id=None,
            ip_address=ip, user_agent=ua, success=False,
            detail=f"unknown_email={req.email}",
        )

    # Always return success to prevent email enumeration
    return {"detail": "If an account with that email exists, a reset link has been sent."}


@app.post("/api/auth/reset-password")
@limiter.limit("5/minute")
def auth_reset_password(req: ResetPasswordRequest, request: Request):
    """Reset a user's password using a valid reset token."""
    from datetime import datetime, timezone
    from homebuyer.auth import _hash_token, hash_password, validate_password

    ip, ua = _client_info(request)
    token_hash = _hash_token(req.token)
    row = _state.db.get_password_reset_token_by_hash(token_hash)

    if row is None or row.get("used"):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    # Check expiry
    expires_at = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="Reset token has expired")

    password_errors = validate_password(req.new_password)
    if password_errors:
        raise HTTPException(status_code=400, detail=password_errors[0])

    user_id = row["user_id"]
    new_hash = hash_password(req.new_password)
    _state.db.update_user_password(user_id, new_hash)
    _state.db.mark_password_reset_used(row["id"])
    _state.db.revoke_all_user_refresh_tokens(user_id)

    _state.db.log_auth_event(
        "password_reset_complete", user_id=user_id,
        ip_address=ip, user_agent=ua,
    )
    return {"detail": "Password has been reset successfully. Please sign in."}


@app.post("/api/auth/resend-verification")
@limiter.limit("1/minute")
def auth_resend_verification(request: Request, user_id: int = Depends(get_current_user_id)):
    """Resend email verification for the current user.

    Sends via Resend if configured; falls back to logging the token for
    local development.
    """
    import secrets
    from datetime import datetime, timedelta, timezone
    from homebuyer.auth import _hash_token

    user = _state.db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.get("is_active", True):
        return {"detail": "Email is already verified"}

    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw_token)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).strftime("%Y-%m-%d %H:%M:%S")
    _state.db.create_email_verification_token(
        user_id=user_id, token_hash=token_hash, expires_at=expires_at,
    )
    # Send verification email (falls back to logging in dev if Resend is not configured)
    from homebuyer.services.email import send_email_verification

    send_email_verification(to=user["email"], token=raw_token)

    ip, ua = _client_info(request)
    _state.db.log_auth_event(
        "verification_resend", user_id=user_id,
        ip_address=ip, user_agent=ua,
    )
    return {"detail": "Verification email sent"}


@app.get("/api/auth/verify-email")
def auth_verify_email(token: str, request: Request):
    """Verify a user's email address using the token from their verification email."""
    from datetime import datetime, timezone
    from homebuyer.auth import _hash_token

    token_hash = _hash_token(token)
    row = _state.db.get_email_verification_token_by_hash(token_hash)

    if row is None or row.get("used"):
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    expires_at = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="Verification token has expired")

    user_id = row["user_id"]
    _state.db.activate_user(user_id)
    _state.db.mark_email_verification_used(row["id"])

    ip, ua = _client_info(request)
    _state.db.log_auth_event(
        "email_verified", user_id=user_id,
        ip_address=ip, user_agent=ua,
    )
    return {"detail": "Email verified successfully. You can now sign in."}


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------


@app.get("/api/auth/google/authorize")
def auth_google_authorize():
    """Return the Google OAuth authorization URL for the client to redirect to."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Google OAuth is not configured")

    from authlib.integrations.httpx_client import AsyncOAuth2Client

    client = AsyncOAuth2Client(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        redirect_uri=GOOGLE_REDIRECT_URI,
        scope="openid email profile",
    )
    uri, _state = client.create_authorization_url(
        "https://accounts.google.com/o/oauth2/v2/auth",
        access_type="offline",
    )
    return {"authorization_url": uri}


@app.get("/api/auth/google/callback")
async def auth_google_callback(code: str, request: Request):
    """Handle Google OAuth callback — exchange code for tokens, create/link user, redirect."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Google OAuth is not configured")

    from authlib.integrations.httpx_client import AsyncOAuth2Client
    from homebuyer.auth import (
        AuthResponse,
        UserResponse,
        create_access_token,
        create_refresh_token,
        set_access_cookie,
    )

    client = AsyncOAuth2Client(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )

    # Exchange authorization code for tokens
    try:
        token = await client.fetch_token(
            "https://oauth2.googleapis.com/token",
            code=code,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

    # Fetch user info from Google
    import httpx

    async with httpx.AsyncClient() as http:
        resp = await http.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Google user info")
        google_user = resp.json()

    google_sub = google_user.get("sub")
    google_email = google_user.get("email")
    google_name = google_user.get("name")

    if not google_sub or not google_email:
        raise HTTPException(status_code=400, detail="Google account missing required info")

    ip, ua = _client_info(request)

    # Check if this Google account is already linked
    oauth_account = _state.db.get_oauth_account("google", google_sub)

    if oauth_account:
        # Existing OAuth link — log in as that user
        user_id = oauth_account["user_id"]
        user = _state.db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Linked user not found")
        if not user.get("is_active", True):
            raise HTTPException(status_code=403, detail="Account is deactivated")
    else:
        # Check if a user with this email already exists
        existing_user = _state.db.get_user_by_email(google_email)
        if existing_user:
            # Link Google account to existing user
            user_id = existing_user["id"]
            user = existing_user
            _state.db.create_oauth_account(
                user_id=user_id,
                provider="google",
                provider_user_id=google_sub,
                email=google_email,
                display_name=google_name,
            )
            _state.db.log_auth_event(
                "oauth_link", user_id=user_id,
                ip_address=ip, user_agent=ua,
                detail=f"provider=google email={google_email}",
            )
        else:
            # Create a new user (no password — OAuth-only)
            user = _state.db.create_user(
                email=google_email,
                password_hash=None,
                full_name=google_name,
            )
            user_id = user["id"]
            _state.db.create_oauth_account(
                user_id=user_id,
                provider="google",
                provider_user_id=google_sub,
                email=google_email,
                display_name=google_name,
            )
            # Auto-accept TOS for OAuth registration
            _state.db.create_tos_acceptance(
                user_id=user_id,
                tos_version=CURRENT_TOS_VERSION,
                ip_address=ip,
            )
            _state.db.log_auth_event(
                "register", user_id=user_id,
                ip_address=ip, user_agent=ua,
                detail="provider=google",
            )

    # Issue tokens
    access_token = create_access_token(data={"sub": str(user_id)})
    refresh_token = create_refresh_token(_state.db, user_id)

    _state.db.log_auth_event(
        "login_success", user_id=user_id,
        ip_address=ip, user_agent=ua,
        detail="provider=google",
    )

    # Redirect to frontend with tokens as URL fragment (not query params — safer)
    import urllib.parse
    fragment = urllib.parse.urlencode({
        "access_token": access_token,
        "refresh_token": refresh_token,
    })
    redirect_url = f"{APP_URL}/auth/callback#{fragment}"
    response = RedirectResponse(url=redirect_url, status_code=302)
    set_access_cookie(response, access_token)
    return response


@app.get("/api/auth/linked-accounts")
def auth_linked_accounts(user_id: int = Depends(get_current_user_id)):
    """List OAuth providers linked to the current user's account."""
    accounts = _state.db.get_user_oauth_accounts(user_id)
    has_password = _state.db.user_has_password(user_id)
    return {
        "accounts": [
            {
                "provider": a["provider"],
                "email": a.get("email"),
                "display_name": a.get("display_name"),
                "created_at": a.get("created_at"),
            }
            for a in accounts
        ],
        "has_password": has_password,
    }


@app.delete("/api/auth/linked-accounts/{provider}")
def auth_unlink_account(provider: str, user_id: int = Depends(get_current_user_id)):
    """Unlink an OAuth provider from the current user's account.

    Only allowed if the user has a password set (otherwise they'd be locked out).
    """
    has_password = _state.db.user_has_password(user_id)
    if not has_password:
        raise HTTPException(
            status_code=400,
            detail="Cannot unlink OAuth — set a password first to maintain account access",
        )
    deleted = _state.db.delete_oauth_account(user_id, provider)
    if not deleted:
        raise HTTPException(status_code=404, detail="No linked account found for this provider")
    return {"detail": f"{provider} account unlinked successfully"}


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


@app.get("/api/auth/sessions")
def auth_list_sessions(user_id: int = Depends(get_current_user_id)):
    """List the current user's active sessions (non-revoked refresh tokens)."""
    sessions = _state.db.get_active_sessions(user_id)
    return [
        {
            "id": s["id"],
            "created_at": s["created_at"],
            "ip_address": s.get("ip_address"),
            "user_agent": s.get("user_agent"),
        }
        for s in sessions
    ]


@app.delete("/api/auth/sessions/{session_id}")
def auth_revoke_session(session_id: int, user_id: int = Depends(get_current_user_id)):
    """Revoke a specific session (refresh token) by ID."""
    from homebuyer.auth import _hash_token

    # Verify the session belongs to this user
    row = _state.db.fetchone(
        "SELECT id, user_id FROM refresh_tokens WHERE id = ? AND revoked = 0",
        (session_id,),
    )
    if not row or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    _state.db.revoke_refresh_token(session_id)
    return {"detail": "Session revoked"}


@app.post("/api/auth/sessions/revoke-others")
def auth_revoke_all_other_sessions(
    req: RefreshTokenRequest,
    user_id: int = Depends(get_current_user_id),
):
    """Revoke all sessions except the current one (identified by the refresh token)."""
    from homebuyer.auth import _hash_token

    token_hash = _hash_token(req.refresh_token)
    current_row = _state.db.get_refresh_token_by_hash(token_hash)
    keep_id = current_row["id"] if current_row else -1
    count = _state.db.revoke_other_sessions(user_id, keep_id)
    return {"detail": f"Revoked {count} other session(s)"}


# --- Conversations ---


@app.get("/api/conversations")
def list_conversations(user_id: int = Depends(get_current_user_id)):
    """List the current user's conversations, most recent first."""
    return _state.db.list_conversations(user_id)


@app.post("/api/conversations")
def create_conversation(
    req: CreateConversationRequest, user_id: int = Depends(get_current_user_id)
):
    """Create a new conversation."""
    return _state.db.create_conversation(
        user_id=user_id, session_id=req.session_id, title=req.title
    )


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user_id: int = Depends(get_current_user_id)):
    """Get a conversation with all its messages."""
    conv = _state.db.get_conversation(conversation_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = _state.db.get_messages(conversation_id, user_id)
    # Parse JSON fields back into objects for the frontend
    for msg in messages:
        if msg.get("blocks_json"):
            try:
                msg["blocks"] = json.loads(msg["blocks_json"])
            except (json.JSONDecodeError, TypeError):
                msg["blocks"] = []
        else:
            msg["blocks"] = []
        if msg.get("tools_used_json"):
            try:
                msg["tools_used"] = json.loads(msg["tools_used_json"])
            except (json.JSONDecodeError, TypeError):
                msg["tools_used"] = []
        else:
            msg["tools_used"] = []
        if msg.get("tool_events_json"):
            try:
                msg["tool_events"] = json.loads(msg["tool_events_json"])
            except (json.JSONDecodeError, TypeError):
                msg["tool_events"] = []
        else:
            msg["tool_events"] = []
        # Remove raw JSON fields
        msg.pop("blocks_json", None)
        msg.pop("tools_used_json", None)
        msg.pop("tool_events_json", None)

    conv["messages"] = messages
    return conv


@app.patch("/api/conversations/{conversation_id}")
def update_conversation(
    conversation_id: int,
    req: UpdateConversationRequest,
    user_id: int = Depends(get_current_user_id),
):
    """Update a conversation's title."""
    conv = _state.db.get_conversation(conversation_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _state.db.update_conversation_title(conversation_id, user_id, req.title)
    return {"ok": True}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int, user_id: int = Depends(get_current_user_id)
):
    """Delete a conversation and all its messages."""
    conv = _state.db.get_conversation(conversation_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _state.db.delete_conversation(conversation_id, user_id)
    return {"ok": True}


@app.post("/api/conversations/{conversation_id}/messages")
def save_messages(
    conversation_id: int,
    req: SaveMessagesRequest,
    user_id: int = Depends(get_current_user_id),
):
    """Append messages to a conversation."""
    conv = _state.db.get_conversation(conversation_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get current max message_index
    existing = _state.db.get_messages(conversation_id, user_id)
    next_index = max((m["message_index"] for m in existing), default=-1) + 1

    saved_ids = []
    for msg in req.messages:
        msg_id = _state.db.save_message(
            conversation_id=conversation_id,
            role=msg.role,
            content=msg.content,
            blocks_json=msg.blocks_json,
            tools_used_json=msg.tools_used_json,
            tool_events_json=msg.tool_events_json,
            message_index=next_index,
        )
        saved_ids.append(msg_id)
        next_index += 1

    _state.db.touch_conversation(conversation_id)
    return {"ok": True, "message_ids": saved_ids}


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
    _store_prediction_from_result(_state.db, result, listing, source="predict")

    # Find comparable sales
    analyzer = _state.get_analyzer()
    comps = analyzer.find_comparables(
        neighborhood=listing.get("neighborhood", ""),
        beds=listing.get("beds"),
        baths=listing.get("baths"),
        sqft=listing.get("sqft"),
        year_built=listing.get("year_built"),
    )

    # Persist RentCast sale history for this listing address
    if _state.rentcast and _state.rentcast.enabled:
        _rc_addr = "{}, {}, {} {}".format(
            listing.get("address", ""),
            listing.get("city", "Berkeley"),
            listing.get("state", "CA"),
            listing.get("zip_code", ""),
        ).strip()
        _rc_detail = _state.rentcast.lookup_property(address=_rc_addr)
        _persist_rentcast_sales(
            address=listing.get("address", ""),
            city=listing.get("city", "Berkeley"),
            state=listing.get("state", "CA"),
            zip_code=listing.get("zip_code", ""),
            latitude=listing.get("latitude", 0),
            longitude=listing.get("longitude", 0),
            neighborhood=listing.get("neighborhood"),
            detail=_rc_detail,
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
    _store_prediction_from_result(_state.db, result, prop, source="manual")

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

    # Step 1b: "In Berkeley?" check — Nominatim reverse geocode fallback
    # when neighborhood polygons have gaps (~0.24% of properties).
    # Uses OpenStreetMap city field to verify the point is in Berkeley.
    if not neighborhood:
        try:
            import requests as _requests
            _nom_resp = _requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "lat": req.latitude,
                    "lon": req.longitude,
                    "format": "json",
                    "addressdetails": 1,
                },
                headers={"User-Agent": "HomeBuyer-Berkeley/0.1"},
                timeout=5,
            )
            _nom_resp.raise_for_status()
            _nom_city = (
                _nom_resp.json()
                .get("address", {})
                .get("city", "")
                .upper()
            )
            if _nom_city == "BERKELEY":
                neighborhood = "Berkeley"
                logger.info(
                    "Nominatim confirmed Berkeley via city field "
                    "(lat=%.6f, lon=%.6f — no polygon match)",
                    req.latitude, req.longitude,
                )
        except Exception as e:
            logger.debug("Nominatim Berkeley check failed: %s", e)
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

    # Step 3b: Check for pre-computed buyer scenario (instant response)
    precomputed = _state.db.get_precomputed_by_location(
        req.latitude, req.longitude, "buyer", max_distance_m=5,
    )
    if precomputed:
        prop = precomputed["property"]
        prop["neighborhood"] = neighborhood
        prediction = json.loads(precomputed["prediction_json"])
        comps = json.loads(precomputed.get("comparables_json") or "[]")
        return {
            "status": "prediction",
            "precomputed": True,
            "listing": _sale_to_listing(prop, neighborhood),
            "prediction": prediction,
            "comparables": comps,
        }

    # Step 4: Try to find an existing property sale near the clicked point
    nearest = _state.db.find_nearest_sale(req.latitude, req.longitude, max_distance_m=5)

    if nearest:
        prop = dict(nearest)
        prop["neighborhood"] = neighborhood  # ensure current geocoded neighborhood

        # If the DB record is missing key property details, try RentCast
        _key_fields = ("beds", "baths", "sqft", "property_type")
        if any(prop.get(f) is None for f in _key_fields):
            _enrich_detail = None
            address = prop.get("address")
            zip_code_val = prop.get("zip_code") or zip_code

            if _state.rentcast and _state.rentcast.enabled and address:
                _full_addr = _clean_address_for_rentcast(address, zip_code_val)
                _enrich_detail = _state.rentcast.lookup_property(address=_full_addr)

            if _enrich_detail:
                enriched = _enrich_detail.to_dict()
                for field in ("beds", "baths", "sqft", "lot_size_sqft",
                              "year_built", "property_type"):
                    if prop.get(field) is None and enriched.get(field) is not None:
                        prop[field] = enriched[field]
                logger.info(
                    "Enriched DB record for %s with property data: %s",
                    address, list(enriched.keys()),
                )

        result = model.predict_single(_state.db, prop)

        # Store in predictions cache
        prop.setdefault("latitude", req.latitude)
        prop.setdefault("longitude", req.longitude)
        prop.setdefault("zip_code", zip_code)
        _store_prediction_from_result(_state.db, result, prop, source="map-click")

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

    # Step 5: Resolve address via reverse geocode, then enrich via RentCast
    address = None
    prop_detail = None  # RentcastPropertyDetail
    last_sale_price, last_sale_date = None, None

    # 5a: Resolve address via Nominatim reverse geocode
    address = _reverse_geocode(req.latitude, req.longitude)

    # 5b: Enrich via RentCast
    if address and _state.rentcast and _state.rentcast.enabled:
        _rc_addr = f"{address}, Berkeley, CA {zip_code}".strip()
        _rc_detail = _state.rentcast.lookup_property(address=_rc_addr)
        if _rc_detail:
            prop_detail = _rc_detail
            if _rc_detail.last_sale_price:
                last_sale_price = _rc_detail.last_sale_price
            if _rc_detail.last_sale_date:
                last_sale_date = _rc_detail.last_sale_date
            logger.info("RentCast enriched map-click for %s", address)

    # Step 5e: If we have complete property data, run prediction immediately
    if prop_detail and prop_detail.is_complete:
        prop = prop_detail.to_dict()
        prop["neighborhood"] = neighborhood
        prop["zip_code"] = zip_code
        prop["latitude"] = req.latitude
        prop["longitude"] = req.longitude
        prop["address"] = address

        result = model.predict_single(_state.db, prop)

        # Store in predictions cache
        _store_prediction_from_result(_state.db, result, prop, source="map-click")

        analyzer = _state.get_analyzer()
        comps = analyzer.find_comparables(
            neighborhood=neighborhood,
            beds=prop.get("beds"),
            baths=prop.get("baths"),
            sqft=prop.get("sqft"),
            year_built=prop.get("year_built"),
        )

        # Persist RentCast sale history for future predictions & model training
        _persist_rentcast_sales(
            address=address,
            city="Berkeley",
            state="CA",
            zip_code=zip_code,
            latitude=req.latitude,
            longitude=req.longitude,
            neighborhood=neighborhood,
            detail=prop_detail,
        )

        # Collect building permits in background (Playwright, ~8-10s)
        if address:
            _collect_permits_background(address)

        return {
            "status": "prediction",
            "listing": _property_to_listing(
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

    # Enrich with partial property data for form pre-fill
    if prop_detail:
        location_info["property_prefill"] = prop_detail.to_dict()

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

    # Check for pre-computed development potential (instant response)
    precomputed = _state.db.get_precomputed_by_location(
        req.latitude, req.longitude, "buyer", max_distance_m=5,
    )
    if precomputed and precomputed.get("potential_json"):
        return json.loads(precomputed["potential_json"])

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

    # Resolve property details from DB + geocoder
    prop = _resolve_property_from_db(
        req.latitude, req.longitude,
        req.model_dump(exclude_none=True),
        _state.db, _state.geocoder,
    )

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

    # Check for pre-computed rental analysis (instant response)
    precomputed = _state.db.get_precomputed_by_location(
        req.latitude, req.longitude, "buyer", max_distance_m=5,
    )
    if precomputed and precomputed.get("rental_json"):
        return json.loads(precomputed["rental_json"])

    # Resolve property details from DB + geocoder
    prop = _resolve_property_from_db(
        req.latitude, req.longitude,
        req.model_dump(exclude_none=True),
        _state.db, _state.geocoder,
        extra_fields=("list_price",),
    )

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


# --- Investment Prospectus ---


@app.post("/api/property/prospectus")
def investment_prospectus(req: ProspectusRequest):
    """Generate an investment prospectus for a property.

    Looks up the property by address in the database, then runs the full
    prospectus pipeline: ML valuation, market context, development potential,
    rental/investment scenarios, and strategy recommendation.
    """
    if not _state or not _state.db:
        raise HTTPException(status_code=503, detail="Server not ready.")

    # Resolve address to a property record
    results = _state.db.search_properties(req.address, limit=1)
    if not results:
        raise HTTPException(status_code=404, detail=f"Property not found: '{req.address}'")

    prop = dict(results[0])

    from homebuyer.analysis.prospectus import ProspectusGenerator, prospectus_to_dict

    market_analyzer = _state.get_analyzer()
    prospectus_gen = ProspectusGenerator(
        db=_state.db,
        dev_calc=_state.dev_calc,
        rental_analyzer=_state.rental_analyzer,
        market_analyzer=market_analyzer,
        predict_fn=lambda prop_dict, source: _get_or_compute_prediction(prop_dict, source),
    )

    try:
        result = prospectus_gen.generate(
            properties=[prop],
            down_payment_pct=req.down_payment_pct,
            investment_horizon_years=req.investment_horizon_years,
            mode=req.mode,
        )
        return prospectus_to_dict(result)
    except Exception as e:
        logger.error("Prospectus generation failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Prospectus generation failed: {str(e)}"
        )


# --- Faketor Chat ---


class FaketorChatRequest(BaseModel):
    """Request body for Faketor chat endpoints.

    Pydantic v2 strict mode rejects int→str coercion, which can cause
    "Input should be a valid string" errors when property data has unexpected
    types (e.g. zip_code as an integer).  We use ``model_config`` to enable
    coercion so these edge cases are handled gracefully.
    """

    model_config = {"coerce_numbers_to_str": True}

    latitude: float
    longitude: float
    message: str
    history: list[dict] = []
    session_id: Optional[str] = None
    address: Optional[str] = None
    neighborhood: Optional[str] = None
    zip_code: Optional[str] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    # Accept floats from the frontend (property detail data may arrive as float)
    # and truncate to int so downstream code still sees integers.
    sqft: Optional[float] = None
    lot_size_sqft: Optional[float] = None
    year_built: Optional[float] = None
    property_type: Optional[str] = "Single Family Residential"
    property_category: Optional[str] = None  # sfr, condo, duplex, etc.


# ---------------------------------------------------------------------------
# Session-aware tool executor
# ---------------------------------------------------------------------------


def _make_session_tool_executor(working_set=None):
    """Create a tool executor that is session-aware.

    Wraps the base ``_faketor_tool_executor`` with:
    - Working set temp table injection for ``query_database``
    - ``undo_filter`` interception
    - Post-execution working set updates for ``search_properties`` and ``query_database``
    """
    from homebuyer.services.session_cache import SessionWorkingSet

    def executor(tool_name: str, tool_input: dict) -> str:
        # Intercept undo_filter
        if tool_name == "undo_filter" and working_set is not None:
            return _handle_undo_filter(working_set)

        # Intercept generate_investment_prospectus with from_working_set
        if (
            tool_name == "generate_investment_prospectus"
            and tool_input.get("from_working_set")
            and working_set is not None
            and working_set.count > 0
        ):
            # Inject working set property IDs as addresses for the prospectus
            ws_props = [prop.to_dict() for prop in working_set.properties.values()]
            addresses = [p.get("address", "") for p in ws_props if p.get("address")]
            if addresses:
                tool_input = {**tool_input, "addresses": addresses}
                del tool_input["from_working_set"]

        # For query_database with an active working set, inject temp table
        if (
            tool_name == "query_database"
            and working_set is not None
            and working_set.count > 0
        ):
            result_str = _execute_query_with_working_set(tool_input, working_set)
        # For update_working_set with SQL in narrow mode, inject temp table
        elif (
            tool_name == "update_working_set"
            and tool_input.get("sql")
            and tool_input.get("mode") == "narrow"
            and working_set is not None
            and working_set.count > 0
        ):
            result_str = _execute_update_working_set_with_temp_table(tool_input, working_set)
        else:
            result_str = _faketor_tool_executor(tool_name, tool_input)

        # Post-execution: update the working set if applicable
        if working_set is not None:
            _update_working_set(working_set, tool_name, tool_input, result_str)

        # Track discussed properties from per-property tool calls
        if working_set is not None and tool_name in _PER_PROPERTY_TOOLS:
            _track_discussed_property(working_set, tool_name, tool_input, result_str)

        return result_str

    return executor


def _handle_undo_filter(working_set) -> str:
    """Handle the undo_filter tool call."""
    layer = working_set.pop_filter()
    if layer is None:
        return json.dumps({
            "message": "No filters to undo. The working set is at its base state.",
            "working_set_count": working_set.count,
        })
    return json.dumps({
        "message": f"Undid filter: '{layer.description}'. Working set restored.",
        "removed_filter": layer.description,
        "working_set_count": working_set.count,
        "remaining_filters": len(working_set.filter_stack),
    })


def _execute_query_with_working_set(tool_input: dict, working_set) -> str:
    """Execute query_database with a _working_set temp table available."""
    if not _state or not _state.db:
        return json.dumps({"error": "Database not available"})

    sql = (tool_input.get("sql") or "").strip()
    explanation = tool_input.get("explanation", "")
    if not sql:
        return json.dumps({"error": "No SQL query provided"})

    # Safety: validate SQL (CREATE allowed for temp table)
    error = _validate_sql(sql, allow_create=True)
    if error:
        return json.dumps({"error": error})
    sql = _enforce_sql_limit(sql)

    logger.info("query_database (session, %d props): %s", working_set.count, sql)

    db = _state.db
    try:
        # Create temp table with working set IDs
        db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _working_set "
            "(property_id INTEGER PRIMARY KEY)"
        )
        db.execute("DELETE FROM _working_set")
        property_ids = working_set.get_property_ids()
        db.executemany(
            "INSERT INTO _working_set (property_id) VALUES (?) ON CONFLICT DO NOTHING",
            [(pid,) for pid in property_ids],
        )

        cursor = db.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(100)
        if db.is_postgres:
            results = [dict(r) for r in rows]
        else:
            results = [dict(zip(columns, row)) for row in rows]

        return safe_json_dumps({
            "query": sql,
            "columns": columns,
            "rows": results,
            "row_count": len(results),
            "explanation": explanation,
            "working_set_count": len(property_ids),
        })
    except Exception as e:
        error_msg = str(e)
        logger.warning("query_database (session) failed: %s", e, exc_info=True)
        # Rollback so the connection isn't stuck in an aborted transaction
        # (PostgreSQL rejects all queries after an error until rollback).
        try:
            db.conn.rollback()
        except Exception:
            pass
        return json.dumps({"error": f"SQL error: {error_msg}", "query": sql})
    finally:
        try:
            db.execute("DROP TABLE IF EXISTS _working_set")
        except Exception:
            try:
                db.conn.rollback()
            except Exception:
                pass


def _execute_update_working_set_with_temp_table(tool_input: dict, working_set) -> str:
    """Execute update_working_set with SQL mode and _working_set temp table.

    Used for narrow mode where the SQL references _working_set.
    """
    if not _state or not _state.db:
        return json.dumps({"error": "Database not available"})

    sql = (tool_input.get("sql") or "").strip()
    mode = tool_input.get("mode", "narrow")
    explanation = tool_input.get("explanation", "")
    requested_limit = min(tool_input.get("limit", 10), 25)

    if not sql:
        return json.dumps({"error": "No SQL query provided"})

    error = _validate_sql(sql, allow_create=True)
    if error:
        return json.dumps({"error": error})
    sql = _enforce_sql_limit(sql)

    logger.info("update_working_set (sql+temp, mode=%s, %d props): %s",
                mode, working_set.count, sql)

    db = _state.db
    try:
        # Create temp table with working set IDs
        db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _working_set "
            "(property_id INTEGER PRIMARY KEY)"
        )
        db.execute("DELETE FROM _working_set")
        property_ids = working_set.get_property_ids()
        db.executemany(
            "INSERT INTO _working_set (property_id) VALUES (?) ON CONFLICT DO NOTHING",
            [(pid,) for pid in property_ids],
        )

        cursor = db.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        if db.is_postgres:
            results = [dict(r) for r in rows]
        else:
            results = [dict(zip(columns, row)) for row in rows]

        return safe_json_dumps({
            "mode": mode,
            "source": "sql",
            "results": results[:requested_limit],
            "total_matching": len(results),
            "filters_applied": {"sql": sql, "explanation": explanation},
        })
    except Exception as e:
        error_msg = str(e)
        logger.warning("update_working_set (sql+temp) failed: %s", e, exc_info=True)
        try:
            db.conn.rollback()
        except Exception:
            pass
        return json.dumps({"error": f"SQL error: {error_msg}", "query": sql})
    finally:
        try:
            db.execute("DROP TABLE IF EXISTS _working_set")
        except Exception:
            try:
                db.conn.rollback()
            except Exception:
                pass


def _update_working_set(working_set, tool_name: str, tool_input: dict, result_str: str) -> None:
    """Update the session working set based on tool results."""
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return

    if isinstance(data, dict) and data.get("error"):
        return

    if tool_name == "search_properties":
        results = data.get("results", [])
        if not results:
            return
        filters = data.get("filters_applied", {})
        total_matching = data.get("total_matching", len(results))
        desc = _describe_search_filters(filters)

        # ADU/SB9 are post-filters (not SQL columns), so the lightweight
        # search can't reproduce them.  When either is active, use only
        # the already-filtered results for the working set.
        has_dev_filter = bool(
            tool_input.get("adu_eligible") or tool_input.get("sb9_eligible")
        )

        # If there are more matches than returned, fetch ALL for the working set
        # (but only when there are no dev-potential post-filters)
        _LIGHTWEIGHT_KEYS = {
            "neighborhoods", "zoning_classes", "zoning_pattern",
            "property_type", "property_category", "record_type",
            "ownership_type", "min_price", "max_price",
            "min_beds", "max_beds", "min_baths", "max_baths",
            "min_lot_sqft", "max_lot_sqft", "min_sqft", "max_sqft",
            "min_year_built", "max_year_built",
        }
        if total_matching > len(results) and _state and _state.db and not has_dev_filter:
            try:
                lightweight_filters = {
                    k: v for k, v in filters.items() if k in _LIGHTWEIGHT_KEYS
                }
                all_rows = _state.db.search_properties_lightweight(**lightweight_filters)
            except Exception as e:
                logger.warning("Lightweight search for working set failed: %s", e, exc_info=True)
                all_rows = results  # fallback to the 25

            if working_set.count == 0:
                working_set.set_properties(all_rows, desc, tool_name)
            else:
                new_ids = {r["id"] for r in all_rows if r.get("id")}
                working_set.push_filter(new_ids, desc, tool_name)
        else:
            # Results already contain everything (or dev-filter is active
            # and results are the authoritative post-filtered set)
            if working_set.count == 0:
                working_set.set_properties(results, desc, tool_name)
            else:
                new_ids = {r["id"] for r in results if r.get("id")}
                working_set.push_filter(new_ids, desc, tool_name)

    elif tool_name == "query_database":
        rows = data.get("rows", [])
        if not rows:
            return
        # Only update if results contain property IDs (integer "id" column)
        if not all(isinstance(r.get("id"), int) for r in rows if "id" in r):
            return
        ids_in_result = {r["id"] for r in rows if isinstance(r.get("id"), int)}
        if not ids_in_result:
            return
        explanation = data.get("explanation", "database query")
        if working_set.count == 0:
            # Initial population — need to fetch full property records from DB
            _populate_working_set_from_ids(working_set, ids_in_result, explanation, tool_name)
        else:
            working_set.push_filter(ids_in_result, explanation, tool_name)

    elif tool_name == "update_working_set":
        mode = data.get("mode", "replace")
        results = data.get("results", [])
        filters = data.get("filters_applied", {})
        total_matching = data.get("total_matching", len(results))
        desc = tool_input.get("explanation") or _describe_search_filters(filters)

        # ADU/SB9 are post-filters
        has_dev_filter = bool(
            tool_input.get("adu_eligible") or tool_input.get("sb9_eligible")
        )

        # For structured searches with more matches than returned,
        # fetch ALL for the working set via lightweight search
        _LIGHTWEIGHT_KEYS = {
            "neighborhoods", "zoning_classes", "zoning_pattern",
            "property_type", "property_category", "record_type",
            "ownership_type", "min_price", "max_price",
            "min_beds", "max_beds", "min_baths", "max_baths",
            "min_lot_sqft", "max_lot_sqft", "min_sqft", "max_sqft",
            "min_year_built", "max_year_built",
        }
        source = data.get("source", "structured")
        all_rows = results  # default: use the returned results

        if (
            source == "structured"
            and total_matching > len(results)
            and _state and _state.db
            and not has_dev_filter
        ):
            try:
                lightweight_filters = {
                    k: v for k, v in filters.items() if k in _LIGHTWEIGHT_KEYS
                }
                all_rows = _state.db.search_properties_lightweight(**lightweight_filters)
            except Exception as e:
                logger.warning("Lightweight search for working set failed: %s", e, exc_info=True)
                all_rows = results  # fallback

        if mode == "replace":
            working_set.set_properties(all_rows, desc, tool_name)

        elif mode == "narrow":
            if not results:
                # Narrow to empty — still push a filter so undo works
                working_set.push_filter(set(), desc, tool_name)
            else:
                new_ids = {r["id"] for r in all_rows if r.get("id")}
                working_set.push_filter(new_ids, desc, tool_name)

        elif mode == "expand":
            if results:
                # For expand, fetch full records for IDs not already in set
                ids_to_add = {
                    r["id"] for r in all_rows
                    if r.get("id") and r["id"] not in working_set.properties
                }
                if ids_to_add:
                    _expand_working_set_from_ids(
                        working_set, ids_to_add, desc, tool_name,
                    )


def _expand_working_set_from_ids(
    working_set, property_ids: set[int], description: str, source_tool: str,
) -> None:
    """Expand the working set by fetching new property records from the DB."""
    if not _state or not _state.db:
        return
    # Filter out IDs already in working set (safety check)
    new_ids = property_ids - set(working_set.properties.keys())
    if not new_ids:
        return

    _WS_FIELDS = (
        "id, address, neighborhood, beds, baths, sqft, building_sqft, "
        "lot_size_sqft, zoning_class, property_type, last_sale_price, year_built, "
        "latitude, longitude, property_category, record_type, lot_group_key, situs_unit"
    )
    _SQLITE_VAR_LIMIT = 900  # Stay under SQLite's default 999 limit

    try:
        rows: list[dict] = []
        id_list = list(new_ids)
        # Batch queries to avoid SQLite variable limit
        for i in range(0, len(id_list), _SQLITE_VAR_LIMIT):
            batch = id_list[i : i + _SQLITE_VAR_LIMIT]
            placeholders = ",".join("?" * len(batch))
            sql = f"SELECT {_WS_FIELDS} FROM properties WHERE id IN ({placeholders})"
            rows.extend(_state.db.fetchall(sql, batch))
        working_set.expand_properties(rows, description, source_tool)
    except Exception as e:
        logger.warning("Failed to expand working set from IDs: %s", e)


def _populate_working_set_from_ids(
    working_set, property_ids: set[int], description: str, source_tool: str,
) -> None:
    """Populate the working set by fetching property records from the DB."""
    if not _state or not _state.db:
        return

    _WS_FIELDS = (
        "id, address, neighborhood, beds, baths, sqft, building_sqft, "
        "lot_size_sqft, zoning_class, property_type, last_sale_price, year_built, "
        "latitude, longitude, property_category, record_type, lot_group_key, situs_unit"
    )
    _SQLITE_VAR_LIMIT = 900  # Stay under SQLite's default 999 limit

    try:
        rows: list[dict] = []
        id_list = list(property_ids)
        # Batch queries to avoid variable limit
        for i in range(0, len(id_list), _SQLITE_VAR_LIMIT):
            batch = id_list[i : i + _SQLITE_VAR_LIMIT]
            placeholders = ",".join("?" * len(batch))
            sql = f"SELECT {_WS_FIELDS} FROM properties WHERE id IN ({placeholders})"
            rows.extend(_state.db.fetchall(sql, batch))
        working_set.set_properties(rows, description, source_tool)
    except Exception as e:
        logger.warning("Failed to populate working set from IDs: %s", e)


def _describe_search_filters(filters: dict) -> str:
    """Generate a human-readable description of search_properties filters."""
    parts = []
    for key, val in filters.items():
        if val is None:
            continue
        label = key.replace("_", " ")
        if isinstance(val, list):
            parts.append(f"{label}: {', '.join(str(v) for v in val)}")
        else:
            parts.append(f"{label}: {val}")
    return "; ".join(parts) if parts else "all properties"


def _execute_update_working_set(tool_input: dict) -> str:
    """Execute the update_working_set tool.

    Handles both structured mode (filter params) and SQL mode.
    Returns search results in the same format as search_properties
    so the frontend can render property_search_results blocks.
    """
    if not _state or not _state.db:
        return json.dumps({"error": "Database not available"})

    mode = tool_input.get("mode", "replace")
    sql = (tool_input.get("sql") or "").strip()
    explanation = tool_input.get("explanation", "")
    requested_limit = min(tool_input.get("limit", 10), 25)
    adu_filter = tool_input.get("adu_eligible")
    sb9_filter = tool_input.get("sb9_eligible")

    if sql:
        # --- SQL mode ---
        error = _validate_sql(sql, allow_create=True)
        if error:
            return json.dumps({"error": error})
        sql = _enforce_sql_limit(sql)

        logger.info("update_working_set (sql, mode=%s): %s", mode, sql)
        try:
            cursor = _state.db.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchall()
            results = [dict(r) if hasattr(r, "keys") else dict(zip(columns, r)) for r in raw_rows]
        except Exception as e:
            logger.warning("update_working_set SQL failed: %s", e, exc_info=True)
            return json.dumps({"error": f"SQL error: {str(e)}", "query": sql})

        # ADU/SB9 post-filtering for SQL mode (if rows have dev potential)
        if adu_filter or sb9_filter:
            filtered = []
            for row in results:
                pot_raw = row.get("potential_json")
                if pot_raw:
                    try:
                        pot = json.loads(pot_raw) if isinstance(pot_raw, str) else pot_raw
                        adu = pot.get("adu", {})
                        sb9 = pot.get("sb9", {})
                        if adu_filter and not adu.get("eligible"):
                            continue
                        if sb9_filter and not sb9.get("eligible"):
                            continue
                    except (json.JSONDecodeError, TypeError):
                        continue
                elif adu_filter or sb9_filter:
                    continue  # Can't verify eligibility without dev data
                filtered.append(row)
            results = filtered

        return safe_json_dumps({
            "mode": mode,
            "source": "sql",
            "results": results[:requested_limit],
            "total_matching": len(results),
            "filters_applied": {"sql": sql, "explanation": explanation},
        })

    else:
        # --- Structured mode ---
        _search_filters = dict(
            neighborhoods=tool_input.get("neighborhoods"),
            zoning_classes=tool_input.get("zoning_classes"),
            zoning_pattern=tool_input.get("zoning_pattern"),
            property_type=tool_input.get("property_type"),
            property_category=tool_input.get("property_category"),
            record_type=tool_input.get("record_type"),
            ownership_type=tool_input.get("ownership_type"),
            min_price=tool_input.get("min_price"),
            max_price=tool_input.get("max_price"),
            min_beds=tool_input.get("min_beds"),
            max_beds=tool_input.get("max_beds"),
            min_baths=tool_input.get("min_baths"),
            max_baths=tool_input.get("max_baths"),
            min_lot_sqft=tool_input.get("min_lot_sqft"),
            max_lot_sqft=tool_input.get("max_lot_sqft"),
            min_sqft=tool_input.get("min_sqft"),
            max_sqft=tool_input.get("max_sqft"),
            min_year_built=tool_input.get("min_year_built"),
            max_year_built=tool_input.get("max_year_built"),
        )

        # Get true total count
        total_matching = _state.db.count_properties_advanced(**_search_filters)

        # Over-fetch when post-filtering on dev potential flags
        sql_limit = requested_limit * 4 if (adu_filter or sb9_filter) else requested_limit

        rows = _state.db.search_properties_advanced(
            **_search_filters,
            limit=sql_limit,
        )

        if not rows:
            return json.dumps({
                "mode": mode,
                "source": "structured",
                "results": [],
                "total_found": 0,
                "total_matching": total_matching,
                "message": "No properties match your criteria.",
            })

        results = []
        for row in rows:
            # Parse development potential from precomputed JSON
            dev_summary = None
            potential_raw = row.get("potential_json")
            if potential_raw:
                try:
                    pot = json.loads(potential_raw)
                    adu = pot.get("adu") or {}
                    sb9 = pot.get("sb9") or {}
                    units = pot.get("units") or {}
                    zoning = pot.get("zoning") or {}
                    dev_summary = {
                        "adu_eligible": adu.get("eligible", False),
                        "adu_max_sqft": adu.get("max_adu_sqft"),
                        "sb9_eligible": sb9.get("eligible", False),
                        "sb9_can_split": sb9.get("can_split", False),
                        "sb9_max_units": sb9.get("max_total_units"),
                        "effective_max_units": units.get("effective_max_units"),
                        "middle_housing_eligible": units.get("middle_housing_eligible", False),
                        "zone_class": zoning.get("zone_class"),
                        "zone_desc": zoning.get("zone_desc"),
                    }
                except (json.JSONDecodeError, TypeError):
                    pass

            # Post-filter on ADU/SB9 eligibility
            if adu_filter and (not dev_summary or not dev_summary.get("adu_eligible")):
                continue
            if sb9_filter and (not dev_summary or not dev_summary.get("sb9_eligible")):
                continue

            # Parse predicted price
            predicted_price = None
            prediction_confidence = None
            pred_raw = row.get("prediction_json")
            if pred_raw:
                try:
                    pred = json.loads(pred_raw)
                    predicted_price = pred.get("predicted_price")
                    prediction_confidence = pred.get("prediction_confidence")
                except (json.JSONDecodeError, TypeError):
                    pass

            # Data quality flags
            r_sqft = row.get("sqft")
            r_building_sqft = row.get("building_sqft")
            r_lot_size_sqft = row.get("lot_size_sqft")

            data_quality = "normal"
            data_quality_note = None
            if r_building_sqft and r_sqft and r_sqft > 0:
                try:
                    bld_ratio = float(r_building_sqft) / float(r_sqft)
                    if bld_ratio > 3:
                        data_quality = "per_unit_mismatch"
                        data_quality_note = (
                            f"Per-unit features likely: building sqft ({r_building_sqft:,}) "
                            f"is {bld_ratio:.1f}x the listing sqft ({r_sqft:,})."
                        )
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
            if data_quality == "normal" and row.get("property_type") == "Multi-Family (5+ Unit)":
                data_quality = "mf5_limited_data"
                data_quality_note = "Multi-family 5+ unit — limited comparable data."

            building_to_lot_ratio = None
            if r_building_sqft and r_lot_size_sqft and r_lot_size_sqft > 0:
                try:
                    building_to_lot_ratio = round(
                        float(r_building_sqft) / float(r_lot_size_sqft), 3
                    )
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

            r_record_type = row.get("record_type")
            if data_quality == "normal" and r_record_type == "unit" and (not r_lot_size_sqft or r_lot_size_sqft == 0):
                data_quality = "shared_lot_no_size"
                data_quality_note = "Condo unit with shared lot — lot size may be zero or shared."

            results.append({
                "id": row.get("id"),
                "address": row.get("address"),
                "neighborhood": row.get("neighborhood"),
                "zip_code": row.get("zip_code"),
                "zoning_class": row.get("zoning_class"),
                "beds": row.get("beds"),
                "baths": row.get("baths"),
                "sqft": row.get("sqft"),
                "building_sqft": r_building_sqft,
                "lot_size_sqft": r_lot_size_sqft,
                "building_to_lot_ratio": building_to_lot_ratio,
                "year_built": row.get("year_built"),
                "property_type": row.get("property_type"),
                "property_category": row.get("property_category"),
                "record_type": r_record_type,
                "situs_unit": row.get("situs_unit"),
                "lot_group_key": row.get("lot_group_key"),
                "last_sale_price": row.get("last_sale_price"),
                "last_sale_date": row.get("last_sale_date"),
                "predicted_price": predicted_price,
                "prediction_confidence": prediction_confidence,
                "data_quality": data_quality,
                "data_quality_note": data_quality_note,
                "development": dev_summary,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
            })

            if len(results) >= requested_limit:
                break

        filters_applied = {
            k: v for k, v in tool_input.items()
            if v is not None and k not in ("limit", "mode", "sql", "explanation")
        }

        return safe_json_dumps({
            "mode": mode,
            "source": "structured",
            "results": results,
            "total_found": len(results),
            "total_matching": total_matching,
            "filters_applied": filters_applied,
        })


def _faketor_tool_executor(tool_name: str, tool_input: dict) -> str:
    """Execute a Faketor tool and return JSON string result."""

    if tool_name == "get_development_potential":
        if not _state or not _state.dev_calc:
            return json.dumps({"error": "Development calculator not available"})
        lat = tool_input["latitude"]
        lon = tool_input["longitude"]
        property_id = tool_input.get("property_id")

        # --- Direct property_id lookup (preferred — avoids lat/lon mismatch) ---
        if property_id and _state.db:
            _pc = _state.db.get_precomputed_scenario(property_id, "buyer")
            if _pc and _pc.get("potential_json"):
                logger.info(
                    "Precomputed HIT for development potential via property_id=%s",
                    property_id,
                )
                return _pc["potential_json"]

        # --- Fallback: lat/lon proximity lookup ---
        _pc = _state.db.get_precomputed_by_location(lat, lon, "buyer", max_distance_m=5)
        if _pc and _pc.get("potential_json"):
            logger.info("Precomputed HIT for development potential via lat/lon")
            return _pc["potential_json"]

        lot_size, sqft, address = None, None, tool_input.get("address")
        record_type, lot_group_key = None, None
        if _state.db:
            nearest = _state.db.find_nearest_sale(lat, lon, max_distance_m=50)
            if nearest:
                lot_size = nearest.get("lot_size_sqft")
                sqft = nearest.get("sqft")
                if not address:
                    address = nearest.get("address")
            # Look up record_type and lot_group_key from properties table
            prop_row = _state.db.fetchone(
                "SELECT record_type, lot_group_key, building_sqft, property_category "
                "FROM properties "
                "WHERE ABS(latitude - ?) < 0.0002 AND ABS(longitude - ?) < 0.0002 "
                "LIMIT 1",
                (lat, lon),
            )
            if prop_row:
                record_type = prop_row["record_type"]
                lot_group_key = prop_row["lot_group_key"]
                # Use building_sqft from properties if we don't have sqft from sale
                if sqft is None and prop_row["building_sqft"]:
                    sqft = prop_row["building_sqft"]
                property_category = prop_row.get("property_category")
            else:
                property_category = None
        else:
            property_category = None
        result = _state.dev_calc.compute(
            lat=lat, lon=lon,
            lot_size_sqft=lot_size, sqft=sqft,
            address=address,
            record_type=record_type,
            lot_group_key=lot_group_key,
            property_category=property_category,
        )
        return safe_json_dumps(_development_potential_to_dict(result))

    elif tool_name == "get_improvement_simulation":
        model = _require_model()
        if not _state or not _state.dev_calc:
            return json.dumps({"error": "Development calculator not available"})
        prop = _resolve_property_from_db(
            tool_input["latitude"], tool_input["longitude"],
            tool_input, _state.db, _state.geocoder,
        )
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
            cat_ratio = ind["roi_ratio"]
            categories.append({
                "category": ind["category"],
                "avg_cost": ind["estimated_cost"],
                "ml_delta": ind["predicted_delta"],
                "roi_multiplier": cat_ratio,
                "roi_note": _format_roi_note(cat_ratio, ind["estimated_cost"], ind["predicted_delta"]),
                "market_premium_pct": roi.avg_ppsf_premium_pct if roi else None,
            })
        total_ratio = sim["roi_ratio"]
        return json.dumps({
            "current_price": sim["current_price"],
            "improved_price": sim["improved_price"],
            "total_delta": sim["total_delta"],
            "total_cost": sim["total_cost"],
            "roi_multiplier": total_ratio,
            "roi_note": _format_roi_note(total_ratio, sim["total_cost"], sim["total_delta"]),
            "categories": categories,
        })

    elif tool_name == "get_comparable_sales":
        # Check precomputed cache first
        lat = tool_input.get("latitude")
        lon = tool_input.get("longitude")
        if lat and lon:
            _pc = _state.db.get_precomputed_by_location(lat, lon, "buyer", max_distance_m=5)
            if _pc and _pc.get("comparables_json"):
                logger.info("Precomputed HIT for comparable sales")
                return _pc["comparables_json"]

        analyzer = _state.get_analyzer()
        comps = analyzer.find_comparables(
            neighborhood=tool_input["neighborhood"],
            beds=tool_input.get("beds"),
            baths=tool_input.get("baths"),
            sqft=tool_input.get("sqft"),
            year_built=tool_input.get("year_built"),
            property_type=tool_input.get("property_type"),
        )
        return safe_json_dumps([_comp_to_dict(c) for c in comps[:7]])

    elif tool_name == "get_neighborhood_stats":
        neighborhood = tool_input["neighborhood"]
        years = tool_input.get("years", 2)
        cache_key = f"neighborhood_stats:{neighborhood}:{years}"
        cached = _state.cache_get(cache_key)
        if cached:
            logger.info("TTL cache HIT for %s", cache_key)
            return safe_json_dumps(cached)
        analyzer = _state.get_analyzer()
        from dataclasses import asdict
        stats = analyzer.get_neighborhood_stats(neighborhood, lookback_years=years)
        result_dict = _neighborhood_stats_to_dict(stats)
        _state.cache_set(cache_key, result_dict)
        logger.info("TTL cache MISS for %s — stored", cache_key)
        return safe_json_dumps(result_dict)

    elif tool_name == "get_market_summary":
        cache_key = "market_summary"
        cached = _state.cache_get(cache_key)
        if cached:
            logger.info("TTL cache HIT for %s", cache_key)
            return safe_json_dumps(cached)
        analyzer = _state.get_analyzer()
        result_dict = analyzer.generate_summary_report()
        _state.cache_set(cache_key, result_dict)
        logger.info("TTL cache MISS for %s — stored", cache_key)
        return safe_json_dumps(result_dict)

    elif tool_name == "get_price_prediction":
        return safe_json_dumps(
            _get_or_compute_prediction(tool_input, source="chat"),
        )

    elif tool_name == "estimate_sell_vs_hold":
        analyzer = _state.get_analyzer()

        # Owner-context overrides
        purchase_price = tool_input.get("purchase_price")
        purchase_date = tool_input.get("purchase_date")
        mortgage_rate_override = tool_input.get("mortgage_rate")
        current_value_override = tool_input.get("current_value_override")

        # Reuse cached prediction (or override with user-stated value)
        if current_value_override:
            current_value = int(current_value_override)
            pred_dict = {"price_lower": current_value, "price_upper": current_value}
        else:
            pred_dict = _get_or_compute_prediction(tool_input, source="chat")
            current_value = pred_dict["predicted_price"]

        # Get neighborhood YoY appreciation
        neighborhood = tool_input.get("neighborhood", "Berkeley")
        stats = analyzer.get_neighborhood_stats(neighborhood, lookback_years=2)
        yoy_pct = stats.yoy_price_change_pct or 3.0  # default 3% if unknown

        # Get current market conditions
        market = analyzer.generate_summary_report()
        mortgage_rate = mortgage_rate_override
        if mortgage_rate is None and market and market.get("current_market"):
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
            scenario_data = {
                "projected_value": projected,
                "appreciation_pct": round((appreciation - 1) * 100, 1),
                "gross_gain": gain,
                "estimated_sell_costs": sell_costs,
                "net_gain": net_gain,
            }
            # Add equity-from-purchase if owner context
            if purchase_price:
                equity_from_purchase = projected - int(purchase_price)
                scenario_data["equity_from_purchase"] = equity_from_purchase
            scenarios[f"{years}yr"] = scenario_data

        # Use RentalAnalyzer for data-driven rent estimate
        beds = int(tool_input.get("beds") or 3)
        # Use purchase_price for expense basis if owner
        expense_basis = int(purchase_price) if purchase_price else current_value
        rent_est = _state.rental_analyzer.estimate_rent(
            beds=beds,
            baths=float(tool_input.get("baths") or 2.0),
            sqft=tool_input.get("sqft"),
            neighborhood=neighborhood,
            property_value=current_value,
        )
        expenses = _state.rental_analyzer.calculate_expenses(
            expense_basis, rent_est.annual_rent,
        )
        noi = rent_est.annual_rent - expenses.total_annual
        cap_rate = round(noi / current_value * 100, 2) if current_value > 0 else 0
        price_to_rent = round(current_value / rent_est.annual_rent, 1) if rent_est.annual_rent > 0 else 0

        result = {
            "current_predicted_value": current_value,
            "confidence_range": [pred_dict.get("price_lower", current_value), pred_dict.get("price_upper", current_value)],
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
        }
        # Include owner context if provided
        if purchase_price:
            pp = int(purchase_price)
            equity = current_value - pp
            result["purchase_price"] = pp
            result["current_equity_gain"] = equity
            if equity >= 0:
                result["equity_note"] = (
                    f"Property has gained ${equity:,.0f} in value since "
                    f"purchase (bought at ${pp:,.0f}, now worth ${current_value:,.0f})"
                )
            else:
                result["equity_note"] = (
                    f"Property has lost ${abs(equity):,.0f} in value since "
                    f"purchase (bought at ${pp:,.0f}, now worth ${current_value:,.0f})"
                )
        if purchase_date:
            result["purchase_date"] = purchase_date

        return safe_json_dumps(result)

    elif tool_name == "estimate_rental_income":
        # Owner-context overrides
        purchase_price = tool_input.get("purchase_price")
        current_value_override = tool_input.get("current_value_override")
        mortgage_rate_override = tool_input.get("mortgage_rate")

        # Check precomputed cache (buyer scenario, no owner overrides)
        if not purchase_price and not current_value_override and not mortgage_rate_override:
            _pc = _state.db.get_precomputed_by_location(
                tool_input["latitude"], tool_input["longitude"], "buyer", max_distance_m=5,
            )
            if _pc and _pc.get("rental_json"):
                logger.info("Precomputed HIT for rental income estimate")
                full_rental = json.loads(_pc["rental_json"])
                # Extract the as-is scenario from full rental analysis
                scenarios = full_rental.get("scenarios", [])
                as_is = next((s for s in scenarios if s.get("scenario_name") == "Rent As-Is"), None)
                if as_is:
                    return safe_json_dumps(as_is)

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
        # Inject owner context into property dict
        if purchase_price:
            prop["purchase_price"] = int(purchase_price)
        if tool_input.get("purchase_date"):
            prop["purchase_date"] = tool_input["purchase_date"]
        if current_value_override:
            prop["list_price"] = int(current_value_override)  # _resolve_property_value picks up list_price first

        from homebuyer.analysis.rental_analysis import _scenario_to_dict
        scenario = _state.rental_analyzer.build_scenario_as_is(
            prop,
            down_payment_pct=tool_input.get("down_payment_pct", 20.0),
            rate_override=mortgage_rate_override,
        )
        return safe_json_dumps(_scenario_to_dict(scenario))

    elif tool_name == "analyze_investment_scenarios":
        # Owner-context overrides
        purchase_price = tool_input.get("purchase_price")
        current_value_override = tool_input.get("current_value_override")
        mortgage_rate_override = tool_input.get("mortgage_rate")

        # Check precomputed cache (buyer scenario, no owner overrides)
        if not purchase_price and not current_value_override and not mortgage_rate_override:
            _pc = _state.db.get_precomputed_by_location(
                tool_input["latitude"], tool_input["longitude"], "buyer", max_distance_m=5,
            )
            if _pc and _pc.get("rental_json"):
                logger.info("Precomputed HIT for investment scenarios")
                return _pc["rental_json"]

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
        # Inject owner context into property dict
        if purchase_price:
            prop["purchase_price"] = int(purchase_price)
        if tool_input.get("purchase_date"):
            prop["purchase_date"] = tool_input["purchase_date"]
        if current_value_override:
            prop["list_price"] = int(current_value_override)  # _resolve_property_value picks up list_price first

        # Resolve property_category for guardrail checks
        inv_property_category = tool_input.get("property_category")
        if not inv_property_category and _state.db:
            try:
                inv_lat, inv_lon = tool_input["latitude"], tool_input["longitude"]
                _delta = 50 / 111_139.0
                _pr = _state.db.fetchone(
                    "SELECT property_category FROM properties "
                    "WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ? LIMIT 1",
                    (inv_lat - _delta, inv_lat + _delta, inv_lon - _delta, inv_lon + _delta),
                )
                if _pr:
                    inv_property_category = _pr["property_category"]
            except Exception:
                pass

        from homebuyer.analysis.rental_analysis import rental_analysis_to_dict
        result = _state.rental_analyzer.analyze(
            prop,
            down_payment_pct=tool_input.get("down_payment_pct", 20.0),
            self_managed=tool_input.get("self_managed", True),
            rate_override=mortgage_rate_override,
            property_category=inv_property_category,
        )
        return safe_json_dumps(rental_analysis_to_dict(result))

    elif tool_name == "generate_investment_prospectus":
        if not _state or not _state.db:
            return json.dumps({"error": "Database not available"})

        addresses_input = tool_input.get("addresses", [])
        # Support single address string as well as list
        if isinstance(addresses_input, str):
            addresses_input = [addresses_input]
        if not addresses_input:
            return json.dumps({"error": "No addresses provided for prospectus generation"})

        down_pct = tool_input.get("down_payment_pct", 20.0)
        horizon = tool_input.get("investment_horizon_years", 5)
        mode = tool_input.get("mode")  # None = auto-detect

        # Resolve each address to a property dict from the database
        properties = []
        for addr in addresses_input:
            results = _state.db.search_properties(addr, limit=1)
            if not results:
                return json.dumps({"error": f"Property not found: '{addr}'"})
            prop = dict(results[0])
            properties.append(prop)

        # Build the ProspectusGenerator with the required dependencies
        from homebuyer.analysis.prospectus import ProspectusGenerator, prospectus_to_dict

        market_analyzer = _state.get_analyzer()
        prospectus_gen = ProspectusGenerator(
            db=_state.db,
            dev_calc=_state.dev_calc,
            rental_analyzer=_state.rental_analyzer,
            market_analyzer=market_analyzer,
            predict_fn=lambda prop_dict, source: _get_or_compute_prediction(prop_dict, source),
        )

        try:
            result = prospectus_gen.generate(
                properties=properties,
                down_payment_pct=down_pct,
                investment_horizon_years=horizon,
                mode=mode,
            )
            return safe_json_dumps(prospectus_to_dict(result))
        except Exception as e:
            logger.error("Prospectus generation failed: %s", e, exc_info=True)
            return json.dumps({"error": f"Prospectus generation failed: {str(e)}"})

    elif tool_name == "lookup_property":
        if not _state or not _state.db:
            return json.dumps({"error": "Database not available"})
        address_query = tool_input.get("address", "")
        results = _state.db.search_properties(address_query, limit=3)
        if not results:
            return json.dumps({"error": f"No properties found matching '{address_query}'"})
        # Return the best match with all details
        best = dict(results[0])

        # On-demand enrichment if key fields are missing
        _key_fields = ("beds", "baths", "sqft", "property_type")
        if any(best.get(f) is None for f in _key_fields):
            _enrich_detail = None
            address = best.get("address")
            zip_code_val = best.get("zip_code", "")

            if _state.rentcast and _state.rentcast.enabled and address:
                _full_addr = _clean_address_for_rentcast(address, zip_code_val)
                _enrich_detail = _state.rentcast.lookup_property(address=_full_addr)

            if _enrich_detail:
                enriched = _enrich_detail.to_dict()
                for field_name in ("beds", "baths", "sqft", "lot_size_sqft",
                                   "year_built", "property_type",
                                   "last_sale_price", "last_sale_date"):
                    if best.get(field_name) is None and enriched.get(field_name) is not None:
                        best[field_name] = enriched[field_name]
                # Persist enrichment to DB so future lookups are faster
                try:
                    _state.db.update_properties_enrichment_batch([{
                        "id": best["id"],
                        "rentcast_enriched": True,
                        **{k: enriched[k] for k in ("beds", "baths", "sqft",
                           "year_built", "property_type",
                           "last_sale_price", "last_sale_date")
                           if enriched.get(k) is not None},
                    }])
                except Exception as e:
                    logger.warning("Failed to persist RentCast enrichment for %s: %s", address, e)
                logger.info(
                    "On-demand RentCast enrichment for %s: found %s",
                    address,
                    [k for k in _key_fields if best.get(k) is not None],
                )

        return safe_json_dumps({
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
            "enriched": bool(best.get("rentcast_enriched")),
        })

    elif tool_name == "search_properties":
        if not _state or not _state.db:
            return json.dumps({"error": "Database not available"})

        requested_limit = min(tool_input.get("limit", 10), 25)
        adu_filter = tool_input.get("adu_eligible")
        sb9_filter = tool_input.get("sb9_eligible")

        # Shared filter kwargs for both count and search
        _search_filters = dict(
            neighborhoods=tool_input.get("neighborhoods"),
            zoning_classes=tool_input.get("zoning_classes"),
            zoning_pattern=tool_input.get("zoning_pattern"),
            property_type=tool_input.get("property_type"),
            property_category=tool_input.get("property_category"),
            record_type=tool_input.get("record_type"),
            ownership_type=tool_input.get("ownership_type"),
            min_price=tool_input.get("min_price"),
            max_price=tool_input.get("max_price"),
            min_beds=tool_input.get("min_beds"),
            max_beds=tool_input.get("max_beds"),
            min_baths=tool_input.get("min_baths"),
            max_baths=tool_input.get("max_baths"),
            min_lot_sqft=tool_input.get("min_lot_sqft"),
            max_lot_sqft=tool_input.get("max_lot_sqft"),
            min_sqft=tool_input.get("min_sqft"),
            max_sqft=tool_input.get("max_sqft"),
            min_year_built=tool_input.get("min_year_built"),
            max_year_built=tool_input.get("max_year_built"),
        )

        # Get true total count (before LIMIT)
        total_matching = _state.db.count_properties_advanced(**_search_filters)

        # Over-fetch when post-filtering on dev potential flags
        sql_limit = requested_limit * 4 if (adu_filter or sb9_filter) else requested_limit

        rows = _state.db.search_properties_advanced(
            **_search_filters,
            limit=sql_limit,
        )

        if not rows:
            return json.dumps({
                "results": [],
                "total_found": 0,
                "total_matching": total_matching,
                "message": "No properties match your criteria. Try broadening your search.",
            })

        results = []
        for row in rows:
            # Parse development potential from precomputed JSON
            dev_summary = None
            potential_raw = row.get("potential_json")
            if potential_raw:
                try:
                    pot = json.loads(potential_raw)
                    adu = pot.get("adu") or {}
                    sb9 = pot.get("sb9") or {}
                    units = pot.get("units") or {}
                    zoning = pot.get("zoning") or {}
                    dev_summary = {
                        "adu_eligible": adu.get("eligible", False),
                        "adu_max_sqft": adu.get("max_adu_sqft"),
                        "sb9_eligible": sb9.get("eligible", False),
                        "sb9_can_split": sb9.get("can_split", False),
                        "sb9_max_units": sb9.get("max_total_units"),
                        "effective_max_units": units.get("effective_max_units"),
                        "middle_housing_eligible": units.get("middle_housing_eligible", False),
                        "zone_class": zoning.get("zone_class"),
                        "zone_desc": zoning.get("zone_desc"),
                    }
                except (json.JSONDecodeError, TypeError):
                    pass

            # Post-filter on ADU/SB9 eligibility
            if adu_filter and (not dev_summary or not dev_summary.get("adu_eligible")):
                continue
            if sb9_filter and (not dev_summary or not dev_summary.get("sb9_eligible")):
                continue

            # Parse predicted price and confidence from precomputed JSON
            predicted_price = None
            prediction_confidence = None
            pred_raw = row.get("prediction_json")
            if pred_raw:
                try:
                    pred = json.loads(pred_raw)
                    predicted_price = pred.get("predicted_price")
                    prediction_confidence = pred.get("prediction_confidence")
                except (json.JSONDecodeError, TypeError):
                    pass

            # Compute data quality flag
            r_sqft = row.get("sqft")
            r_building_sqft = row.get("building_sqft")
            r_lot_size_sqft = row.get("lot_size_sqft")

            data_quality = "normal"
            data_quality_note = None
            if r_building_sqft and r_sqft and r_sqft > 0:
                try:
                    bld_ratio = float(r_building_sqft) / float(r_sqft)
                    if bld_ratio > 3:
                        data_quality = "per_unit_mismatch"
                        data_quality_note = (
                            f"Per-unit features likely: building sqft ({r_building_sqft:,}) "
                            f"is {bld_ratio:.1f}x the listing sqft ({r_sqft:,}). "
                            "Assessor data may reflect per-unit values."
                        )
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
            if data_quality == "normal" and row.get("property_type") == "Multi-Family (5+ Unit)":
                data_quality = "mf5_limited_data"
                data_quality_note = "Multi-family 5+ unit — limited comparable data."

            # Pre-compute building-to-lot ratio using correct building_sqft
            building_to_lot_ratio = None
            if r_building_sqft and r_lot_size_sqft and r_lot_size_sqft > 0:
                try:
                    building_to_lot_ratio = round(
                        float(r_building_sqft) / float(r_lot_size_sqft), 3
                    )
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

            # Condo shared-lot data quality flag
            r_record_type = row.get("record_type")
            if data_quality == "normal" and r_record_type == "unit" and (not r_lot_size_sqft or r_lot_size_sqft == 0):
                data_quality = "shared_lot_no_size"
                data_quality_note = "Condo unit with shared lot — lot size may be zero or shared across units."

            results.append({
                "id": row.get("id"),
                "address": row.get("address"),
                "neighborhood": row.get("neighborhood"),
                "zip_code": row.get("zip_code"),
                "zoning_class": row.get("zoning_class"),
                "beds": row.get("beds"),
                "baths": row.get("baths"),
                "sqft": row.get("sqft"),
                "building_sqft": r_building_sqft,
                "lot_size_sqft": r_lot_size_sqft,
                "building_to_lot_ratio": building_to_lot_ratio,
                "year_built": row.get("year_built"),
                "property_type": row.get("property_type"),
                "property_category": row.get("property_category"),
                "record_type": r_record_type,
                "situs_unit": row.get("situs_unit"),
                "lot_group_key": row.get("lot_group_key"),
                "last_sale_price": row.get("last_sale_price"),
                "last_sale_date": row.get("last_sale_date"),
                "predicted_price": predicted_price,
                "prediction_confidence": prediction_confidence,
                "data_quality": data_quality,
                "data_quality_note": data_quality_note,
                "development": dev_summary,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
            })

            if len(results) >= requested_limit:
                break

        # Build filters_applied — include dev filters so the working set
        # descriptor mentions them, but exclude 'limit' (pagination detail)
        filters_applied = {
            k: v for k, v in tool_input.items()
            if v is not None and k != "limit"
        }

        return safe_json_dumps({
            "results": results,
            "total_found": len(results),
            "total_matching": total_matching,
            "filters_applied": filters_applied,
        })

    elif tool_name == "update_working_set":
        return _execute_update_working_set(tool_input)

    elif tool_name == "lookup_permits":
        if not _state or not _state.db:
            return json.dumps({"error": "Database not available"})
        address = tool_input.get("address", "")
        limit = min(tool_input.get("limit", 20), 50)
        permits = _state.db.lookup_permits_by_address(address, limit=limit)
        if not permits:
            return json.dumps({
                "permits": [],
                "total": 0,
                "address": address,
                "note": "No building permits found for this address.",
            })
        return safe_json_dumps({
            "permits": permits,
            "total": len(permits),
            "address": address,
        })

    elif tool_name == "lookup_regulation":
        from homebuyer.services.berkeley_regulations import lookup_regulation
        result = lookup_regulation(
            tool_input.get("topic", ""),
            tool_input.get("zone_code"),
        )
        return safe_json_dumps(result)

    elif tool_name == "lookup_glossary_term":
        from homebuyer.services.glossary import lookup_glossary_term
        result = lookup_glossary_term(
            tool_input.get("topic", ""),
            tool_input.get("category"),
        )
        return safe_json_dumps(result)

    elif tool_name == "query_database":
        if not _state or not _state.db:
            return json.dumps({"error": "Database not available"})
        sql = (tool_input.get("sql") or "").strip()
        explanation = tool_input.get("explanation", "")
        if not sql:
            return json.dumps({"error": "No SQL query provided"})

        # Safety: validate SQL (no CREATE allowed in non-session path)
        error = _validate_sql(sql)
        if error:
            return json.dumps({"error": error})
        sql = _enforce_sql_limit(sql)

        logger.info("query_database: %s | explanation: %s", sql, explanation)

        try:
            cursor = _state.db.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchmany(100)  # Hard cap at 100 rows
            results = [dict(r) if hasattr(r, "keys") else dict(zip(columns, r)) for r in raw_rows]

            return safe_json_dumps({
                "query": sql,
                "columns": columns,
                "rows": results,
                "row_count": len(results),
                "explanation": explanation,
            })
        except Exception as e:
            error_msg = str(e)
            logger.warning("query_database failed: %s", e, exc_info=True)
            try:
                _state.db.conn.rollback()
            except Exception:
                pass
            return json.dumps({"error": f"SQL error: {error_msg}", "query": sql})

    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})


def _resolve_faketor_context(req: FaketorChatRequest) -> dict:
    """Resolve property context from request + DB for Faketor chat."""
    # Truncate float→int for fields that downstream code treats as int
    _sqft = int(req.sqft) if req.sqft is not None else None
    _lot = int(req.lot_size_sqft) if req.lot_size_sqft is not None else None
    _yr = int(req.year_built) if req.year_built is not None else None

    overrides = {
        k: v for k, v in {
            "neighborhood": req.neighborhood,
            "sqft": _sqft,
            "lot_size_sqft": _lot,
            "beds": req.beds,
            "baths": req.baths,
            "year_built": _yr,
            "address": req.address,
            "zip_code": req.zip_code,
            "property_type": req.property_type,
        }.items() if v is not None
    }

    prop = _resolve_property_from_db(
        req.latitude, req.longitude,
        overrides, _state.db, _state.geocoder,
    )

    # Enrich property_category from properties table if not provided
    property_category = req.property_category
    if not property_category and _state.db:
        try:
            delta = 50 / 111_139.0  # ~50m bounding box
            row = _state.db.fetchone(
                """SELECT property_category, record_type
                   FROM properties
                   WHERE latitude BETWEEN ? AND ?
                     AND longitude BETWEEN ? AND ?
                   LIMIT 1""",
                (req.latitude - delta, req.latitude + delta,
                 req.longitude - delta, req.longitude + delta),
            )
            if row:
                property_category = row["property_category"]
        except Exception:
            pass

    prop["property_category"] = property_category
    return prop


@app.post("/api/faketor/chat")
def faketor_chat(req: FaketorChatRequest):
    """Chat with Faketor, the AI real estate advisor."""
    if not _state:
        raise HTTPException(status_code=503, detail="Server not initialized")

    # Resolve session working set
    working_set = None
    if req.session_id:
        working_set = _state.sessions.get_or_create(req.session_id)

    property_context = _resolve_faketor_context(req)
    tool_executor = _make_session_tool_executor(working_set)

    result = _state.faketor.chat(
        message=req.message,
        history=req.history,
        property_context=property_context,
        tool_executor=tool_executor,
        working_set_descriptor=working_set.get_descriptor() if working_set else "",
    )

    # Attach working set metadata for the frontend sidebar
    # Always emit — even when count is 0 — so the frontend can sync.
    if working_set is not None:
        result["working_set"] = _build_working_set_metadata(working_set, req.session_id)

    return result


@app.post("/api/faketor/chat/stream")
def faketor_chat_stream(req: FaketorChatRequest):
    """SSE streaming version of Faketor chat."""
    if not _state:
        raise HTTPException(status_code=503, detail="Server not initialized")

    # Resolve session working set
    working_set = None
    if req.session_id:
        working_set = _state.sessions.get_or_create(req.session_id)

    property_context = _resolve_faketor_context(req)
    tool_executor = _make_session_tool_executor(working_set)

    def event_generator():
        for event in _state.faketor.chat_stream(
            message=req.message,
            history=req.history,
            property_context=property_context,
            tool_executor=tool_executor,
            working_set_descriptor=working_set.get_descriptor() if working_set else "",
        ):
            event_type = event["event"]
            data = safe_json_dumps(event["data"])
            yield f"event: {event_type}\ndata: {data}\n\n"

        # Emit working set metadata after the chat is done.
        # Always emit — even when count is 0 — so the frontend can sync.
        if working_set is not None:
            ws_data = safe_json_dumps(
                _build_working_set_metadata(working_set, req.session_id),
            )
            yield f"event: working_set\ndata: {ws_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/faketor/working-set/{session_id}")
def get_working_set_properties(
    session_id: str,
    page: int = 0,
    page_size: int = 25,
    sort_by: str = "address",
    sort_dir: str = "asc",
    search: str | None = None,
):
    """Return paginated properties from the session working set."""
    if not _state:
        raise HTTPException(status_code=503, detail="Server not initialized")

    working_set = _state.sessions.get(session_id)
    if working_set is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    # Get all properties as dicts
    all_props = [prop.to_dict() for prop in working_set.properties.values()]

    # Apply search filter
    if search:
        q = search.lower()
        all_props = [
            p for p in all_props
            if q in (p.get("address") or "").lower()
            or q in (p.get("neighborhood") or "").lower()
            or q in (p.get("zoning_class") or "").lower()
        ]

    # Sort
    from homebuyer.services.session_cache import PropertyRecord
    valid_fields = set(PropertyRecord.__dataclass_fields__)
    sort_key = sort_by if sort_by in valid_fields else "address"
    reverse = sort_dir == "desc"
    all_props.sort(
        key=lambda p: (p.get(sort_key) is None, p.get(sort_key, "")),
        reverse=reverse,
    )

    # Paginate
    total = len(all_props)
    page_size = min(page_size, 100)
    start = page * page_size
    end = start + page_size
    page_items = all_props[start:end]

    return {
        "properties": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),  # ceil division
        "descriptor": working_set.get_descriptor(),
    }


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


def _format_roi_note(
    roi_multiplier: Optional[float],
    cost: Optional[int],
    value_delta: Optional[int],
) -> Optional[str]:
    """Human-readable ROI note.

    ``roi_multiplier`` is value_delta / cost (e.g. 1.4 means $1.40 value
    gained per $1 spent, NOT 140% return).  Pre-computing a note prevents
    the LLM from mis-stating the return.
    """
    if roi_multiplier is None or cost is None or value_delta is None:
        return None
    if cost == 0:
        return None
    pct_return = (roi_multiplier - 1.0) * 100
    if roi_multiplier >= 1.0:
        return (
            f"For every $1 spent, you gain ${roi_multiplier:.2f} in value "
            f"({pct_return:+.0f}% net return on a ${cost:,.0f} investment "
            f"adding ${value_delta:,.0f} in value)"
        )
    return (
        f"For every $1 spent, you gain only ${roi_multiplier:.2f} in value "
        f"({pct_return:+.0f}% net return — the ${cost:,.0f} investment "
        f"adds only ${value_delta:,.0f} in value)"
    )


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
        "similarity_score": comp.similarity_score,
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

    # 0) Check precomputed scenarios first (fastest path)
    precomputed = _state.db.get_precomputed_by_location(lat, lon, "buyer", max_distance_m=5)
    if precomputed:
        logger.info(
            "Precomputed HIT for prediction at (%s, %s) — returning stored result",
            lat, lon,
        )
        return json.loads(precomputed["prediction_json"])

    # 1) Check predictions cache
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
    _store_prediction_from_result(_state.db, result, prop, source=source)

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

    # If the analysis was not applicable for this property type, return early
    if getattr(result, "not_applicable", False):
        resp["not_applicable"] = True
        resp["not_applicable_reason"] = getattr(result, "not_applicable_reason", "")
        return resp

    resp["not_applicable"] = False
    resp["not_applicable_reason"] = ""

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

    # Lot aggregate info (for condo units)
    resp["is_unit_not_lot"] = result.is_unit_not_lot
    if result.lot_aggregate:
        agg = result.lot_aggregate
        resp["lot_aggregate"] = {
            "lot_group_key": agg.lot_group_key,
            "total_units": agg.total_units,
            "total_building_sqft": agg.total_building_sqft,
            "lot_size_sqft": agg.lot_size_sqft,
            "total_assessed_value": agg.total_assessed_value,
            "building_to_lot_ratio": agg.building_to_lot_ratio,
            "addresses": agg.addresses,
        }
    else:
        resp["lot_aggregate"] = None

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


def _property_to_listing(
    prop: dict,
    neighborhood: str,
    zone_class: str | None = None,
    last_sale_price: int | None = None,
    last_sale_date: str | None = None,
) -> dict:
    """Convert enriched property details to ListingData format."""
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
    row = _state.db.fetchone(
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
    )
    return dict(row)["zip_code"] if row else "94702"


def _persist_rentcast_sales(
    address: str,
    city: str,
    state: str,
    zip_code: str,
    latitude: float,
    longitude: float,
    neighborhood: str | None,
    detail: "RentcastPropertyDetail | None" = None,
) -> None:
    """Persist RentCast sale history to the database.

    Called after a successful prediction for a property not already in the DB.
    If no sale history is found, persists a property-only record (null
    sale_price/sale_date) so the property is cached for future lookups.

    Errors are logged but never raised so the prediction response is unaffected.
    """
    if not address:
        return
    if not detail:
        return

    try:
        from datetime import date as date_type

        from homebuyer.storage.models import PropertySale

        inserted = 0

        if detail.sale_history:
            for txn in detail.sale_history:
                try:
                    sale_date_obj = date_type.fromisoformat(txn.sale_date)
                except ValueError:
                    continue

                price_per_sqft = None
                if detail.sqft and detail.sqft > 0:
                    price_per_sqft = round(txn.sale_price / detail.sqft, 2)

                sale = PropertySale(
                    address=address,
                    city=city,
                    state=state,
                    zip_code=zip_code,
                    latitude=latitude,
                    longitude=longitude,
                    sale_date=sale_date_obj,
                    sale_price=txn.sale_price,
                    sale_type=txn.event_type,
                    property_type=detail.property_type,
                    beds=detail.beds,
                    baths=detail.baths,
                    sqft=detail.sqft,
                    lot_size_sqft=detail.lot_size_sqft,
                    year_built=detail.year_built,
                    price_per_sqft=price_per_sqft,
                    neighborhood=neighborhood,
                    data_source="rentcast",
                )
                if _state.db.upsert_sale(sale):
                    inserted += 1

        # If no sale history, save a property-only record for future caching
        if inserted == 0:
            prop_record = PropertySale(
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                latitude=latitude,
                longitude=longitude,
                sale_date=None,
                sale_price=None,
                property_type=detail.property_type,
                beds=detail.beds,
                baths=detail.baths,
                sqft=detail.sqft,
                lot_size_sqft=detail.lot_size_sqft,
                year_built=detail.year_built,
                neighborhood=neighborhood,
                data_source="rentcast",
            )
            if _state.db.upsert_sale(prop_record):
                inserted = 1
                logger.info(
                    "Persisted property-only record for %s (no sale history)",
                    address,
                )

        if inserted and detail.sale_history:
            logger.info(
                "Persisted %d RentCast sale records for %s", inserted, address,
            )
    except Exception:
        logger.warning(
            "Failed to persist RentCast sales for %s", address, exc_info=True,
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

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Resolve the UI build directory.  Try several locations:
# 1. Relative to api.py source (works in dev where api.py is in src/homebuyer/)
# 2. Relative to cwd (works on Render where cwd is the repo root)
_UI_DIST = _Path(__file__).resolve().parents[2] / "ui" / "dist"
if not _UI_DIST.is_dir():
    _UI_DIST = _Path.cwd() / "ui" / "dist"

_MARKETING_DIR = _Path(__file__).resolve().parents[2] / "marketing"
if not _MARKETING_DIR.is_dir():
    _MARKETING_DIR = _Path.cwd() / "marketing"

if _MARKETING_DIR.is_dir():
    @app.get("/welcome")
    async def _serve_marketing():
        """Serve the standalone marketing landing page."""
        return FileResponse(_MARKETING_DIR / "index.html", media_type="text/html")

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
