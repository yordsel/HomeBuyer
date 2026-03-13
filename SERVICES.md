# Services & Tools

Detailed reference for HomeBuyer's API, AI agent, CLI pipeline, ML model, and external dependencies.

---

## Table of Contents

- [Faketor AI Agent](#faketor-ai-agent)
- [API Endpoints](#api-endpoints)
- [CLI Data Pipeline](#cli-data-pipeline)
- [Data Collectors](#data-collectors)
- [ML Model](#ml-model)
- [Environment Variables](#environment-variables)

---

## Faketor AI Agent

Faketor is the AI property analyst — a Claude-powered agent with 18 tools that can look up properties, run comps, check zoning, estimate rental income, model investment scenarios, and generate PDF prospectuses. It has zero emotional attachment to closing the deal.

| Tool | Description |
|------|-------------|
| `lookup_property` | Look up a Berkeley property by address — beds, baths, sqft, year built, lot size, zoning, neighborhood, last sale |
| `search_properties` | Search properties by criteria (price range, beds, sqft, neighborhood, zoning) |
| `get_price_prediction` | ML model's predicted sale price with confidence interval |
| `get_comparable_sales` | Recent comparable sales in the same neighborhood |
| `get_neighborhood_stats` | Neighborhood-level stats — median price, price/sqft, sale velocity, DOM, inventory |
| `get_market_summary` | Berkeley-wide market summary — median prices, sale-to-list ratio, % sold above list |
| `get_development_potential` | Zoning details, ADU feasibility, Middle Housing eligibility, setback requirements |
| `get_improvement_simulation` | Simulate effect of home improvements on estimated sale price |
| `estimate_rental_income` | Monthly and annual rental income estimates |
| `estimate_sell_vs_hold` | Compare selling now vs. holding for 1, 3, or 5 years |
| `analyze_investment_scenarios` | Comprehensive scenario analysis — flip, rent, hold |
| `generate_investment_prospectus` | Full PDF-exportable investment prospectus for one or more properties |
| `lookup_permits` | Building permits filed for a specific address |
| `lookup_regulation` | Berkeley regulations, zoning definitions, housing policies from the JSON knowledge base |
| `lookup_glossary_term` | Financial and real estate terminology definitions |
| `query_database` | Read-only SQL queries against the Berkeley property database |
| `update_working_set` | Change the session's property working set (replace, filter, add, remove) |
| `undo_filter` | Undo the most recent filter applied to the working set |

---

## API Endpoints

### Health & Status

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/status` | System status |
| GET | `/api/fun-fact` | Random Berkeley real estate fun fact |

### Authentication

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/login` | Sign in |
| GET | `/api/auth/me` | Current user profile |
| POST | `/api/auth/refresh` | Refresh JWT token |
| POST | `/api/auth/logout` | Sign out (revokes refresh token) |
| POST | `/api/auth/change-password` | Change password |
| POST | `/api/auth/forgot-password` | Initiate password reset email |
| POST | `/api/auth/reset-password` | Complete password reset |
| POST | `/api/auth/resend-verification` | Resend email verification |
| GET | `/api/auth/verify-email` | Verify email token |
| POST | `/api/auth/deactivate` | Deactivate account (soft delete) |
| DELETE | `/api/auth/account` | Permanently delete account |
| GET | `/api/auth/activity` | User activity log |

### Google OAuth

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/auth/google/authorize` | Get Google OAuth authorization URL |
| GET | `/api/auth/google/callback` | Handle OAuth callback, create/link account |
| GET | `/api/auth/linked-accounts` | List linked OAuth providers |
| DELETE | `/api/auth/linked-accounts/{provider}` | Unlink an OAuth provider |

### Session Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/auth/sessions` | List active sessions |
| DELETE | `/api/auth/sessions/{session_id}` | Revoke a specific session |
| POST | `/api/auth/sessions/revoke-others` | Revoke all sessions except current |

### Terms of Service

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/terms/current` | Current TOS version and content |
| POST | `/api/auth/accept-tos` | Accept terms of service |

### Predictions

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/predict/listing` | Predict price from Redfin listing URL |
| POST | `/api/predict/manual` | Predict price from property details |
| POST | `/api/predict/map-click` | Predict price from map coordinates |

### Market Data

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/market/trend` | Market trend data over time |
| GET | `/api/market/summary` | Berkeley market summary stats |

### Neighborhoods

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/neighborhoods` | List all neighborhoods |
| GET | `/api/neighborhoods/geojson` | Neighborhood boundaries as GeoJSON |
| GET | `/api/neighborhoods/{name}` | Specific neighborhood details |

### Property Analysis

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/property/potential` | Development potential analysis |
| POST | `/api/property/potential/summary` | Summary development potential |
| POST | `/api/property/improvement-sim` | Simulate home improvements |
| POST | `/api/property/rental-analysis` | Rental income analysis |
| POST | `/api/property/rent-estimate` | Rent estimate |
| POST | `/api/comps` | Comparable sales with analysis |

### Affordability

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/afford/{budget}` | What you can afford with a given monthly budget |

### Faketor AI Chat

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/faketor/chat` | Chat with Faketor (request/response) |
| POST | `/api/faketor/chat/stream` | Chat with Faketor (streaming) |
| GET | `/api/faketor/working-set/{session_id}` | Current property working set |

### Conversations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/conversations` | List conversations |
| POST | `/api/conversations` | Create conversation |
| GET | `/api/conversations/{id}` | Get conversation details |
| PATCH | `/api/conversations/{id}` | Rename conversation |
| DELETE | `/api/conversations/{id}` | Delete conversation |
| POST | `/api/conversations/{id}/messages` | Send message |

### Model Info

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/model/info` | Model metadata and performance metrics |

---

## CLI Data Pipeline

The CLI (`homebuyer`) handles data collection, processing, enrichment, model training, and analysis. All commands use the Click framework.

### Setup

```bash
homebuyer init          # Create directories, initialize database, verify geo boundaries
homebuyer status        # Show database statistics and row counts
```

### Data Collection (`homebuyer collect`)

| Command | Description | Source |
|---------|-------------|--------|
| `collect sales` | Fetch property sales | Redfin GIS-CSV API |
| `collect market` | Download market metrics | Redfin Data Center |
| `collect rates` | Fetch mortgage rates | FRED |
| `collect indicators` | Fetch economic indicators | FRED |
| `collect census` | Fetch median income by zip | Census ACS API |
| `collect beso` | Fetch energy benchmarking | Berkeley Open Data |
| `collect permits` | Scrape building permits | Accela Citizen Access |
| `collect parcels` | Download parcel data | Berkeley Open Data |
| `collect regulations` | Build regulation JSON knowledge base | Municipal codes + city websites |
| `collect glossary` | Compile financial/RE terminology | Seed files |
| `collect all` | Run all collectors | All sources |

### Data Processing (`homebuyer process`)

| Command | Description |
|---------|-------------|
| `process normalize` | Normalize property data |
| `process geocode` | Geocode properties to neighborhoods |
| `process deduplicate` | Remove duplicate records |
| `process validate` | Validate data integrity |
| `process zoning` | Assign zoning districts |
| `process parcels` | Enrich parcels with zoning + neighborhood |
| `process sales` | Enrich sales with zoning + neighborhood |
| `process all` | Run all processing steps |

### Data Enrichment (`homebuyer enrich`)

| Command | Description | Source |
|---------|-------------|--------|
| `enrich rentcast` | Backfill property details | RentCast API |
| `enrich backfill-sales` | Backfill sale history | RentCast API |

### Model Training

| Command | Description |
|---------|-------------|
| `homebuyer train` | Train ML price prediction model (with optional grid search) |
| `homebuyer precompute` | Precompute investment scenarios for all properties |
| `homebuyer generate-facts` | Generate fact caches |

### Analysis (`homebuyer analyze`)

| Command | Description |
|---------|-------------|
| `analyze summary` | Overall property and market summary |
| `analyze neighborhood` | Analyze a specific neighborhood |
| `analyze neighborhoods` | Analyze all neighborhoods |
| `analyze estimate` | Estimate hold value and investment metrics for an address |
| `analyze trend` | Price trends over time |
| `analyze afford` | Affordability analysis for a monthly budget |

### Export

| Command | Description |
|---------|-------------|
| `homebuyer export` | Export any table to CSV |

---

## Data Collectors

| Collector | Data Source | Method |
|-----------|-----------|--------|
| `RedfinSalesCollector` | Redfin GIS-CSV API | HTTP requests with price-range splitting |
| `RedfinMarketCollector` | Redfin Data Center | S3 TSV download |
| `FredCollector` | FRED | CSV API |
| `CensusCollector` | Census ACS | JSON API |
| `BESOCollector` | Berkeley Open Data (Socrata) | JSON API |
| `ParcelCollector` | Berkeley Open Data (Socrata) | JSON API |
| `AccelaPermitCollector` | Accela Citizen Access | Playwright browser automation |
| `RegulationCollector` | Berkeley Municipal Code + city websites | Playwright + requests |
| `GlossaryCollector` | Seed JSON files | File copy |
| `RentcastParcelEnricher` | RentCast API | HTTP requests (paid) |
| `ListingFetcher` | Redfin listing pages | HTTP + HTML parsing |

---

## ML Model

**Algorithm:** Histogram-based Gradient Boosting (scikit-learn `HistGradientBoostingRegressor`)

**Architecture:**
- Main model trained on log-transformed sale prices
- Two quantile models (5th and 95th percentile) for 90% prediction intervals
- GridSearchCV for hyperparameter tuning with temporal train/test split

**Features (43+):**

| Category | Features |
|----------|----------|
| Property | beds, baths, sqft, lot_size_sqft, year_built, hoa_per_month, latitude, longitude |
| Derived | bed_bath_ratio, sqft_per_bed, lot_to_living_ratio, effective_sqft, is_condo_unit, units_on_lot, and more |
| Location | neighborhood (encoded), zip_code (encoded), zoning (encoded), property_type (encoded) |
| Market | market_median_price, market_sale_to_list, market_sold_above_pct |
| Economic | rate_30yr, consumer_sentiment |
| Census | zip_median_income |
| Permits | permit_count_5yr, permit_count_total, years_since_last_permit, maintenance_value, modernization_recency |

**Training filters:** Sale price $100K–$10M, post-2015, price/sqft under $2,000, outlier flagging at 3 standard deviations.

**Explainability:** SHAP TreeExplainer for feature importance and Shapley values.

---

## Environment Variables

### Required for Production

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `ENVIRONMENT` | `production` or `development` |
| `JWT_SECRET_KEY` | Secret key for JWT token signing |

### Email (required for password reset and email verification)

| Variable | Description |
|----------|-------------|
| `RESEND_API_KEY` | Resend API key |
| `EMAIL_FROM` | Sender address (must be verified domain in Resend) |
| `APP_URL` | Frontend URL for links in emails |

### AI Agent (required for Faketor)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |

### Property Data (required for enrichment)

| Variable | Description |
|----------|-------------|
| `RENTCAST_API_KEY` | RentCast API key |

### Google OAuth (optional)

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLIENT_ID` | Google OAuth 2.0 Client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth 2.0 Client Secret |
| `GOOGLE_REDIRECT_URI` | OAuth callback URL |

All variables default to empty strings or sensible development defaults when not set. The app degrades gracefully — features that depend on missing API keys simply won't be available.
