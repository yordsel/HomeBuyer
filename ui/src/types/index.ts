// ---------------------------------------------------------------------------
// Prediction
// ---------------------------------------------------------------------------

export interface FeatureContribution {
  name: string;        // human-readable label
  value: number;       // dollar contribution (positive or negative)
  raw_feature: string; // internal feature name
}

export interface PredictionResult {
  predicted_price: number;
  price_lower: number;
  price_upper: number;
  neighborhood: string | null;
  list_price: number | null;
  predicted_premium_pct: number | null;
  base_value: number | null;
  feature_contributions: FeatureContribution[] | null;
}

export interface ListingData {
  address: string;
  city: string;
  state: string;
  zip_code: string;
  latitude: number;
  longitude: number;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  year_built: number | null;
  lot_size_sqft: number | null;
  property_type: string;
  list_price: number | null;
  neighborhood: string | null;
  redfin_url: string;
  property_id: string | null;
  sale_date: string | null;
  hoa_per_month: number | null;
  garage_spaces: number | null;
  last_sale_price: number | null;
  last_sale_date: string | null;
}

export interface ListingPredictionResponse {
  listing: ListingData;
  prediction: PredictionResult;
  comparables: ComparableProperty[];
}

export interface ManualPredictPayload {
  neighborhood: string;
  zip_code?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  year_built?: number;
  lot_size_sqft?: number;
  hoa_per_month?: number;
  latitude?: number;
  longitude?: number;
  property_type?: string;
  list_price?: number;
}

// ---------------------------------------------------------------------------
// Map-click prediction
// ---------------------------------------------------------------------------

export type PredictMode = 'url' | 'map';

export interface AttomPrefill {
  beds?: number;
  baths?: number;
  sqft?: number;
  year_built?: number;
  lot_size_sqft?: number;
  property_type?: string;
}

export interface MapClickLocationInfo {
  latitude: number;
  longitude: number;
  neighborhood: string;
  zip_code: string;
  zoning_class: string | null;
  address: string | null;
  attom_prefill?: AttomPrefill;
}

export interface MapClickResponse {
  status: 'prediction' | 'needs_details' | 'error';
  // When status === 'prediction':
  listing?: ListingData;
  prediction?: PredictionResult;
  comparables?: ComparableProperty[];
  // When status === 'needs_details':
  location_info?: MapClickLocationInfo;
  // When status === 'error':
  error?: string;
  error_code?: 'not_residential' | 'not_in_berkeley' | 'no_zone';
}

// ---------------------------------------------------------------------------
// Neighborhoods
// ---------------------------------------------------------------------------

export interface NeighborhoodStats {
  name: string;
  sale_count: number;
  median_price: number | null;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
  median_ppsf: number | null;
  avg_ppsf: number | null;
  median_sqft: number | null;
  avg_year_built: number | null;
  yoy_price_change_pct: number | null;
  median_lot_size: number | null;
  property_type_breakdown: Record<string, number>;
  dominant_zoning: string[];
  zoning_breakdown: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Market
// ---------------------------------------------------------------------------

export interface MarketSnapshot {
  period: string;
  median_sale_price: number | null;
  median_list_price: number | null;
  sale_to_list_ratio: number | null;
  sold_above_list_pct: number | null;
  homes_sold: number | null;
  inventory: number | null;
  median_dom: number | null;
  mortgage_rate_30yr: number | null;
}

export interface MarketSummary {
  data_coverage: {
    total_sales: number;
    date_range: { earliest: string; latest: string };
    neighborhoods_covered: number;
  };
  current_market: {
    period: string;
    median_sale_price: number | null;
    median_list_price: number | null;
    sale_to_list_ratio: number | null;
    sold_above_list_pct: number | null;
    homes_sold_monthly: number | null;
    median_days_on_market: number | null;
    mortgage_rate_30yr: number | null;
  };
  price_distribution_2yr: { bracket: string; count: number }[];
  top_neighborhoods_by_price: {
    name: string;
    median_price: number | null;
    avg_ppsf: number | null;
    sales: number;
    yoy_change: number | null;
  }[];
  property_type_prices: {
    type: string;
    count: number;
    avg_price: number;
  }[];
  zoning_price_insights: {
    zone_category: string;
    count: number;
    avg_price: number;
    avg_ppsf: number | null;
  }[];
}

// ---------------------------------------------------------------------------
// Comparables
// ---------------------------------------------------------------------------

export interface ComparableProperty {
  address: string;
  sale_date: string;
  sale_price: number;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  lot_size_sqft: number | null;
  year_built: number | null;
  neighborhood: string | null;
  price_per_sqft: number | null;
  distance_score: number;
  latitude: number | null;
  longitude: number | null;
}

// ---------------------------------------------------------------------------
// GeoJSON (Neighborhood Boundaries)
// ---------------------------------------------------------------------------

export interface GeoJsonFeature {
  type: 'Feature';
  properties: { name: string };
  geometry: {
    type: 'Polygon' | 'MultiPolygon';
    coordinates: number[][][] | number[][][][];
  };
}

export interface NeighborhoodGeoJson {
  type: 'FeatureCollection';
  features: GeoJsonFeature[];
}

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------

export interface ModelInfo {
  trained_at: string;
  data_cutoff_date: string;
  train_size: number;
  test_size: number;
  feature_count: number;
  feature_names: string[];
  metrics: {
    mae: number;
    mape: number;
    r2: number;
    within_10pct: number;
    within_20pct: number;
    interval_coverage?: number;
  };
  hyperparameters: Record<string, number | string>;
  feature_importances: Record<string, number>;
  neighborhood_metrics: {
    neighborhood: string;
    test_count: number;
    mape: number;
    mae: number;
    within_10pct: number;
  }[];
  data_completeness: Record<string, {
    label: string;
    filled: number;
    total: number;
    pct: number;
  }>;
}

// ---------------------------------------------------------------------------
// Affordability
// ---------------------------------------------------------------------------

export interface AffordabilityResult {
  monthly_budget: number;
  mortgage_rate_30yr: number;
  max_affordable_price: number;
  down_payment_amount: number;
  loan_amount: number;
  is_jumbo_loan: boolean;
  jumbo_threshold: number;
  affordable_neighborhoods: {
    name: string;
    recent_sales_in_range: number;
    avg_price: number;
    lowest_recent_sale: number;
    property_type_breakdown: Record<string, number>;
    dominant_zoning: string[];
  }[];
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

export interface DatabaseStatus {
  property_sales: { count: number; min_date: string; max_date: string };
  neighborhood_coverage: { geocoded: number; total: number; pct: number };
  market_metrics: { count: number; min_date: string; max_date: string };
  mortgage_rates: { count: number; min_date: string; max_date: string };
  economic_indicators: { count: number; min_date: string; max_date: string };
  census_income: { count: number; zip_codes: string; min_year: number; max_year: number };
  neighborhoods: { count: number };
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export type PageId = 'predict' | 'neighborhoods' | 'market' | 'model' | 'afford';
