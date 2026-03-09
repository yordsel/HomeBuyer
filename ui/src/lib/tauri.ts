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
  DevelopmentPotentialResponse,
  PotentialSummaryResponse,
  ImprovementSimResponse,
  FaketorChatResponse,
  RentalAnalysisResponse,
  RentEstimate,
  WorkingSetPage,
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
const API_BASE = isTauri || isLocal ? 'http://127.0.0.1:8787' : '';

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

// ============================================================================
// Development Potential
// ============================================================================

export async function getPropertyPotential(payload: {
  latitude: number;
  longitude: number;
  address?: string;
  lot_size_sqft?: number;
  sqft?: number;
}): Promise<DevelopmentPotentialResponse> {
  if (isTauri) return tauriInvoke('get_property_potential', { payload });
  return apiPost('/api/property/potential', payload);
}

export async function getPropertyPotentialSummary(payload: {
  latitude: number;
  longitude: number;
  address?: string;
  lot_size_sqft?: number;
  sqft?: number;
  neighborhood?: string;
  beds?: number;
  baths?: number;
  year_built?: number;
}): Promise<PotentialSummaryResponse> {
  if (isTauri) return tauriInvoke('get_property_potential_summary', { payload });
  return apiPost('/api/property/potential/summary', payload);
}

export async function getImprovementSimulation(payload: {
  latitude: number;
  longitude: number;
  address?: string;
  neighborhood?: string;
  zip_code?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  property_type?: string;
  hoa_per_month?: number;
}): Promise<ImprovementSimResponse> {
  if (isTauri) return tauriInvoke('get_improvement_simulation', { payload });
  return apiPost('/api/property/improvement-sim', payload);
}

// ============================================================================
// Rental Income & Investment Analysis
// ============================================================================

export async function getRentalAnalysis(payload: {
  latitude: number;
  longitude: number;
  address?: string;
  neighborhood?: string;
  zip_code?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  property_type?: string;
  list_price?: number;
  hoa_per_month?: number;
  down_payment_pct?: number;
  self_managed?: boolean;
}): Promise<RentalAnalysisResponse> {
  if (isTauri) return tauriInvoke('get_rental_analysis', { payload });
  return apiPost('/api/property/rental-analysis', payload);
}

export async function getRentEstimate(payload: {
  latitude: number;
  longitude: number;
  beds?: number;
  baths?: number;
  sqft?: number;
  neighborhood?: string;
  list_price?: number;
}): Promise<RentEstimate> {
  if (isTauri) return tauriInvoke('get_rent_estimate', { payload });
  return apiPost('/api/property/rent-estimate', payload);
}

// ============================================================================
// Faketor Chat
// ============================================================================

export async function sendFaketorMessage(payload: {
  latitude: number;
  longitude: number;
  message: string;
  history?: { role: string; content: string }[];
  session_id?: string;
  address?: string;
  neighborhood?: string;
  zip_code?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  property_type?: string;
  property_category?: string;
}): Promise<FaketorChatResponse> {
  if (isTauri) return tauriInvoke('faketor_chat', { payload });
  return apiPost('/api/faketor/chat', payload);
}

export async function getWorkingSetProperties(params: {
  session_id: string;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_dir?: string;
  search?: string;
}): Promise<WorkingSetPage> {
  const qs = new URLSearchParams();
  if (params.page != null) qs.set('page', String(params.page));
  if (params.page_size != null) qs.set('page_size', String(params.page_size));
  if (params.sort_by) qs.set('sort_by', params.sort_by);
  if (params.sort_dir) qs.set('sort_dir', params.sort_dir);
  if (params.search) qs.set('search', params.search);
  const query = qs.toString();
  return apiGet(`/api/faketor/working-set/${params.session_id}${query ? `?${query}` : ''}`);
}
