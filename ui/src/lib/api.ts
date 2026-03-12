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
  ResponseBlock,
  WorkingSetMeta,
  AuthResponse,
  AuthActivityEvent,
  User,
  Conversation,
  ConversationDetail,
} from '../types';
import { coerceBlockData } from './coerce';

// ---------------------------------------------------------------------------
// API base: in local dev hit the FastAPI server directly;
// in production use relative URLs (same-origin).
// ---------------------------------------------------------------------------

const isLocal =
  window.location.hostname === 'localhost' ||
  window.location.hostname === '127.0.0.1';
const API_BASE = isLocal ? 'http://127.0.0.1:8787' : '';

// ---------------------------------------------------------------------------
// Auth token management
// ---------------------------------------------------------------------------

const TOKEN_KEY = 'homebuyer_token';
const REFRESH_TOKEN_KEY = 'homebuyer_refresh_token';

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function getStoredRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setStoredRefreshToken(token: string): void {
  localStorage.setItem(REFRESH_TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  if (token) {
    return { Authorization: `Bearer ${token}` };
  }
  return {};
}

// ---------------------------------------------------------------------------
// Token refresh logic — handles 401 retry transparently
// ---------------------------------------------------------------------------

let refreshPromise: Promise<AuthResponse> | null = null;

/** Callback set by AuthContext so the API layer can force a logout on unrecoverable auth failures. */
let onAuthFailure: (() => void) | null = null;
export function setOnAuthFailure(cb: () => void) {
  onAuthFailure = cb;
}

async function refreshAccessToken(): Promise<AuthResponse> {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) {
    throw new Error('No refresh token');
  }
  const resp = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!resp.ok) {
    // Refresh failed — clear tokens and force logout
    clearStoredToken();
    onAuthFailure?.();
    throw new Error('Session expired. Please sign in again.');
  }
  const data: AuthResponse = await resp.json();
  setStoredToken(data.access_token);
  setStoredRefreshToken(data.refresh_token);
  return data;
}

/**
 * Attempt to refresh the token exactly once. Concurrent callers share the
 * same in-flight promise so only one refresh request is made.
 */
async function ensureFreshToken(): Promise<void> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken();
  }
  try {
    await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

// ---------------------------------------------------------------------------
// HTTP helpers with automatic 401 → refresh → retry
// ---------------------------------------------------------------------------

/** Paths that should NOT trigger a token refresh on 401. */
const AUTH_PATHS = ['/api/auth/login', '/api/auth/register', '/api/auth/refresh'];

/**
 * Core fetch wrapper with 401 → refresh → retry logic.
 * On a 401 from any non-auth endpoint, it attempts one token refresh
 * and retries the original request with the new access token.
 */
async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const doFetch = () =>
    fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers: { ...authHeaders(), ...(init.headers as Record<string, string> ?? {}) },
    });

  let resp = await doFetch();

  // Attempt one transparent refresh on 401 (skip for auth endpoints)
  if (resp.status === 401 && !AUTH_PATHS.includes(path) && getStoredRefreshToken()) {
    await ensureFreshToken();
    resp = await doFetch();
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

/** GET helper. */
async function apiGet<T>(path: string): Promise<T> {
  return apiFetch<T>(path);
}

/** POST helper. */
async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** PATCH helper. */
async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** DELETE helper. */
async function apiDelete<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: 'DELETE' });
}

// ============================================================================
// Health & Status
// ============================================================================

export async function getHealth(): Promise<{ status: string; model_loaded: boolean }> {
  return apiGet('/api/health');
}

export async function getStatus(): Promise<DatabaseStatus> {
  return apiGet('/api/status');
}

// ============================================================================
// Fun Facts
// ============================================================================

export interface FunFact {
  category: string;
  display_text: string;
}

export async function getRandomFunFact(): Promise<FunFact> {
  return apiGet('/api/fun-fact');
}

// ============================================================================
// Predictions
// ============================================================================

export async function predictListing(url: string): Promise<ListingPredictionResponse> {
  return apiPost('/api/predict/listing', { url });
}

export async function predictManual(
  payload: ManualPredictPayload,
): Promise<{ prediction: PredictionResult }> {
  return apiPost('/api/predict/manual', payload);
}

export async function predictMapClick(
  latitude: number,
  longitude: number,
): Promise<MapClickResponse> {
  return apiPost('/api/predict/map-click', { latitude, longitude });
}

// ============================================================================
// Neighborhoods
// ============================================================================

export async function getNeighborhoods(
  minSales?: number,
  years?: number,
): Promise<NeighborhoodStats[]> {
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
  const qs = years != null ? `?years=${years}` : '';
  return apiGet(`/api/neighborhoods/${encodeURIComponent(name)}${qs}`);
}

export async function getNeighborhoodGeoJson(): Promise<NeighborhoodGeoJson> {
  return apiGet('/api/neighborhoods/geojson');
}

// ============================================================================
// Market
// ============================================================================

export async function getMarketTrend(months?: number): Promise<MarketSnapshot[]> {
  const qs = months != null ? `?months=${months}` : '';
  return apiGet(`/api/market/trend${qs}`);
}

export async function getMarketSummary(): Promise<MarketSummary> {
  return apiGet('/api/market/summary');
}

// ============================================================================
// Model
// ============================================================================

export async function getModelInfo(): Promise<ModelInfo> {
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
  return apiPost('/api/faketor/chat', payload);
}

// ---------------------------------------------------------------------------
// SSE streaming chat
// ---------------------------------------------------------------------------

export interface StreamCallbacks {
  onTextDelta: (text: string) => void;
  onToolStart: (name: string, label: string) => void;
  onToolResult: (name: string, block: ResponseBlock | null) => void;
  onDone: (reply: string, toolCalls: { name: string; input: Record<string, unknown> }[], blocks: ResponseBlock[]) => void;
  onWorkingSet: (meta: WorkingSetMeta) => void;
  onError: (message: string) => void;
}

/**
 * Stream a Faketor chat message via SSE.
 * Returns an AbortController so the caller can cancel.
 */
export function streamFaketorMessage(
  payload: {
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
  },
  callbacks: StreamCallbacks,
): AbortController {
  const controller = new AbortController();

  (async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/faketor/chat/stream`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        callbacks.onError(data.detail ?? `HTTP ${resp.status}`);
        return;
      }

      const reader = resp.body?.getReader();
      if (!reader) {
        callbacks.onError('No response body');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events from the buffer
        const parts = buffer.split('\n\n');
        buffer = parts.pop() ?? '';

        for (const part of parts) {
          const lines = part.split('\n');
          let eventType = '';
          let eventData = '';

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7);
            } else if (line.startsWith('data: ')) {
              eventData = line.slice(6);
            }
          }

          if (!eventType || !eventData) continue;

          try {
            // Parse and coerce string-encoded numerics at the boundary.
            // This is the single point where backend JSON enters the frontend.
            const raw = JSON.parse(eventData);
            const data = coerceBlockData(raw);

            switch (eventType) {
              case 'text_delta':
                callbacks.onTextDelta(data.text);
                break;
              case 'tool_start':
                callbacks.onToolStart(data.name, data.label);
                break;
              case 'tool_result':
                callbacks.onToolResult(data.name, data.block ?? null);
                break;
              case 'done':
                callbacks.onDone(data.reply, data.tool_calls ?? [], data.blocks ?? []);
                break;
              case 'working_set':
                callbacks.onWorkingSet(data as WorkingSetMeta);
                break;
              case 'error':
                callbacks.onError(data.message);
                break;
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      callbacks.onError(err instanceof Error ? err.message : 'Stream connection failed');
    }
  })();

  return controller;
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

// ============================================================================
// Authentication
// ============================================================================

export async function authRegister(
  email: string,
  password: string,
  full_name?: string,
  accepted_tos_version?: string,
): Promise<AuthResponse> {
  return apiPost('/api/auth/register', {
    email,
    password,
    full_name: full_name ?? null,
    accepted_tos_version: accepted_tos_version ?? null,
  });
}

export async function authLogin(email: string, password: string): Promise<AuthResponse> {
  return apiPost('/api/auth/login', { email, password });
}

export async function authGetMe(): Promise<User> {
  return apiGet('/api/auth/me');
}

export async function authLogout(): Promise<void> {
  const refreshToken = getStoredRefreshToken();
  if (refreshToken) {
    // Best-effort server-side revocation — don't block on failure
    fetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    }).catch(() => {});
  }
  clearStoredToken();
}

export async function authAcceptTos(): Promise<{ detail: string; version: string }> {
  return apiPost('/api/auth/accept-tos', {});
}

export async function authChangePassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ detail: string }> {
  return apiPost('/api/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export async function authGetActivity(
  limit = 20,
  offset = 0,
): Promise<AuthActivityEvent[]> {
  return apiGet(`/api/auth/activity?limit=${limit}&offset=${offset}`);
}

export async function authDeactivateAccount(password: string): Promise<{ detail: string }> {
  return apiPost('/api/auth/deactivate', { password });
}

export async function authDeleteAccount(password: string): Promise<{ detail: string }> {
  return apiFetch('/api/auth/account', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
}

export async function authForgotPassword(email: string): Promise<{ detail: string }> {
  return apiPost('/api/auth/forgot-password', { email });
}

export async function authResetPassword(
  token: string,
  newPassword: string,
): Promise<{ detail: string }> {
  return apiPost('/api/auth/reset-password', { token, new_password: newPassword });
}

// ============================================================================
// Conversations
// ============================================================================

export async function listConversations(): Promise<Conversation[]> {
  return apiGet('/api/conversations');
}

export async function createConversation(
  session_id: string,
  title?: string,
): Promise<{ id: number; session_id: string; title: string | null }> {
  return apiPost('/api/conversations', { session_id, title: title ?? null });
}

export async function getConversation(id: number): Promise<ConversationDetail> {
  return apiGet(`/api/conversations/${id}`);
}

export async function updateConversationTitle(
  id: number,
  title: string,
): Promise<{ ok: boolean }> {
  return apiPatch(`/api/conversations/${id}`, { title });
}

export async function deleteConversation(id: number): Promise<{ ok: boolean }> {
  return apiDelete(`/api/conversations/${id}`);
}

export async function saveConversationMessages(
  conversationId: number,
  messages: {
    role: string;
    content: string;
    blocks_json?: string | null;
    tools_used_json?: string | null;
    tool_events_json?: string | null;
  }[],
): Promise<{ ok: boolean; message_ids: number[] }> {
  return apiPost(`/api/conversations/${conversationId}/messages`, { messages });
}
