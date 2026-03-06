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
// Development Potential
// ---------------------------------------------------------------------------

export interface ZoningDetail {
  zone_class: string;
  zone_desc: string | null;
  general_plan: string | null;
}

export interface ZoneRuleDetail {
  max_lot_coverage_pct: number;
  max_height_ft: number;
  is_hillside: boolean;
  residential: boolean;
}

export interface UnitPotential {
  base_max_units: number;
  middle_housing_eligible: boolean;
  middle_housing_max_units: number | null;
  effective_max_units: number;
}

export interface ADUFeasibility {
  eligible: boolean;
  max_adu_sqft: number;
  remaining_lot_coverage_sqft: number | null;
  notes: string;
}

export interface SB9Eligibility {
  eligible: boolean;
  can_split: boolean;
  resulting_lot_sizes: number[] | null;
  max_total_units: number;
  notes: string;
}

export interface BESORecordData {
  beso_id: string;
  building_address: string;
  beso_property_type: string | null;
  floor_area: number | null;
  energy_star_score: number | null;
  site_eui: number | null;
  benchmark_status: string | null;
  assessment_status: string | null;
  reporting_year: number | null;
}

export interface ImprovementROI {
  category: string;
  avg_job_value: number;
  avg_ppsf_premium_pct: number;
  sample_count: number;
}

export interface DevelopmentPotentialResponse {
  zoning: ZoningDetail | null;
  zone_rule: ZoneRuleDetail | null;
  units: UnitPotential | null;
  adu: ADUFeasibility | null;
  sb9: SB9Eligibility | null;
  beso: BESORecordData[];
  improvements: ImprovementROI[];
}

// ---------------------------------------------------------------------------
// Improvement Simulation
// ---------------------------------------------------------------------------

export interface ImprovementSimCategory {
  category: string;
  avg_permit_cost: number;
  ml_predicted_delta: number;
  ml_roi_ratio: number;
  correlation_premium_pct: number | null;
  sample_count: number;
}

export interface ImprovementSimResponse {
  current_price: number;
  improved_price: number;
  total_delta: number;
  total_cost: number;
  roi_ratio: number;
  categories: ImprovementSimCategory[];
  error?: string;
}

// ---------------------------------------------------------------------------
// AI Potential Summary
// ---------------------------------------------------------------------------

export interface AIPotentialSummary {
  summary: string;
  recommendation: string;
  caveats: string[];
  highlights: string[];
}

export interface PotentialSummaryResponse {
  potential: DevelopmentPotentialResponse;
  ai_summary: AIPotentialSummary | null;
  ai_error?: string;
}

// ---------------------------------------------------------------------------
// Rental Income & Investment Analysis
// ---------------------------------------------------------------------------

export interface RentEstimate {
  unit_type: string;
  beds: number;
  baths: number;
  sqft: number | null;
  monthly_rent: number;
  annual_rent: number;
  estimation_method: string;
  confidence: string;
  notes: string;
}

export interface ExpenseBreakdown {
  property_tax: number;
  insurance: number;
  maintenance: number;
  vacancy_reserve: number;
  management_fee: number;
  hoa: number;
  utilities: number;
  total_annual: number;
  expense_ratio_pct: number;
}

export interface MortgageAnalysis {
  property_value: number;
  down_payment_pct: number;
  down_payment_amount: number;
  loan_amount: number;
  rate_30yr: number;
  monthly_pi: number;
  monthly_tax: number;
  monthly_insurance: number;
  monthly_piti: number;
  is_jumbo: boolean;
  annual_interest_yr1: number;
  annual_principal_yr1: number;
}

export interface TaxBenefits {
  depreciation_annual: number;
  mortgage_interest_deduction: number;
  operating_expense_deductions: number;
  estimated_tax_savings: number;
  marginal_tax_rate_used: number;
  notes: string[];
}

export interface AnnualCashFlow {
  year: number;
  gross_rent: number;
  operating_expenses: number;
  noi: number;
  mortgage_payment: number;
  cash_flow: number;
  equity_buildup: number;
  property_value: number;
  cumulative_equity: number;
  total_return: number;
}

export interface InvestmentScenario {
  scenario_name: string;
  scenario_type: string;
  property_value: number;
  additional_investment: number;
  total_investment: number;
  units: RentEstimate[];
  total_monthly_rent: number;
  total_annual_rent: number;
  expenses: ExpenseBreakdown;
  mortgage: MortgageAnalysis;
  cap_rate_pct: number;
  cash_on_cash_pct: number;
  gross_rent_multiplier: number;
  price_to_rent_ratio: number;
  monthly_cash_flow: number;
  projections: AnnualCashFlow[];
  tax_benefits: TaxBenefits;
  development_feasible: boolean;
  development_notes: string;
}

export interface RentalAnalysisResponse {
  property_address: string | null;
  property_value: number;
  neighborhood: string;
  scenarios: InvestmentScenario[];
  best_scenario: string;
  recommendation_notes: string;
  data_sources: string[];
  disclaimers: string[];
}

// ---------------------------------------------------------------------------
// Faketor Chat
// ---------------------------------------------------------------------------

export interface FaketorMessage {
  role: 'user' | 'assistant';
  content: string;
}

export type ResponseBlockType =
  | 'prediction_card'
  | 'comps_table'
  | 'neighborhood_stats'
  | 'development_potential'
  | 'improvement_sim'
  | 'sell_vs_hold'
  | 'rental_income'
  | 'investment_scenarios'
  | 'market_summary'
  | 'property_detail';

export interface ResponseBlock {
  type: ResponseBlockType;
  tool_name: string;
  data: Record<string, unknown>;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  blocks?: ResponseBlock[];
  toolsUsed?: string[];
}

export interface FaketorChatResponse {
  reply: string;
  tool_calls?: { name: string; input: Record<string, unknown> }[];
  blocks?: ResponseBlock[];
  error?: string;
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export type PageId = 'chat' | 'predict' | 'neighborhoods' | 'market' | 'model' | 'afford' | 'potential';
