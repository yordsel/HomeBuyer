/**
 * Runtime coercion for SSE block data parsed from JSON.
 *
 * The backend may serialize Python Decimal, numpy, or other non-standard
 * numeric types as strings via `json.dumps(default=str)`. While the backend
 * now uses `SafeEncoder` to prevent this, this module provides a defensive
 * second layer at the frontend parse boundary.
 *
 * Instead of maintaining 15+ Zod schemas that mirror TypeScript interfaces,
 * we use a generic recursive approach: walk the parsed object and coerce any
 * string that looks numeric into an actual `number`. This is safe because:
 *
 *   1. JSON has no "string vs number ambiguity" — if the backend intended a
 *      string, it won't look like a pure number (e.g., addresses, dates).
 *   2. Fields like zip codes ("94703") ARE numeric strings, but they're
 *      consumed as strings by the UI anyway — calling `formatCurrency("94703")`
 *      or `.toFixed()` on them would be a bug regardless.
 *   3. We exclude strings that contain non-numeric chars (hyphens, slashes,
 *      letters, spaces) so dates like "2026-03-12" and addresses stay as
 *      strings.
 *
 * Usage:
 *   const data = coerceBlockData(JSON.parse(eventData));
 */

/**
 * Strict numeric string pattern.
 * Matches: "123", "-45.6", "0.5", "+3", "1e10", "-2.5E-3", ".5"
 * Does NOT match: "2026-03-12", "94703-1234", "hello", "", " 5 ", "1,000"
 */
const NUMERIC_RE = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

/**
 * Recursively coerce string-encoded numbers in a parsed JSON object.
 *
 * - Walks arrays and plain objects recursively.
 * - Converts string values that match a strict numeric pattern to `number`.
 * - Leaves non-matching strings, booleans, nulls, and existing numbers as-is.
 * - Returns a new object (does not mutate the input).
 */
export function coerceBlockData<T>(value: T): T {
  if (value === null || value === undefined) {
    return value;
  }

  // String → try numeric coercion
  if (typeof value === 'string') {
    if (NUMERIC_RE.test(value)) {
      const n = Number(value);
      // Guard against edge cases: NaN, Infinity
      if (Number.isFinite(n)) {
        return n as unknown as T;
      }
    }
    return value;
  }

  // Arrays → recurse into each element
  if (Array.isArray(value)) {
    return value.map((item) => coerceBlockData(item)) as unknown as T;
  }

  // Plain objects → recurse into each value
  if (typeof value === 'object') {
    const result: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      result[k] = coerceBlockData(v);
    }
    return result as T;
  }

  // number, boolean — return as-is
  return value;
}
