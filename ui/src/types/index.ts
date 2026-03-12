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

export interface PropertyPrefill {
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
  property_prefill?: PropertyPrefill;
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
// Investment Prospectus
// ---------------------------------------------------------------------------

export interface ProspectusComparable {
  address: string;
  sale_price: number;
  sale_date: string;
  beds?: number | null;
  baths?: number | null;
  sqft?: number | null;
  price_per_sqft?: number | null;
}

export interface ProspectusScenario {
  scenario_name?: string;
  scenario_type?: string;
  property_value?: number;
  additional_investment?: number;
  total_investment?: number;
  total_monthly_rent?: number;
  total_annual_rent?: number;
  cap_rate_pct?: number;
  cash_on_cash_pct?: number;
  monthly_cash_flow?: number;
  gross_rent_multiplier?: number;
  development_feasible?: boolean;
  development_notes?: string;
  units?: Array<{
    unit_type: string;
    beds: number;
    baths: number;
    sqft: number | null;
    monthly_rent: number;
  }>;
  expenses?: {
    property_tax: number;
    insurance: number;
    maintenance: number;
    vacancy_reserve: number;
    management_fee: number;
    hoa: number;
    utilities: number;
    total_annual: number;
    expense_ratio_pct: number;
  };
  mortgage?: {
    down_payment_amount: number;
    loan_amount: number;
    rate_30yr: number;
    monthly_piti: number;
  };
  projections?: Array<{
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
  }>;
  tax_benefits?: {
    depreciation_annual: number;
    mortgage_interest_deduction: number;
    estimated_tax_savings: number;
  };
}

export interface PropertyProspectus {
  // Property Overview
  address?: string | null;
  neighborhood: string;
  property_type: string;
  beds?: number | null;
  baths?: number | null;
  sqft?: number | null;
  year_built?: number | null;
  lot_size_sqft?: number | null;
  zoning_class?: string | null;

  // Valuation
  estimated_value: number;
  value_range_low: number;
  value_range_high: number;
  value_per_sqft?: number | null;

  // Market Context
  neighborhood_median_price?: number | null;
  neighborhood_yoy_change_pct?: number | null;
  neighborhood_avg_ppsf?: number | null;
  city_median_price?: number | null;
  mortgage_rate_30yr?: number | null;
  median_dom?: number | null;
  comparable_sales: ProspectusComparable[];

  // Development Potential
  adu_eligible: boolean;
  adu_max_sqft?: number | null;
  sb9_eligible: boolean;
  sb9_can_split: boolean;
  middle_housing_eligible: boolean;
  middle_housing_max_units?: number | null;
  effective_max_units: number;
  development_notes: string;

  // Investment Scenarios
  scenarios: ProspectusScenario[];
  best_scenario_name: string;
  recommendation_notes: string;

  // Recommended Strategy
  recommended_approach: string;
  recommended_approach_label: string;
  strategy_rationale: string;
  capital_required: number;
  time_horizon_years: number;
  projected_total_return: number;
  projected_annual_return_pct: number;
  monthly_cash_flow: number;

  // Risk Factors
  risk_factors: string[];

  // Key Metrics
  cap_rate_pct: number;
  cash_on_cash_pct: number;
  gross_rent_multiplier: number;
  price_to_rent_ratio: number;

  // Narrative commentaries
  valuation_commentary?: string;
  market_position_commentary?: string;
  scenario_recommendation_narrative?: string;
  comps_analysis_narrative?: string;
  risk_mitigation_narrative?: string;

  // Best scenario detail for charts
  best_scenario_detail?: ProspectusScenario | null;

  // Metadata
  generated_at: string;
  data_sources: string[];
  disclaimers: string[];
}

export interface PortfolioComparisonMetric {
  address: string;
  estimated_value: number;
  cap_rate_pct: number;
  cash_on_cash_pct: number;
  monthly_cash_flow: number;
  strategy: string;
}

export interface GroupStatistics {
  count: number;
  avg_price: number;
  median_price: number;
  min_price: number;
  max_price: number;
  avg_cap_rate: number;
  avg_coc: number;
  price_distribution: Array<{ bracket: string; count: number }>;
  common_neighborhoods: string[];
  common_zoning: string[];
}

export interface PortfolioSummary {
  total_capital_required: number;
  total_monthly_cash_flow: number;
  weighted_avg_cap_rate: number;
  weighted_avg_coc: number;
  property_count: number;
  diversification_notes: string;

  // Multi-property mode
  mode?: string;
  investment_thesis?: string;

  // Similar mode
  shared_traits?: string[];
  individual_differences?: string[];

  // Thesis mode
  group_statistics?: GroupStatistics | null;
  example_property_indices?: number[];

  // Chart data
  comparison_metrics?: PortfolioComparisonMetric[];
  neighborhood_allocation?: Record<string, number>;
  strategy_allocation?: Record<string, number>;
}

export interface InvestmentProspectusResponse {
  properties: PropertyProspectus[];
  portfolio_summary?: PortfolioSummary | null;
  is_multi_property: boolean;
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
  | 'investment_prospectus'
  | 'market_summary'
  | 'property_detail'
  | 'property_search_results'
  | 'query_result';

// ---------------------------------------------------------------------------
// Block data interfaces (used by the discriminated union ResponseBlock)
// ---------------------------------------------------------------------------

export interface PropertyDetailBlockData {
  address?: string;
  neighborhood?: string;
  zip_code?: string;
  zoning_class?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  property_type?: string;
  use_description?: string;
  last_sale_price?: number;
  last_sale_date?: string;
  building_sqft?: number;
  latitude?: number;
  longitude?: number;
  property_category?: string;
  record_type?: string;
}

export interface PredictionBlockData {
  predicted_price: number;
  price_lower: number;
  price_upper: number;
  neighborhood?: string;
  base_value?: number;
  feature_contributions?: {
    name: string;
    value: number;
    raw_feature?: string;
  }[];
}

export interface CompBlockData {
  address: string;
  sale_date: string;
  sale_price: number;
  beds?: number;
  baths?: number;
  sqft?: number;
  price_per_sqft?: number;
}

export interface NeighborhoodBlockData {
  name?: string;
  median_price?: number;
  avg_price?: number;
  median_ppsf?: number;
  sale_count?: number;
  yoy_price_change_pct?: number;
  dominant_zoning?: string[];
  median_lot_size?: number;
  avg_year_built?: number;
  property_type_breakdown?: Record<string, number>;
}

export interface DevelopmentBlockData {
  zoning?: {
    zone_class?: string;
    zone_desc?: string;
    general_plan?: string;
  };
  zone_rule?: {
    max_lot_coverage_pct?: number;
    max_height_ft?: number;
    is_hillside?: boolean;
    residential?: boolean;
  };
  units?: {
    base_max_units?: number;
    middle_housing_eligible?: boolean;
    middle_housing_max_units?: number;
    effective_max_units?: number;
  };
  adu?: {
    eligible?: boolean;
    max_adu_sqft?: number;
    remaining_lot_coverage_sqft?: number;
    notes?: string;
  };
  sb9?: {
    eligible?: boolean;
    can_split?: boolean;
    max_total_units?: number;
    notes?: string;
  };
}

export interface SellVsHoldBlockData {
  current_predicted_value?: number;
  confidence_range?: [number, number];
  neighborhood?: string;
  yoy_appreciation_pct?: number;
  mortgage_rate_30yr?: number;
  hold_scenarios?: Record<
    string,
    {
      projected_value?: number;
      appreciation_pct?: number;
      gross_gain?: number;
      estimated_sell_costs?: number;
      net_gain?: number;
    }
  >;
  rental_estimate?: {
    monthly_rent?: number;
    annual_gross_rent?: number;
    annual_net_rent?: number;
    cap_rate_pct?: number;
    price_to_rent_ratio?: number;
    expense_ratio_pct?: number;
    estimation_method?: string;
  };
}

export interface MarketBlockData {
  current_market?: {
    period?: string;
    median_sale_price?: number;
    median_list_price?: number;
    sale_to_list_ratio?: number;
    sold_above_list_pct?: number;
    homes_sold_monthly?: number;
    median_days_on_market?: number;
    mortgage_rate_30yr?: number;
  };
  data_coverage?: {
    total_sales?: number;
    neighborhoods_covered?: number;
  };
  top_neighborhoods_by_price?: {
    name: string;
    median_price?: number;
    sales?: number;
    yoy_change?: number;
  }[];
}

export interface ImprovementBlockData {
  current_price?: number;
  improved_price?: number;
  total_delta?: number;
  total_cost?: number;
  roi?: number;
  categories?: {
    category: string;
    avg_cost?: number;
    ml_delta?: number;
    roi?: number;
    market_premium_pct?: number;
  }[];
}

export interface InvestmentScenarioBlockItem {
  scenario_name?: string;
  scenario_type?: string;
  total_investment?: number;
  monthly_cash_flow?: number;
  cap_rate_pct?: number;
  cash_on_cash_pct?: number;
  total_monthly_rent?: number;
  development_feasible?: boolean;
}

export interface InvestmentScenariosBlockData {
  property_address?: string;
  property_value?: number;
  neighborhood?: string;
  scenarios?: InvestmentScenarioBlockItem[];
  best_scenario?: string;
  recommendation_notes?: string;
}

export interface RentalIncomeBlockData {
  scenario_name?: string;
  property_value?: number;
  total_monthly_rent?: number;
  total_annual_rent?: number;
  expenses?: {
    property_tax?: number;
    insurance?: number;
    maintenance?: number;
    vacancy_reserve?: number;
    management_fee?: number;
    total_annual?: number;
    expense_ratio_pct?: number;
  };
  mortgage?: {
    monthly_piti?: number;
    rate_30yr?: number;
    down_payment_pct?: number;
    loan_amount?: number;
  };
  cap_rate_pct?: number;
  cash_on_cash_pct?: number;
  monthly_cash_flow?: number;
  gross_rent_multiplier?: number;
  price_to_rent_ratio?: number;
  units?: {
    unit_type?: string;
    beds?: number;
    monthly_rent?: number;
  }[];
}

// ---------------------------------------------------------------------------
// Discriminated union: ResponseBlock
// ---------------------------------------------------------------------------

interface ResponseBlockBase {
  tool_name: string;
}

export type ResponseBlock =
  | (ResponseBlockBase & { type: 'property_detail'; data: PropertyDetailBlockData })
  | (ResponseBlockBase & { type: 'prediction_card'; data: PredictionBlockData })
  | (ResponseBlockBase & { type: 'comps_table'; data: CompBlockData[] })
  | (ResponseBlockBase & { type: 'neighborhood_stats'; data: NeighborhoodBlockData })
  | (ResponseBlockBase & { type: 'development_potential'; data: DevelopmentBlockData })
  | (ResponseBlockBase & { type: 'sell_vs_hold'; data: SellVsHoldBlockData })
  | (ResponseBlockBase & { type: 'market_summary'; data: MarketBlockData })
  | (ResponseBlockBase & { type: 'improvement_sim'; data: ImprovementBlockData })
  | (ResponseBlockBase & { type: 'investment_scenarios'; data: InvestmentScenariosBlockData })
  | (ResponseBlockBase & { type: 'rental_income'; data: RentalIncomeBlockData })
  | (ResponseBlockBase & { type: 'property_search_results'; data: PropertySearchResultsData })
  | (ResponseBlockBase & { type: 'query_result'; data: QueryResultData })
  | (ResponseBlockBase & { type: 'investment_prospectus'; data: InvestmentProspectusResponse });

// ---------------------------------------------------------------------------
// Search result types (from search_properties tool)
// ---------------------------------------------------------------------------

export interface SearchResultDevelopment {
  adu_eligible?: boolean;
  adu_max_sqft?: number;
  sb9_eligible?: boolean;
  sb9_can_split?: boolean;
  sb9_max_units?: number;
  effective_max_units?: number;
  middle_housing_eligible?: boolean;
  zone_class?: string;
  zone_desc?: string;
}

export interface SearchResultProperty {
  id?: number;
  address: string;
  neighborhood?: string;
  zip_code?: string;
  zoning_class?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  building_sqft?: number;
  lot_size_sqft?: number;
  building_to_lot_ratio?: number;
  year_built?: number;
  property_type?: string;
  property_category?: string;
  record_type?: string;
  last_sale_price?: number;
  last_sale_date?: string;
  predicted_price?: number;
  prediction_confidence?: number;
  data_quality?: string;
  data_quality_note?: string;
  development?: SearchResultDevelopment;
  latitude?: number;
  longitude?: number;
}

export interface PropertySearchResultsData {
  results: SearchResultProperty[];
  total_found: number;
  total_matching: number;
  filters_applied?: Record<string, unknown>;
  message?: string;
}

// ---------------------------------------------------------------------------
// Query result types (from query_database tool)
// ---------------------------------------------------------------------------

export interface QueryResultData {
  query: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  explanation?: string;
  error?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  blocks?: ResponseBlock[];
  toolsUsed?: string[];
  /** Tool execution events for rendering compact status chips in chat. */
  toolEvents?: ToolEvent[];
}

/** A streamed tool execution event (start or result). */
export interface ToolEvent {
  name: string;
  label: string;
  /** The block produced by the tool, if any. */
  block?: ResponseBlock;
  /** True once the tool has finished executing. */
  done: boolean;
}

export interface WorkingSetMeta {
  count: number;
  descriptor: string;
  session_id: string;
  /** Sample of up to 25 properties from the working set for sidebar display. */
  sample?: WorkingSetProperty[];
  /** Properties the user has drilled into with per-property tools (LIFO, max 10). */
  discussed?: WorkingSetProperty[];
  /** Number of active filters — non-zero means undo is available. */
  filter_depth?: number;
}

export interface WorkingSetProperty {
  id: number;
  address: string;
  neighborhood: string | null;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  building_sqft: number | null;
  lot_size_sqft: number | null;
  zoning_class: string | null;
  property_type: string | null;
  last_sale_price: number | null;
  year_built: number | null;
  latitude: number | null;
  longitude: number | null;
  property_category: string | null;
  record_type: string | null;
  lot_group_key: string | null;
  situs_unit: string | null;
}

export interface WorkingSetPage {
  properties: WorkingSetProperty[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  descriptor: string;
}

export interface FaketorChatResponse {
  reply: string;
  tool_calls?: { name: string; input: Record<string, unknown> }[];
  blocks?: ResponseBlock[];
  error?: string;
  working_set?: WorkingSetMeta;
}

// ---------------------------------------------------------------------------
// Authentication
// ---------------------------------------------------------------------------

export interface User {
  id: number;
  email: string;
  full_name: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export type PageId = 'chat' | 'predict' | 'neighborhoods' | 'market' | 'model' | 'afford' | 'potential';
