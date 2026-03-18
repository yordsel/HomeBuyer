# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Python backend
```bash
pip install -e ".[dev,collectors]"   # Install with test + scraping deps
pytest                                # Run all tests (testpaths = tests/)
pytest tests/test_auth.py             # Run a single test file
pytest tests/test_auth.py -k "test_login" # Run a specific test
ruff check src/                       # Lint (py311, line-length 100)
ruff format src/                      # Format
```

### Frontend
```bash
cd ui && npm run dev                  # Vite dev server on port 1420 (strict)
cd ui && npm run build                # tsc + vite build → ui/dist/
```

### Running the app locally
```bash
python -m homebuyer                   # Starts FastAPI/Uvicorn on port 8787
```
Backend on `http://127.0.0.1:8787`, frontend dev server on `http://127.0.0.1:1420`. The frontend API client (`ui/src/lib/api.ts`) detects localhost and routes API calls to `:8787`; in production it uses relative URLs (same origin).

### CLI data pipeline
```bash
homebuyer collect sales               # Scrape Redfin sales data
homebuyer collect mortgage             # Fetch FRED mortgage rates
homebuyer collect regulations          # Scrape Berkeley zoning/regulations → JSON
homebuyer process                      # Normalize, deduplicate, geocode
homebuyer train                        # Train ML model → data/models/
homebuyer predict                      # Run batch predictions
```

### Production smoke test
```bash
./scripts/smoke-test.sh                        # Test production (agentc.work)
./scripts/smoke-test.sh http://localhost:8787   # Test local
```
22 curl-based checks covering health, frontend, market data, neighborhoods/GeoJSON, predictions, property analysis, and auth endpoints. Run after every deploy.

## Architecture

### Single-process backend
FastAPI serves both the API and the built frontend SPA from a single process. All ~50 endpoints live in `src/homebuyer/api.py`. An `AppState` singleton is initialized at lifespan startup, loading the DB connection, ML model, zoning classifier, geocoder, and development calculator. Middleware stack: CORS → SecurityHeaders → SlowAPI rate limiter.

### Dual-mode database
`src/homebuyer/storage/database.py` handles SQLite (dev) and PostgreSQL (prod). Mode is selected by the `DATABASE_URL` env var — when set, PostgreSQL is used; otherwise SQLite at `data/berkeley_homebuyer.db`. Schema DDL is written in SQLite dialect and auto-translated for Postgres at runtime. Current schema version: 5.

### Frontend routing
The React app uses **state-based routing** (`useState<PageId>` in `App.tsx`), not React Router. Pages are switched via a `renderPage()` switch statement. Two context providers: `AuthContext` (JWT tokens, Google OAuth) and `PropertyContext` (active property, tracked properties, working-set metadata).

### Auth system
JWT HS256 (30 min access tokens) + opaque rotating refresh tokens (7 days, SHA-256 hashed in DB). Access token stored in HttpOnly cookie (`homebuyer_access`). Google OAuth via Authlib with tokens passed as URL hash fragments post-callback. TOS version-gated via `CURRENT_TOS_VERSION` in config.py. Rate limits on auth endpoints (register 3/min, login 5/min, refresh 10/min).

### Faketor AI agent
Claude-powered property analyst in `src/homebuyer/services/faketor/` (modular package). Uses `claude-sonnet-4-20250514` with 28 tools (18 built-in + 10 gap analysis), max 12 iterations per turn. When `USE_SEGMENT_ORCHESTRATION=true`, requests are routed through `TurnOrchestrator` (9-step pipeline: load context → extract signals → classify segment → resolve job → pre-execute gap tools → build prompt → LLM loop → post-process → persist). `ResearchContext` persists buyer state, market snapshot, and property analyses per user. `SessionWorkingSet` manages a per-session property filter stack with undo support. Chat streams via SSE with event types: `tool_start`, `tool_result`, `text_delta`, `working_set`, `discussed_property`, `segment_update`, `resume_briefing`, `suggestion_chips`, `done`, `error`.

### ML model
`HistGradientBoostingRegressor` (3 models: point estimate + upper/lower quantile bounds). Features include property attributes joined with market metrics and mortgage rates. Stored as joblib at `data/models/berkeley_price_model.joblib`. SHAP values provide per-feature contribution explanations.

### Path resolution (important for deployment)
`config.py` computes `PROJECT_ROOT` from `__file__`, but when pip-installed on Render, `__file__` is in site-packages. It falls back to `Path.cwd()` when the computed root lacks a `data/` directory. All paths (`DATA_DIR`, `GEO_DIR`, `REGULATIONS_DIR`, etc.) derive from `PROJECT_ROOT`. If data files are missing in production, check this resolution first.

### Deployment
Render: PostgreSQL 16 + Python web service (free tier). `render-build.sh` runs `pip install .` then `cd ui && npm ci && npm run build`. Start command: `python -m homebuyer`. The built SPA is served by FastAPI's catch-all route — `/assets/*` serves static files, everything else falls through to `index.html`.

## Key files

| File | Purpose |
|------|---------|
| `src/homebuyer/api.py` | All API endpoints (~4400 lines), AppState, lifespan |
| `src/homebuyer/config.py` | All configuration, paths, env vars, constants |
| `src/homebuyer/auth.py` | JWT, bcrypt, refresh tokens, OAuth2 |
| `src/homebuyer/services/faketor/orchestrator.py` | Segment-driven 9-step turn pipeline |
| `src/homebuyer/services/faketor/service.py` | Faketor service entry point, legacy + orchestrated paths |
| `src/homebuyer/services/faketor/classification.py` | Buyer segment classifier (11 segments) |
| `src/homebuyer/services/faketor/extraction.py` | Signal extraction from user messages via Haiku |
| `src/homebuyer/services/faketor/jobs.py` | Job resolution, proactive analysis registry, suggestion chips |
| `src/homebuyer/services/session_cache.py` | Working set / filter stack |
| `src/homebuyer/storage/database.py` | Dual-mode DB (SQLite/PostgreSQL) |
| `src/homebuyer/prediction/model.py` | ML model artifact and prediction |
| `ui/src/App.tsx` | Frontend root, page routing, auth gate |
| `ui/src/lib/api.ts` | API client, 401→refresh→retry logic |
| `ui/src/context/AuthContext.tsx` | Auth state management |
| `SERVICES.md` | Full reference: all endpoints, tools, CLI, env vars |

## Test patterns

Auth tests (`tests/test_auth.py`, 49 tests) use `TestClient` with an in-memory SQLite DB swap and `limiter.enabled = False` to bypass rate limiting. Other test files use the `tmp_db` and `sample_sale` fixtures from `conftest.py`.

## Environment variables

Required for production: `DATABASE_URL`, `JWT_SECRET_KEY`, `ANTHROPIC_API_KEY`. Optional: `RENTCAST_API_KEY` (property enrichment), `RESEND_API_KEY` + `EMAIL_FROM` (transactional email), `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `GOOGLE_REDIRECT_URI` (OAuth), `ENVIRONMENT` (controls CSP strictness), `APP_URL` (email link base), `FRONTEND_URL` (extra CORS origin), `USE_SEGMENT_ORCHESTRATION` (feature flag: `true` enables segment-driven orchestrator, default `false` uses legacy Faketor path).

## Data directory

`data/geo/` (GeoJSON boundaries) and `data/models/` (ML model) are committed and required for production. `data/raw/`, `data/processed/`, `data/regulations/sources/`, and `*.db` files are gitignored. Regulation seed data lives in `data/regulations/seed/`.
