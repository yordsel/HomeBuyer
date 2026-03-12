/**
 * Pure utility functions for computing context panel header summaries
 * from the tracked properties array.
 */
import type { TrackedProperty } from '../../context/PropertyContext';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Compact currency for header display: $2.8M, $850K, etc. */
export function formatCompactCurrency(amount: number): string {
  const n = Number(amount);
  if (n >= 1_000_000) {
    const m = n / 1_000_000;
    return `$${m % 1 === 0 ? m.toFixed(0) : m.toFixed(1)}M`;
  }
  if (n >= 1_000) {
    const k = Math.round(n / 1_000);
    return `$${k}K`;
  }
  return `$${Math.round(n)}`;
}

/** Extract predicted price from blocks first, then property summary data. */
function getPredictedPrice(tracked: TrackedProperty): number | null {
  const predBlock = tracked.blocks.find((b) => b.type === 'prediction_card');
  if (predBlock && predBlock.type === 'prediction_card') {
    return predBlock.data.predicted_price ?? null;
  }
  return tracked.property.predicted_price ?? null;
}

// ---------------------------------------------------------------------------
// Multi-property summary (1-3 lines)
// ---------------------------------------------------------------------------

/**
 * Compute concise summary lines for the context panel header
 * when multiple properties are tracked.  Mirrors the backend
 * SessionWorkingSet.get_descriptor() format so the UI is
 * consistent regardless of whether we have backend metadata.
 */
export function getMultiPropertySummaryLines(
  properties: TrackedProperty[],
): string[] {
  const lines: string[] = [];

  // --- Neighborhoods with counts (top 3) ---
  const neighborhoods: Record<string, number> = {};
  for (const t of properties) {
    const n = t.property.neighborhood;
    if (n) neighborhoods[n] = (neighborhoods[n] ?? 0) + 1;
  }
  const nhoods = Object.entries(neighborhoods).sort((a, b) => b[1] - a[1]);
  if (nhoods.length > 0) {
    const top = nhoods.slice(0, 3).map(([n, c]) => `${n} (${c})`).join(', ');
    const suffix = nhoods.length > 3 ? `, +${nhoods.length - 3} more` : '';
    lines.push(`Neighborhoods: ${top}${suffix}`);
  }

  // --- Property types with counts (top 3) ---
  const types: Record<string, number> = {};
  for (const t of properties) {
    const pt = t.property.property_type;
    if (pt) types[pt] = (types[pt] ?? 0) + 1;
  }
  const typeEntries = Object.entries(types).sort((a, b) => b[1] - a[1]);
  if (typeEntries.length > 0) {
    const top = typeEntries.slice(0, 3).map(([n, c]) => `${n} (${c})`).join(', ');
    lines.push(`Types: ${top}`);
  }

  // --- Lot size range ---
  const lots = properties
    .map((t) => t.property.lot_size_sqft)
    .filter((v): v is number => v != null && v > 0)
    .sort((a, b) => a - b);
  if (lots.length >= 2) {
    const med = lots[Math.floor(lots.length / 2)];
    lines.push(
      `Lot size: ${lots[0].toLocaleString()} – ${lots[lots.length - 1].toLocaleString()} sqft (median ${med.toLocaleString()})`,
    );
  }

  // --- Zoning distribution (top 3) ---
  const zones: Record<string, number> = {};
  for (const t of properties) {
    const z = t.property.zoning_class;
    if (z) zones[z] = (zones[z] ?? 0) + 1;
  }
  const zoneEntries = Object.entries(zones).sort((a, b) => b[1] - a[1]);
  if (zoneEntries.length > 0) {
    const top = zoneEntries.slice(0, 3).map(([z, c]) => `${z} (${c})`).join(', ');
    const suffix = zoneEntries.length > 3 ? `, +${zoneEntries.length - 3} more` : '';
    lines.push(`Zoning: ${top}${suffix}`);
  }

  // Fallback if no data lines generated
  if (lines.length === 0) {
    lines.push(`${properties.length} properties`);
  }

  return lines.slice(0, 4);
}

// ---------------------------------------------------------------------------
// Single-property summary (1 line)
// ---------------------------------------------------------------------------

/**
 * Compute a single concise summary line for the context panel header
 * when exactly one property is tracked.
 */
export function getSinglePropertySummaryLine(
  tracked: TrackedProperty,
): string {
  const price = getPredictedPrice(tracked);
  const { property } = tracked;

  if (price != null) {
    const suffix = property.zoning_class
      ? ` · ${property.zoning_class}`
      : '';
    return `Est. ${formatCompactCurrency(price)}${suffix}`;
  }

  if (property.last_sale_price != null) {
    return `Last sold ${formatCompactCurrency(property.last_sale_price)}`;
  }

  if (property.neighborhood) {
    return property.neighborhood;
  }

  return property.property_type ?? '';
}
