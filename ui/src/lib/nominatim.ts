/**
 * Nominatim (OpenStreetMap) forward-geocoding client.
 *
 * Scoped to the Berkeley, CA bounding box and rate-limited to
 * one request per second per Nominatim usage policy.
 */

// Berkeley bounding box (west, south, east, north → Nominatim wants west,north,east,south for viewbox)
const VIEWBOX = '-122.34,37.92,-122.22,37.84'; // west, north, east, south

const MIN_QUERY_LENGTH = 3;
const MIN_REQUEST_INTERVAL_MS = 1_100; // >1 s between requests

let lastRequestTime = 0;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NominatimAddress {
  house_number?: string;
  road?: string;
  city?: string;
  postcode?: string;
  state?: string;
  [key: string]: string | undefined;
}

export interface NominatimResult {
  place_id: number;
  lat: string;
  lon: string;
  display_name: string;
  address: NominatimAddress;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a short, human-friendly address from the verbose Nominatim result. */
export function formatResultAddress(result: NominatimResult): string {
  const { house_number, road, postcode } = result.address;
  const parts: string[] = [];

  if (house_number && road) {
    parts.push(`${house_number} ${road}`);
  } else if (road) {
    parts.push(road);
  }

  if (postcode) {
    parts.push(postcode);
  }

  return parts.length > 0 ? parts.join(', ') : result.display_name.split(',')[0];
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

/**
 * Search Nominatim for addresses within the Berkeley bounding box.
 *
 * Returns an empty array if the query is too short or if the request
 * is throttled by the rate limiter.
 */
export async function searchAddresses(
  query: string,
  limit = 5,
): Promise<NominatimResult[]> {
  const trimmed = query.trim();
  if (trimmed.length < MIN_QUERY_LENGTH) return [];

  // Rate limiting
  const now = Date.now();
  if (now - lastRequestTime < MIN_REQUEST_INTERVAL_MS) return [];
  lastRequestTime = now;

  const params = new URLSearchParams({
    q: trimmed,
    format: 'json',
    addressdetails: '1',
    viewbox: VIEWBOX,
    bounded: '1',
    countrycodes: 'us',
    limit: String(limit),
  });

  const url = `https://nominatim.openstreetmap.org/search?${params}`;

  const res = await fetch(url, {
    headers: {
      'User-Agent': 'HomeBuyer-BerkeleyPricePredictor/0.1 (student project)',
    },
  });

  if (!res.ok) return [];

  const data: NominatimResult[] = await res.json();
  return data;
}
