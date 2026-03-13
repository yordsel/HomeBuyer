/**
 * Format a number as USD currency.
 */
export function formatCurrency(amount: number | string | null | undefined): string {
  if (amount == null) return '—';
  const n = typeof amount === 'string' ? parseFloat(amount) : amount;
  if (isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(n);
}

/**
 * Format a number with commas.
 */
export function formatNumber(n: number | string | null | undefined): string {
  if (n == null) return '—';
  const num = typeof n === 'string' ? parseFloat(n) : n;
  if (isNaN(num)) return '—';
  return new Intl.NumberFormat('en-US').format(num);
}

/**
 * Format a percentage with one decimal place and a sign.
 */
export function formatPct(pct: number | string | null | undefined, showSign = false): string {
  if (pct == null) return '—';
  const n = typeof pct === 'string' ? parseFloat(pct) : pct;
  if (isNaN(n)) return '—';
  const prefix = showSign && n > 0 ? '+' : '';
  return `${prefix}${n.toFixed(1)}%`;
}

/**
 * Format a date string (YYYY-MM-DD) as "Mar 3, 2026".
 */
export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/**
 * Get today's date as YYYY-MM-DD.
 */
export function getTodayString(): string {
  return new Date().toISOString().split('T')[0];
}

/**
 * Format a number as compact USD: $1.2M, $345K, or full currency for small values.
 */
export function formatCompact(n: number | string | null | undefined): string {
  if (n == null) return '—';
  const num = typeof n === 'string' ? parseFloat(n) : n;
  if (isNaN(num)) return '—';
  if (Math.abs(num) >= 1_000_000) return `$${(num / 1_000_000).toFixed(1)}M`;
  if (Math.abs(num) >= 1_000) return `$${(num / 1_000).toFixed(0)}K`;
  return formatCurrency(num);
}

/**
 * Safely coerce a value to a number.
 * Returns the numeric value, or `fallback` (default 0) when the input is
 * null, undefined, NaN, or a non-numeric string.  This is the primary
 * defence against `json.dumps(…, default=str)` serialising Python Decimal
 * or other exotic numerics as strings.
 */
export function toNum(v: unknown, fallback = 0): number {
  if (v == null) return fallback;
  const n = typeof v === 'string' ? parseFloat(v) : Number(v);
  return isNaN(n) ? fallback : n;
}

/**
 * Format a backend tool name for display: strip common prefixes, replace
 * underscores with spaces, and title-case each word.
 */
export function formatToolName(name: string): string {
  return name
    .replace(/^(get_|estimate_|analyze_|lookup_)/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Truncate a string to a max length with ellipsis.
 */
export function truncate(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen - 1) + '\u2026';
}

// ---------------------------------------------------------------------------
// Chart / time-series utilities
// ---------------------------------------------------------------------------

/**
 * Compute a trailing moving average for a numeric series.
 *
 * Previously duplicated in TrendChart.tsx and AboveListChart.tsx.
 *
 * @param values  Array of nullable numbers (null entries are skipped).
 * @param window  Number of trailing periods (default 12).
 * @param minPoints  Minimum non-null points in the window to emit a
 *                   value (default 3).
 * @returns  Array of the same length with computed averages (or null).
 */
export function computeMovingAverage(
  values: (number | null)[],
  window = 12,
  minPoints = 3,
): (number | null)[] {
  return values.map((_, i) => {
    const start = Math.max(0, i - window + 1);
    const slice = values.slice(start, i + 1).filter((v): v is number => v != null);
    if (slice.length >= Math.min(window, i + 1) && slice.length >= minPoints) {
      return slice.reduce((s, v) => s + v, 0) / slice.length;
    }
    return null;
  });
}

export type TrendDirection = 'rising' | 'declining' | 'stable' | null;

export interface TrendInfo {
  label: string;
  color: string;
  direction: TrendDirection;
}

/**
 * Determine trend direction from the last N values of a moving average.
 *
 * Previously duplicated in TrendChart.tsx and AboveListChart.tsx.
 *
 * @param maValues  Array of non-null MA values.
 * @param lookback  Number of recent points to compare (default 6).
 * @param threshold  Percentage change threshold for "stable" band (default 3).
 * @param invertColors  If true, rising = red and declining = green
 *                      (used for "sold above list" chart where lower is better
 *                      for buyers). Default false.
 */
export function getTrendInfo(
  maValues: number[],
  lookback = 6,
  threshold = 3,
  invertColors = false,
): TrendInfo {
  if (maValues.length < lookback) {
    return { label: '', color: 'text-gray-500', direction: null };
  }

  const recent = maValues.slice(-lookback);
  const first = recent[0];
  const last = recent[recent.length - 1];
  const pctChange = ((last - first) / Math.abs(first)) * 100;

  const risingColor = invertColors ? 'text-red-600' : 'text-green-600';
  const decliningColor = invertColors ? 'text-green-600' : 'text-red-600';

  if (pctChange < -threshold) {
    return { label: 'Declining', color: decliningColor, direction: 'declining' };
  }
  if (pctChange > threshold) {
    return { label: 'Rising', color: risingColor, direction: 'rising' };
  }
  return { label: 'Stable', color: 'text-amber-600', direction: 'stable' };
}
