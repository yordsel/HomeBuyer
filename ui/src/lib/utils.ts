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
