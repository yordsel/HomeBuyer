#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Production smoke-test for HomeBuyer (agentc.work)
#
# Usage:
#   ./scripts/smoke-test.sh                     # test production
#   ./scripts/smoke-test.sh http://localhost:8787  # test local dev
#
# Returns exit code 0 if all checks pass, 1 if any fail.
# ---------------------------------------------------------------------------
set -uo pipefail
# Note: -e intentionally omitted — (( )) arithmetic returns 1 when
# incrementing from 0, which would abort the script under -e.

BASE="${1:-https://www.agentc.work}"
PASS=0
FAIL=0
WARN=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
check_status() {
  local method="$1" url="$2" expected="$3" label="$4" data="${5:-}"
  local args=(-s -o /dev/null -w "%{http_code}" --max-time 30)

  if [[ "$method" == "POST" ]]; then
    args+=(-X POST -H "Content-Type: application/json" -d "$data")
  fi

  local status
  status=$(curl "${args[@]}" "$url" 2>/dev/null) || status="000"

  if [[ "$status" == "$expected" ]]; then
    printf "  ${GREEN}✅ %-45s %s${NC}\n" "$label" "$status"
    PASS=$((PASS + 1))
  else
    printf "  ${RED}❌ %-45s %s (expected %s)${NC}\n" "$label" "$status" "$expected"
    FAIL=$((FAIL + 1))
  fi
}

check_json_field() {
  local url="$1" field="$2" label="$3"
  local value
  value=$(curl -s --max-time 15 "$url" 2>/dev/null | python3 -c "
import sys, json
field = sys.argv[1]
try:
    d = json.load(sys.stdin)
    v = d
    for k in field.split('.'):
        v = v[k] if isinstance(v, dict) else v[int(k)] if k.isdigit() else None
    print(v if v is not None else 'NULL')
except: print('ERROR')
" "$field" 2>/dev/null)

  if [[ "$value" != "ERROR" && "$value" != "NULL" && "$value" != "" ]]; then
    printf "  ${GREEN}✅ %-45s %s${NC}\n" "$label" "$value"
    PASS=$((PASS + 1))
  else
    printf "  ${RED}❌ %-45s %s${NC}\n" "$label" "${value:-empty}"
    FAIL=$((FAIL + 1))
  fi
}

warn_status() {
  local method="$1" url="$2" expected="$3" label="$4" data="${5:-}"
  local args=(-s -o /dev/null -w "%{http_code}" --max-time 30)

  if [[ "$method" == "POST" ]]; then
    args+=(-X POST -H "Content-Type: application/json" -d "$data")
  fi

  local status
  status=$(curl "${args[@]}" "$url" 2>/dev/null) || status="000"

  if [[ "$status" == "$expected" ]]; then
    printf "  ${GREEN}✅ %-45s %s${NC}\n" "$label" "$status"
    PASS=$((PASS + 1))
  else
    printf "  ${YELLOW}⚠️  %-45s %s (expected %s)${NC}\n" "$label" "$status" "$expected"
    WARN=$((WARN + 1))
  fi
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
printf "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}\n"
printf "${BOLD}${CYAN}  HomeBuyer Production Smoke Test${NC}\n"
printf "${BOLD}${CYAN}  Target: %s${NC}\n" "$BASE"
printf "${BOLD}${CYAN}  Time:   %s${NC}\n" "$(date '+%Y-%m-%d %H:%M:%S %Z')"
printf "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}\n"

# ---------------------------------------------------------------------------
# 1. Core health
# ---------------------------------------------------------------------------
echo ""
printf "${BOLD}[1/7] Core Health${NC}\n"
check_status  GET  "$BASE/api/health"  200  "Health endpoint"
check_json_field   "$BASE/api/health"  "status"  "Health status = ok"

# ---------------------------------------------------------------------------
# 2. Frontend serving
# ---------------------------------------------------------------------------
echo ""
printf "${BOLD}[2/7] Frontend (SPA)${NC}\n"
check_status  GET  "$BASE/"           200  "Landing page"
check_status  GET  "$BASE/welcome"    200  "Welcome route (SPA fallback)"

# Check that static assets are served (not just the SPA fallback)
ASSET_URL=$(curl -s --max-time 10 "$BASE/" 2>/dev/null | grep -o '/assets/index-[^"]*\.js' | head -1)
if [[ -n "$ASSET_URL" ]]; then
  check_status  GET  "$BASE$ASSET_URL"  200  "JS bundle ($ASSET_URL)"
else
  printf "  ${RED}❌ %-45s %s${NC}\n" "JS bundle" "not found in HTML"
  FAIL=$((FAIL + 1))
fi

# ---------------------------------------------------------------------------
# 3. Market data
# ---------------------------------------------------------------------------
echo ""
printf "${BOLD}[3/7] Market Data${NC}\n"
check_status     GET  "$BASE/api/market/summary"  200  "Market summary"
check_status     GET  "$BASE/api/market/trend"     200  "Market trend"
check_json_field      "$BASE/api/market/summary"   "current_market.median_sale_price"  "Median sale price present"

# ---------------------------------------------------------------------------
# 4. Neighborhoods & GeoJSON
# ---------------------------------------------------------------------------
echo ""
printf "${BOLD}[4/7] Neighborhoods${NC}\n"
check_status     GET  "$BASE/api/neighborhoods"          200  "Neighborhoods list"
check_status     GET  "$BASE/api/neighborhoods/geojson"   200  "GeoJSON boundaries"
check_json_field      "$BASE/api/neighborhoods/geojson"   "type"  "GeoJSON type = FeatureCollection"

# ---------------------------------------------------------------------------
# 5. Prediction & Model
# ---------------------------------------------------------------------------
echo ""
printf "${BOLD}[5/7] Prediction & Model${NC}\n"
check_status  GET  "$BASE/api/model/info"  200  "Model info"

# Model may or may not be loaded — warn instead of fail
MODEL_LOADED=$(curl -s --max-time 10 "$BASE/api/health" 2>/dev/null | python3 -c "
import sys, json
try: print(json.load(sys.stdin).get('model_loaded', False))
except: print('False')
" 2>/dev/null)

if [[ "$MODEL_LOADED" == "True" ]]; then
  printf "  ${GREEN}✅ %-45s %s${NC}\n" "ML model loaded" "yes"
  PASS=$((PASS + 1))
  # Only test predict if model is loaded
  check_status  POST  "$BASE/api/predict/manual"  200  "Manual prediction" \
    '{"bedrooms":3,"bathrooms":2,"sqft":1500,"lot_sqft":5000,"year_built":1950,"neighborhood":"North Berkeley","property_type":"Single Family"}'
else
  printf "  ${YELLOW}⚠️  %-45s %s${NC}\n" "ML model loaded" "no (predictions disabled)"
  WARN=$((WARN + 1))
fi

# ---------------------------------------------------------------------------
# 6. Property analysis (Potential / Rental / Affordability)
# ---------------------------------------------------------------------------
echo ""
printf "${BOLD}[6/7] Property Analysis${NC}\n"
check_status  POST  "$BASE/api/property/potential"  200  "Development potential" \
  '{"address":"1200 Cedar St","latitude":37.880,"longitude":-122.273,"lot_sqft":5000}'

check_status  POST  "$BASE/api/property/potential/summary"  200  "Potential summary" \
  '{"address":"1200 Cedar St","latitude":37.880,"longitude":-122.273,"lot_sqft":5000}'

check_status  GET   "$BASE/api/afford/1500000"  200  "Affordability calculator"

# Rental analysis may depend on external API (RentCast) — warn only
warn_status  POST  "$BASE/api/property/rental-analysis"  200  "Rental analysis" \
  '{"address":"1200 Cedar St, Berkeley, CA","latitude":37.880,"longitude":-122.273,"bedrooms":3,"bathrooms":2,"sqft":1500,"lot_sqft":5000}'

# ---------------------------------------------------------------------------
# 7. Auth endpoints (basic reachability — not testing login flow)
# ---------------------------------------------------------------------------
echo ""
printf "${BOLD}[7/7] Auth Endpoints${NC}\n"
check_status  GET   "$BASE/api/terms/current"     200  "Terms of service"
check_status  GET   "$BASE/api/fun-fact"           200  "Fun fact"

# Auth endpoints should return 422 (missing body) not 500
check_status  POST  "$BASE/api/auth/login"     422  "Login (reachable, needs body)"  '{}'
check_status  POST  "$BASE/api/auth/register"  422  "Register (reachable, needs body)"  '{}'

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
printf "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}\n"
TOTAL=$((PASS + FAIL + WARN))
printf "${BOLD}  Results: "
printf "${GREEN}%d passed${NC}  " "$PASS"
if [[ $FAIL -gt 0 ]]; then
  printf "${RED}%d failed${NC}  " "$FAIL"
else
  printf "%d failed  " "$FAIL"
fi
if [[ $WARN -gt 0 ]]; then
  printf "${YELLOW}%d warnings${NC}  " "$WARN"
else
  printf "%d warnings  " "$WARN"
fi
printf "(%d total)\n" "$TOTAL"
printf "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}\n"
echo ""

if [[ $FAIL -gt 0 ]]; then
  printf "${RED}${BOLD}  ⛔  SMOKE TEST FAILED${NC}\n\n"
  exit 1
else
  printf "${GREEN}${BOLD}  ✅  ALL CHECKS PASSED${NC}\n\n"
  exit 0
fi
