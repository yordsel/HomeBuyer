/**
 * Format a number as USD currency.
 */
export function formatCurrency(amount: number | null | undefined): string {
  if (amount == null) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(amount);
}

/**
 * Format a number with commas.
 */
export function formatNumber(n: number | null | undefined): string {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US').format(n);
}

/**
 * Format a percentage with one decimal place and a sign.
 */
export function formatPct(pct: number | null | undefined, showSign = false): string {
  if (pct == null) return '—';
  const prefix = showSign && pct > 0 ? '+' : '';
  return `${prefix}${pct.toFixed(1)}%`;
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
 * Truncate a string to a max length with ellipsis.
 */
export function truncate(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen - 1) + '\u2026';
}
