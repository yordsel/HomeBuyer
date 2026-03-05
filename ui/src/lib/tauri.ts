import type {
  ListingPredictionResponse,
  PredictionResult,
  NeighborhoodStats,
  NeighborhoodGeoJson,
  MarketSnapshot,
  MarketSummary,
  ModelInfo,
  AffordabilityResult,
  ComparableProperty,
  DatabaseStatus,
  ManualPredictPayload,
  MapClickResponse,
} from '../types';

// ---------------------------------------------------------------------------
// Runtime detection: Tauri IPC vs direct HTTP to FastAPI
// ---------------------------------------------------------------------------

const isTauri = '__TAURI_INTERNALS__' in window;

// In Tauri or local dev, hit the local FastAPI server directly.
// In production (same-origin), use relative URLs so the request goes
// to the same host that served the frontend.
const isLocal =
  window.location.hostname === 'localhost' ||
  window.location.hostname === '127.0.0.1';
const API_BASE = isTauri || isLocal ? 'http://127.0.0.1:10000' : '';

/**
 * Wrapper that uses Tauri invoke() when running inside the Tauri shell,
 * or falls back to direct HTTP calls to the FastAPI backend when running
 * in a regular browser (useful for dev/preview without Tauri).
 */
async function tauriInvoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (isTauri) {
    const { invoke } = await import('@tauri-apps/api/core');
    return invoke<T>(command, args);
  }
  // Fallback: not available, throw so the HTTP functions below are used instead
  throw new Error('Not in Tauri');
}

/** Simple GET helper for browser-mode API calls. */
async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${resp.status}`);
  }
  return resp.json();
}

/** Simple POST helper for browser-mode API calls. */
async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.detail ?? `HTTP ${resp.status}`);
  }
  return resp.json();
}

// ============================================================================
// Health & Status
// ============================================================================

export async function getHealth(): Promise<{ status: string; model_loaded: boolean }> {
  if (isTauri) return tauriInvoke('health');
  return apiGet('/api/health');
}

export async function getStatus(): Promise<DatabaseStatus> {
  if (isTauri) return tauriInvoke('get_status');
  return apiGet('/api/status');
}

// ============================================================================
// Predictions
// ============================================================================

export async function predictListing(url: string): Promise<ListingPredictionResponse> {
  if (isTauri) return tauriInvoke('predict_listing', { url });
  return apiPost('/api/predict/listing', { url });
}

export async function predictManual(
  payload: ManualPredictPayload,
): Promise<{ prediction: PredictionResult }> {
  if (isTauri) return tauriInvoke('predict_manual', { payload });
  return apiPost('/api/predict/manual', payload);
}

export async function predictMapClick(
  latitude: number,
  longitude: number,
): Promise<MapClickResponse> {
  if (isTauri) return tauriInvoke('predict_map_click', { latitude, longitude });
  return apiPost('/api/predict/map-click', { latitude, longitude });
}

// ============================================================================
// Neighborhoods
// ============================================================================

export async function getNeighborhoods(
  minSales?: number,
  years?: number,
): Promise<NeighborhoodStats[]> {
  if (isTauri) {
    return tauriInvoke('get_neighborhoods', {
      min_sales: minSales ?? null,
      years: years ?? null,
    });
  }
  const params = new URLSearchParams();
  if (minSales != null) params.set('min_sales', String(minSales));
  if (years != null) params.set('years', String(years));
  const qs = params.toString();
  return apiGet(`/api/neighborhoods${qs ? `?${qs}` : ''}`);
}

export async function getNeighborhoodDetail(
  name: string,
  years?: number,
): Promise<NeighborhoodStats> {
  if (isTauri) {
    return tauriInvoke('get_neighborhood_detail', { name, years: years ?? null });
  }
  const qs = years != null ? `?years=${years}` : '';
  return apiGet(`/api/neighborhoods/${encodeURIComponent(name)}${qs}`);
}

export async function getNeighborhoodGeoJson(): Promise<NeighborhoodGeoJson> {
  if (isTauri) return tauriInvoke('get_neighborhood_geojson');
  return apiGet('/api/neighborhoods/geojson');
}

// ============================================================================
// Market
// ============================================================================

export async function getMarketTrend(months?: number): Promise<MarketSnapshot[]> {
  if (isTauri) return tauriInvoke('get_market_trend', { months: months ?? null });
  const qs = months != null ? `?months=${months}` : '';
  return apiGet(`/api/market/trend${qs}`);
}

export async function getMarketSummary(): Promise<MarketSummary> {
  if (isTauri) return tauriInvoke('get_market_summary');
  return apiGet('/api/market/summary');
}

// ============================================================================
// Model
// ============================================================================

export async function getModelInfo(): Promise<ModelInfo> {
  if (isTauri) return tauriInvoke('get_model_info');
  return apiGet('/api/model/info');
}

// ============================================================================
// Affordability
// ============================================================================

export async function getAffordability(
  budget: number,
  downPct?: number,
  hoa?: number,
): Promise<AffordabilityResult> {
  if (isTauri) {
    return tauriInvoke('get_affordability', {
      budget,
      down_pct: downPct ?? null,
      hoa: hoa ?? null,
    });
  }
  const params = new URLSearchParams();
  if (downPct != null) params.set('down_pct', String(downPct));
  if (hoa != null) params.set('hoa', String(hoa));
  const qs = params.toString();
  return apiGet(`/api/afford/${budget}${qs ? `?${qs}` : ''}`);
}

// ============================================================================
// Comparables
// ============================================================================

export async function getComparables(payload: {
  neighborhood: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  year_built?: number;
}): Promise<ComparableProperty[]> {
  if (isTauri) return tauriInvoke('get_comparables', { payload });
  return apiPost('/api/comps', payload);
}
