/**
 * PDF document generation for the Investment Prospectus.
 *
 * Uses @react-pdf/renderer to create a professional letter-size PDF
 * with magazine-style layouts, SVG charts, and data-driven narratives.
 * Supports single-property, curated portfolio, similar group, and thesis modes.
 */
import {
  Document,
  Page,
  Text,
  View,
  pdf,
} from '@react-pdf/renderer';
import type {
  InvestmentProspectusResponse,
  PropertyProspectus,
  PortfolioSummary,
  ProspectusScenario,
  ProspectusComparable,
} from '../types';
import {
  C,
  s,
  fmtCurrency,
  fmtPct,
  fmtDate,
  fmtNumber,
  TwoColumn,
  NarrativeBlock,
  MetricCard,
  CalloutBox,
  PageFooter,
  KVRow,
  SectionHeader,
  MetricBox,
  DevBadge,
} from './prospectus-layouts';
import {
  ScenarioComparisonBar,
  ExpenseDonut,
  CashFlowProjectionBar,
  PropertyComparisonBar,
  PortfolioAllocationDonut,
} from './prospectus-charts';

// ============================================================================
// SINGLE-PROPERTY PAGES
// ============================================================================

// ---------------------------------------------------------------------------
// Cover Page
// ---------------------------------------------------------------------------

function CoverPage({ p, disclaimer }: { p: PropertyProspectus; disclaimer: string }) {
  return (
    <Page size="LETTER" style={s.page}>
      {/* Title block */}
      <View style={{ marginTop: 48, marginBottom: 16 }}>
        <Text
          style={{
            fontSize: 28,
            fontFamily: 'Helvetica-Bold',
            color: C.gray900,
            marginBottom: 6,
          }}
        >
          Investment Prospectus
        </Text>
        <View
          style={{
            width: 60,
            height: 3,
            backgroundColor: C.amber,
            marginBottom: 12,
          }}
        />
        <Text style={{ fontSize: 16, color: C.gray600 }}>
          {p.address || p.neighborhood}
        </Text>
        <Text style={{ fontSize: 10, color: C.gray400, marginTop: 4 }}>
          Berkeley, California  |  Generated {fmtDate(p.generated_at?.split('T')[0])}
        </Text>
      </View>

      {/* Executive Summary — two-column: strategy left, metrics right */}
      <SectionHeader>Executive Summary</SectionHeader>

      <TwoColumn
        ratio={0.55}
        gap={20}
        left={
          <View>
            <CalloutBox>
              <Text style={{ fontSize: 12, fontFamily: 'Helvetica-Bold', color: C.green }}>
                {p.recommended_approach_label || 'Analysis Complete'}
              </Text>
              {p.strategy_rationale && (
                <Text style={{ fontSize: 9, color: C.gray600, marginTop: 6, lineHeight: 1.5 }}>
                  {p.strategy_rationale}
                </Text>
              )}
            </CalloutBox>

            {/* Investment overview narrative */}
            <NarrativeBlock
              title="Investment Overview"
              content={p.valuation_commentary || null}
              marginTop={10}
            />
            <NarrativeBlock
              content={p.market_position_commentary || null}
              accentColor={C.green}
              marginTop={6}
            />
          </View>
        }
        right={
          <View>
            <View
              style={{
                backgroundColor: C.gray50,
                borderRadius: 4,
                borderWidth: 0.5,
                borderColor: C.gray200,
                padding: 10,
              }}
            >
              <Text
                style={{
                  fontSize: 8,
                  fontFamily: 'Helvetica-Bold',
                  color: C.gray500,
                  textTransform: 'uppercase',
                  letterSpacing: 0.5,
                  marginBottom: 6,
                }}
              >
                Key Metrics
              </Text>
              <KVRow label="Estimated Value" value={fmtCurrency(p.estimated_value)} />
              <KVRow label="Capital Required" value={fmtCurrency(p.capital_required)} />
              <View style={{ height: 4 }} />
              <KVRow label="Monthly Cash Flow" value={fmtCurrency(p.monthly_cash_flow)} />
              <KVRow label="Annual Return" value={fmtPct(p.projected_annual_return_pct)} />
              <View style={{ height: 4 }} />
              <KVRow label="Cap Rate" value={fmtPct(p.cap_rate_pct)} />
              <KVRow label="Cash-on-Cash" value={fmtPct(p.cash_on_cash_pct)} />
              <KVRow
                label="GRM"
                value={p.gross_rent_multiplier ? Number(p.gross_rent_multiplier).toFixed(1) : '\u2014'}
              />
              <KVRow label="Time Horizon" value={`${p.time_horizon_years} years`} />
            </View>
          </View>
        }
      />

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Property Details Page
// ---------------------------------------------------------------------------

function PropertyDetailsPage({ p, disclaimer }: { p: PropertyProspectus; disclaimer: string }) {
  return (
    <Page size="LETTER" style={s.page}>
      <Text style={{ fontSize: 14, fontFamily: 'Helvetica-Bold', color: C.gray900, marginBottom: 2 }}>
        {p.address || p.neighborhood}
      </Text>

      <SectionHeader>Property Characteristics</SectionHeader>
      <View style={{ flexDirection: 'row' }}>
        <View style={{ width: '50%', paddingRight: 12 }}>
          {p.beds != null && <KVRow label="Bedrooms" value={String(p.beds)} />}
          {p.baths != null && <KVRow label="Bathrooms" value={String(p.baths)} />}
          {p.sqft != null && <KVRow label="Living Area" value={`${fmtNumber(p.sqft)} sqft`} />}
          {p.lot_size_sqft != null && (
            <KVRow label="Lot Size" value={`${fmtNumber(p.lot_size_sqft)} sqft`} />
          )}
        </View>
        <View style={{ width: '50%', paddingLeft: 12 }}>
          {p.year_built != null && <KVRow label="Year Built" value={String(p.year_built)} />}
          {p.zoning_class && <KVRow label="Zoning" value={p.zoning_class} />}
          <KVRow label="Property Type" value={p.property_type} />
          <KVRow label="Neighborhood" value={p.neighborhood} />
        </View>
      </View>

      {/* Valuation Analysis — KV left, narrative right */}
      <SectionHeader>Valuation Analysis</SectionHeader>
      <TwoColumn
        ratio={0.4}
        gap={16}
        left={
          <View>
            <KVRow label="Estimated Value" value={fmtCurrency(p.estimated_value)} />
            <KVRow label="Low Estimate" value={fmtCurrency(p.value_range_low)} />
            <KVRow label="High Estimate" value={fmtCurrency(p.value_range_high)} />
            {p.value_per_sqft != null && (
              <KVRow label="Value per Sqft" value={`$${Number(p.value_per_sqft).toFixed(0)}`} />
            )}
          </View>
        }
        right={
          <NarrativeBlock
            content={p.valuation_commentary || null}
            marginTop={0}
          />
        }
      />

      {/* Market Context — KV left, narrative right */}
      <SectionHeader>Market Context</SectionHeader>
      <TwoColumn
        ratio={0.4}
        gap={16}
        left={
          <View>
            {p.neighborhood_median_price != null && (
              <KVRow label={`${p.neighborhood} Median`} value={fmtCurrency(p.neighborhood_median_price)} />
            )}
            {p.city_median_price != null && (
              <KVRow label="Berkeley Median" value={fmtCurrency(p.city_median_price)} />
            )}
            {p.neighborhood_yoy_change_pct != null && (
              <KVRow label="YoY Change" value={fmtPct(p.neighborhood_yoy_change_pct, true)} />
            )}
            {p.neighborhood_avg_ppsf != null && (
              <KVRow label="Avg $/sqft" value={`$${Number(p.neighborhood_avg_ppsf).toFixed(0)}`} />
            )}
            {p.mortgage_rate_30yr != null && (
              <KVRow label="Mortgage Rate (30yr)" value={`${Number(p.mortgage_rate_30yr).toFixed(2)}%`} />
            )}
            {p.median_dom != null && (
              <KVRow label="Median Days on Market" value={`${p.median_dom} days`} />
            )}
          </View>
        }
        right={
          <NarrativeBlock
            content={p.market_position_commentary || null}
            accentColor={C.green}
            marginTop={0}
          />
        }
      />

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Development & Scenarios Page
// ---------------------------------------------------------------------------

function DevelopmentAndScenariosPage({
  p,
  disclaimer,
}: {
  p: PropertyProspectus;
  disclaimer: string;
}) {
  const scenarios = p.scenarios ?? [];
  const bestScenario = p.best_scenario_detail || scenarios.find(
    (sc) => p.best_scenario_name && (sc.scenario_name || '').toLowerCase().includes(p.best_scenario_name.toLowerCase()),
  );

  return (
    <Page size="LETTER" style={s.page}>
      <Text style={{ fontSize: 14, fontFamily: 'Helvetica-Bold', color: C.gray900, marginBottom: 2 }}>
        {p.address || p.neighborhood}
      </Text>

      {/* Development */}
      <SectionHeader>Development Potential</SectionHeader>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 6 }}>
        <DevBadge label="ADU" eligible={p.adu_eligible} detail={p.adu_max_sqft ? `${p.adu_max_sqft} sqft max` : undefined} />
        <DevBadge label="SB9 Split" eligible={p.sb9_eligible} />
        <DevBadge
          label="Middle Housing"
          eligible={p.middle_housing_eligible}
          detail={p.middle_housing_max_units ? `up to ${p.middle_housing_max_units} units` : undefined}
        />
      </View>
      <KVRow label="Effective Max Units" value={String(p.effective_max_units)} />
      {p.development_notes && (
        <Text style={{ fontSize: 8.5, color: C.gray500, marginTop: 4, lineHeight: 1.4 }}>
          {p.development_notes}
        </Text>
      )}

      {/* Scenarios table */}
      {scenarios.length > 0 && (
        <>
          <SectionHeader>Investment Scenarios</SectionHeader>
          <View style={s.tableHeader}>
            <Text style={[s.tableHeaderText, { width: '22%' }]}>Scenario</Text>
            <Text style={[s.tableHeaderText, { width: '16%', textAlign: 'right' }]}>Investment</Text>
            <Text style={[s.tableHeaderText, { width: '14%', textAlign: 'right' }]}>Rent/mo</Text>
            <Text style={[s.tableHeaderText, { width: '16%', textAlign: 'right' }]}>Cash Flow</Text>
            <Text style={[s.tableHeaderText, { width: '16%', textAlign: 'right' }]}>Cap Rate</Text>
            <Text style={[s.tableHeaderText, { width: '16%', textAlign: 'right' }]}>CoC</Text>
          </View>
          {scenarios.map((sc: ProspectusScenario, i: number) => {
            const isBest =
              p.best_scenario_name &&
              (sc.scenario_name || '').toLowerCase().includes(p.best_scenario_name.toLowerCase());
            return (
              <View
                key={i}
                style={[s.tableRow, isBest ? s.tableRowHighlight : {}]}
              >
                <Text style={[s.tableCell, { width: '22%', fontFamily: isBest ? 'Helvetica-Bold' : 'Helvetica' }]}>
                  {isBest ? '\u2713 ' : ''}
                  {sc.scenario_name || sc.scenario_type || 'Scenario'}
                </Text>
                <Text style={[s.tableCell, { width: '16%', textAlign: 'right' }]}>
                  {fmtCurrency(sc.total_investment)}
                </Text>
                <Text style={[s.tableCell, { width: '14%', textAlign: 'right' }]}>
                  {fmtCurrency(sc.total_monthly_rent)}
                </Text>
                <Text
                  style={[
                    s.tableCell,
                    {
                      width: '16%',
                      textAlign: 'right',
                      color: (sc.monthly_cash_flow ?? 0) >= 0 ? C.green : C.red,
                      fontFamily: 'Helvetica-Bold',
                    },
                  ]}
                >
                  {fmtCurrency(sc.monthly_cash_flow)}
                </Text>
                <Text style={[s.tableCell, { width: '16%', textAlign: 'right' }]}>
                  {fmtPct(sc.cap_rate_pct)}
                </Text>
                <Text style={[s.tableCell, { width: '16%', textAlign: 'right' }]}>
                  {fmtPct(sc.cash_on_cash_pct)}
                </Text>
              </View>
            );
          })}

          {/* Charts row: scenario comparison + expense breakdown */}
          <TwoColumn
            ratio={0.55}
            gap={12}
            marginTop={12}
            left={
              scenarios.length >= 2 ? (
                <View>
                  <ScenarioComparisonBar scenarios={scenarios} width={240} height={110} />
                </View>
              ) : <View />
            }
            right={
              bestScenario?.expenses ? (
                <View>
                  <ExpenseDonut expenses={bestScenario.expenses} width={200} height={110} />
                </View>
              ) : <View />
            }
          />

          {/* Cash flow projections */}
          {bestScenario?.projections && bestScenario.projections.length > 0 && (
            <View style={{ marginTop: 8 }}>
              <CashFlowProjectionBar
                projections={bestScenario.projections}
                width={480}
                height={100}
              />
            </View>
          )}
        </>
      )}

      {/* Scenario recommendation narrative */}
      <NarrativeBlock
        title="Recommendation"
        content={p.scenario_recommendation_narrative || p.recommendation_notes || null}
        accentColor={C.green}
        marginTop={10}
      />

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Comps & Risks Page
// ---------------------------------------------------------------------------

function CompsAndRisksPage({
  p,
  disclaimer,
}: {
  p: PropertyProspectus;
  disclaimer: string;
}) {
  const comps = p.comparable_sales ?? [];
  const risks = p.risk_factors ?? [];

  return (
    <Page size="LETTER" style={s.page}>
      <Text style={{ fontSize: 14, fontFamily: 'Helvetica-Bold', color: C.gray900, marginBottom: 2 }}>
        {p.address || p.neighborhood}
      </Text>

      {/* Comparable Sales */}
      {comps.length > 0 && (
        <>
          <SectionHeader>Comparable Sales</SectionHeader>
          <View style={s.tableHeader}>
            <Text style={[s.tableHeaderText, { width: '36%' }]}>Address</Text>
            <Text style={[s.tableHeaderText, { width: '20%', textAlign: 'right' }]}>Price</Text>
            <Text style={[s.tableHeaderText, { width: '14%', textAlign: 'right' }]}>Beds</Text>
            <Text style={[s.tableHeaderText, { width: '14%', textAlign: 'right' }]}>$/sqft</Text>
            <Text style={[s.tableHeaderText, { width: '16%', textAlign: 'right' }]}>Date</Text>
          </View>
          {comps.map((c: ProspectusComparable, i: number) => (
            <View key={i} style={s.tableRow}>
              <Text style={[s.tableCell, { width: '36%' }]}>{c.address}</Text>
              <Text style={[s.tableCell, { width: '20%', textAlign: 'right' }]}>
                {fmtCurrency(c.sale_price)}
              </Text>
              <Text style={[s.tableCell, { width: '14%', textAlign: 'right' }]}>
                {c.beds != null ? String(c.beds) : '\u2014'}
              </Text>
              <Text style={[s.tableCell, { width: '14%', textAlign: 'right' }]}>
                {c.price_per_sqft ? `$${Number(c.price_per_sqft).toFixed(0)}` : '\u2014'}
              </Text>
              <Text style={[s.tableCell, { width: '16%', textAlign: 'right' }]}>
                {fmtDate(c.sale_date)}
              </Text>
            </View>
          ))}

          {/* Comps analysis narrative */}
          <NarrativeBlock
            content={p.comps_analysis_narrative || null}
            marginTop={6}
          />
        </>
      )}

      {/* Risk Assessment — two-column: risks left, mitigation right */}
      {risks.length > 0 && (
        <>
          <SectionHeader>Risk Assessment</SectionHeader>
          <TwoColumn
            ratio={0.5}
            gap={16}
            left={
              <View>
                {risks.map((risk: string, i: number) => (
                  <View key={i} style={{ flexDirection: 'row', marginBottom: 4 }}>
                    <Text style={{ color: C.amber, fontSize: 9, marginRight: 6 }}>{'\u26A0'}</Text>
                    <Text style={{ fontSize: 8.5, color: C.gray600, flex: 1, lineHeight: 1.4 }}>
                      {risk}
                    </Text>
                  </View>
                ))}
              </View>
            }
            right={
              <NarrativeBlock
                title="Mitigation Strategies"
                content={p.risk_mitigation_narrative || null}
                accentColor={C.green}
                marginTop={0}
              />
            }
          />
        </>
      )}

      {/* Disclaimers + Data Sources (combined, compact) */}
      <SectionHeader>Disclaimers & Data Sources</SectionHeader>
      {(p.disclaimers ?? []).map((d: string, i: number) => (
        <Text key={i} style={{ fontSize: 7.5, color: C.gray400, marginBottom: 2, lineHeight: 1.4 }}>
          {d}
        </Text>
      ))}
      {(p.data_sources ?? []).length > 0 && (
        <Text style={{ fontSize: 7.5, color: C.gray500, marginTop: 4, lineHeight: 1.4 }}>
          Data sources: {(p.data_sources ?? []).join(' \u2022 ')}
        </Text>
      )}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ============================================================================
// CONDENSED 2-PAGE LAYOUT (for multi-property modes)
// ============================================================================

function CondensedPropertyPage1({
  p,
  disclaimer,
}: {
  p: PropertyProspectus;
  disclaimer: string;
}) {
  const scenarios = p.scenarios ?? [];
  const bestScenario = p.best_scenario_detail || scenarios.find(
    (sc) => p.best_scenario_name && (sc.scenario_name || '').toLowerCase().includes(p.best_scenario_name.toLowerCase()),
  );

  return (
    <Page size="LETTER" style={s.page}>
      {/* Title + strategy badge */}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 14, fontFamily: 'Helvetica-Bold', color: C.gray900 }}>
            {p.address || p.neighborhood}
          </Text>
        </View>
        {p.recommended_approach_label && (
          <View
            style={{
              backgroundColor: C.greenBg,
              borderRadius: 3,
              paddingHorizontal: 8,
              paddingVertical: 3,
              borderWidth: 0.5,
              borderColor: '#A7F3D0',
            }}
          >
            <Text style={{ fontSize: 7.5, fontFamily: 'Helvetica-Bold', color: C.green }}>
              {p.recommended_approach_label}
            </Text>
          </View>
        )}
      </View>

      {/* Property details + key metrics side by side */}
      <TwoColumn
        ratio={0.55}
        gap={16}
        marginTop={8}
        left={
          <View>
            <Text style={{ fontSize: 8, fontFamily: 'Helvetica-Bold', color: C.gray500, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>
              Property Details
            </Text>
            <View style={{ flexDirection: 'row' }}>
              <View style={{ width: '50%' }}>
                {p.beds != null && <KVRow label="Beds" value={String(p.beds)} />}
                {p.baths != null && <KVRow label="Baths" value={String(p.baths)} />}
                {p.sqft != null && <KVRow label="Sqft" value={fmtNumber(p.sqft)} />}
              </View>
              <View style={{ width: '50%' }}>
                {p.year_built != null && <KVRow label="Built" value={String(p.year_built)} />}
                <KVRow label="Zoning" value={p.zoning_class || '\u2014'} />
                <KVRow label="Type" value={p.property_type} />
              </View>
            </View>
          </View>
        }
        right={
          <View style={{ backgroundColor: C.gray50, borderRadius: 4, padding: 8, borderWidth: 0.5, borderColor: C.gray200 }}>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
              <MetricCard label="Value" value={fmtCurrency(p.estimated_value)} width="50%" />
              <MetricCard label="Capital" value={fmtCurrency(p.capital_required)} width="50%" />
              <MetricCard
                label="Cash Flow/mo"
                value={fmtCurrency(p.monthly_cash_flow)}
                color={p.monthly_cash_flow >= 0 ? C.green : C.red}
                width="50%"
              />
              <MetricCard label="Cap Rate" value={fmtPct(p.cap_rate_pct)} width="50%" />
              <MetricCard label="CoC Return" value={fmtPct(p.cash_on_cash_pct)} width="50%" />
              <MetricCard label="Annual Return" value={fmtPct(p.projected_annual_return_pct)} width="50%" />
            </View>
          </View>
        }
      />

      {/* Strategy rationale */}
      {p.strategy_rationale && (
        <NarrativeBlock
          title="Strategy"
          content={p.strategy_rationale}
          accentColor={C.green}
          marginTop={8}
        />
      )}

      {/* Scenarios table */}
      {scenarios.length > 0 && (
        <>
          <SectionHeader>Investment Scenarios</SectionHeader>
          <View style={s.tableHeader}>
            <Text style={[s.tableHeaderText, { width: '24%' }]}>Scenario</Text>
            <Text style={[s.tableHeaderText, { width: '19%', textAlign: 'right' }]}>Investment</Text>
            <Text style={[s.tableHeaderText, { width: '19%', textAlign: 'right' }]}>Cash Flow</Text>
            <Text style={[s.tableHeaderText, { width: '19%', textAlign: 'right' }]}>Cap Rate</Text>
            <Text style={[s.tableHeaderText, { width: '19%', textAlign: 'right' }]}>CoC</Text>
          </View>
          {scenarios.map((sc: ProspectusScenario, i: number) => {
            const isBest =
              p.best_scenario_name &&
              (sc.scenario_name || '').toLowerCase().includes(p.best_scenario_name.toLowerCase());
            return (
              <View key={i} style={[s.tableRow, isBest ? s.tableRowHighlight : {}]}>
                <Text style={[s.tableCell, { width: '24%', fontFamily: isBest ? 'Helvetica-Bold' : 'Helvetica' }]}>
                  {isBest ? '\u2713 ' : ''}{sc.scenario_name || sc.scenario_type || 'Scenario'}
                </Text>
                <Text style={[s.tableCell, { width: '19%', textAlign: 'right' }]}>{fmtCurrency(sc.total_investment)}</Text>
                <Text style={[s.tableCell, { width: '19%', textAlign: 'right', color: (sc.monthly_cash_flow ?? 0) >= 0 ? C.green : C.red, fontFamily: 'Helvetica-Bold' }]}>
                  {fmtCurrency(sc.monthly_cash_flow)}
                </Text>
                <Text style={[s.tableCell, { width: '19%', textAlign: 'right' }]}>{fmtPct(sc.cap_rate_pct)}</Text>
                <Text style={[s.tableCell, { width: '19%', textAlign: 'right' }]}>{fmtPct(sc.cash_on_cash_pct)}</Text>
              </View>
            );
          })}

          {/* Charts: scenario bar + expense donut */}
          <TwoColumn
            ratio={0.55}
            gap={8}
            marginTop={8}
            left={
              scenarios.length >= 2 ? (
                <ScenarioComparisonBar scenarios={scenarios} width={230} height={100} />
              ) : <View />
            }
            right={
              bestScenario?.expenses ? (
                <ExpenseDonut expenses={bestScenario.expenses} width={190} height={100} />
              ) : <View />
            }
          />
        </>
      )}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

function CondensedPropertyPage2({
  p,
  disclaimer,
}: {
  p: PropertyProspectus;
  disclaimer: string;
}) {
  const comps = (p.comparable_sales ?? []).slice(0, 3);
  const risks = (p.risk_factors ?? []).slice(0, 3);

  return (
    <Page size="LETTER" style={s.page}>
      <Text style={{ fontSize: 14, fontFamily: 'Helvetica-Bold', color: C.gray900, marginBottom: 2 }}>
        {p.address || p.neighborhood}
      </Text>

      {/* Market & Valuation (compact two-column) */}
      <SectionHeader>Market & Valuation</SectionHeader>
      <TwoColumn
        ratio={0.4}
        gap={16}
        left={
          <View>
            <KVRow label="Estimated Value" value={fmtCurrency(p.estimated_value)} />
            <KVRow label="Value Range" value={`${fmtCurrency(p.value_range_low)} – ${fmtCurrency(p.value_range_high)}`} />
            {p.value_per_sqft != null && <KVRow label="$/sqft" value={`$${Number(p.value_per_sqft).toFixed(0)}`} />}
            {p.neighborhood_median_price != null && (
              <KVRow label={`${p.neighborhood} Median`} value={fmtCurrency(p.neighborhood_median_price)} />
            )}
            {p.neighborhood_yoy_change_pct != null && (
              <KVRow label="YoY Change" value={fmtPct(p.neighborhood_yoy_change_pct, true)} />
            )}
          </View>
        }
        right={
          <NarrativeBlock
            content={p.valuation_commentary || p.market_position_commentary || null}
            marginTop={0}
          />
        }
      />

      {/* Development (compact) */}
      <SectionHeader>Development</SectionHeader>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 2 }}>
        <DevBadge label="ADU" eligible={p.adu_eligible} detail={p.adu_max_sqft ? `${p.adu_max_sqft} sqft` : undefined} />
        <DevBadge label="SB9" eligible={p.sb9_eligible} />
        <DevBadge label="Middle Housing" eligible={p.middle_housing_eligible} detail={p.middle_housing_max_units ? `${p.middle_housing_max_units} units` : undefined} />
      </View>
      {p.development_notes && (
        <Text style={{ fontSize: 8, color: C.gray500, lineHeight: 1.4, maxLines: 2 }}>
          {p.development_notes}
        </Text>
      )}

      {/* Comparable Sales (compact, max 3) */}
      {comps.length > 0 && (
        <>
          <SectionHeader>Comparable Sales</SectionHeader>
          <View style={s.tableHeader}>
            <Text style={[s.tableHeaderText, { width: '40%' }]}>Address</Text>
            <Text style={[s.tableHeaderText, { width: '22%', textAlign: 'right' }]}>Price</Text>
            <Text style={[s.tableHeaderText, { width: '18%', textAlign: 'right' }]}>$/sqft</Text>
            <Text style={[s.tableHeaderText, { width: '20%', textAlign: 'right' }]}>Date</Text>
          </View>
          {comps.map((c: ProspectusComparable, i: number) => (
            <View key={i} style={s.tableRow}>
              <Text style={[s.tableCell, { width: '40%' }]}>{c.address}</Text>
              <Text style={[s.tableCell, { width: '22%', textAlign: 'right' }]}>{fmtCurrency(c.sale_price)}</Text>
              <Text style={[s.tableCell, { width: '18%', textAlign: 'right' }]}>{c.price_per_sqft ? `$${Number(c.price_per_sqft).toFixed(0)}` : '\u2014'}</Text>
              <Text style={[s.tableCell, { width: '20%', textAlign: 'right' }]}>{fmtDate(c.sale_date)}</Text>
            </View>
          ))}
          <NarrativeBlock content={p.comps_analysis_narrative || null} marginTop={4} />
        </>
      )}

      {/* Risks (compact, max 3) */}
      {risks.length > 0 && (
        <>
          <SectionHeader>Key Risks</SectionHeader>
          {risks.map((risk: string, i: number) => (
            <View key={i} style={{ flexDirection: 'row', marginBottom: 3 }}>
              <Text style={{ color: C.amber, fontSize: 8, marginRight: 4 }}>{'\u26A0'}</Text>
              <Text style={{ fontSize: 8, color: C.gray600, flex: 1, lineHeight: 1.3 }}>{risk}</Text>
            </View>
          ))}
        </>
      )}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ============================================================================
// PORTFOLIO OVERVIEW PAGES
// ============================================================================

// ---------------------------------------------------------------------------
// Curated Portfolio Overview
// ---------------------------------------------------------------------------

function CuratedPortfolioOverviewPage({
  summary,
  properties,
  disclaimer,
}: {
  summary: PortfolioSummary;
  properties: PropertyProspectus[];
  disclaimer: string;
}) {
  return (
    <Page size="LETTER" style={s.page}>
      <View style={{ marginTop: 36, marginBottom: 16 }}>
        <Text style={{ fontSize: 28, fontFamily: 'Helvetica-Bold', color: C.gray900, marginBottom: 6 }}>
          Portfolio Investment Prospectus
        </Text>
        <View style={{ width: 60, height: 3, backgroundColor: C.amber, marginBottom: 12 }} />
        <Text style={{ fontSize: 12, color: C.gray600 }}>
          {summary.property_count} Properties  |  Berkeley, California
        </Text>
        <Text style={{ fontSize: 10, color: C.gray400, marginTop: 4 }}>
          Generated {fmtDate(properties[0]?.generated_at?.split('T')[0])}
        </Text>
      </View>

      {/* Investment thesis */}
      {summary.investment_thesis && (
        <NarrativeBlock
          title="Investment Thesis"
          content={summary.investment_thesis}
          accentColor={C.amber}
          bgColor={C.amberBg}
          fontSize={9}
          marginTop={4}
        />
      )}

      {/* Portfolio metrics */}
      <SectionHeader>Portfolio Metrics</SectionHeader>
      <View style={s.metricsGrid}>
        <MetricBox label="Total Capital" value={fmtCurrency(summary.total_capital_required)} />
        <MetricBox
          label="Monthly Cash Flow"
          value={fmtCurrency(summary.total_monthly_cash_flow)}
          color={summary.total_monthly_cash_flow >= 0 ? C.green : C.red}
        />
        <MetricBox label="Wtd Avg Cap Rate" value={fmtPct(summary.weighted_avg_cap_rate)} />
        <MetricBox label="Wtd Avg CoC" value={fmtPct(summary.weighted_avg_coc)} />
      </View>

      {/* Donut charts: neighborhood + strategy allocation */}
      <TwoColumn
        ratio={0.5}
        gap={12}
        marginTop={12}
        left={
          summary.neighborhood_allocation && Object.keys(summary.neighborhood_allocation).length > 0 ? (
            <PortfolioAllocationDonut
              allocation={summary.neighborhood_allocation}
              title="Neighborhood Allocation"
              width={210}
              height={110}
            />
          ) : <View />
        }
        right={
          summary.strategy_allocation && Object.keys(summary.strategy_allocation).length > 0 ? (
            <PortfolioAllocationDonut
              allocation={summary.strategy_allocation}
              title="Strategy Allocation"
              width={210}
              height={110}
            />
          ) : <View />
        }
      />

      {/* Property listing table */}
      <SectionHeader>Properties</SectionHeader>
      <View style={s.tableHeader}>
        <Text style={[s.tableHeaderText, { width: '34%' }]}>Address</Text>
        <Text style={[s.tableHeaderText, { width: '16%', textAlign: 'right' }]}>Est. Value</Text>
        <Text style={[s.tableHeaderText, { width: '16%', textAlign: 'right' }]}>Cash Flow</Text>
        <Text style={[s.tableHeaderText, { width: '12%', textAlign: 'right' }]}>Cap Rate</Text>
        <Text style={[s.tableHeaderText, { width: '10%', textAlign: 'right' }]}>CoC</Text>
        <Text style={[s.tableHeaderText, { width: '12%', textAlign: 'right' }]}>Strategy</Text>
      </View>
      {properties.map((p, i) => (
        <View key={i} style={s.tableRow}>
          <Text style={[s.tableCell, { width: '34%' }]}>{p.address || p.neighborhood}</Text>
          <Text style={[s.tableCell, { width: '16%', textAlign: 'right' }]}>{fmtCurrency(p.estimated_value)}</Text>
          <Text style={[s.tableCell, { width: '16%', textAlign: 'right', color: p.monthly_cash_flow >= 0 ? C.green : C.red }]}>
            {fmtCurrency(p.monthly_cash_flow)}
          </Text>
          <Text style={[s.tableCell, { width: '12%', textAlign: 'right' }]}>{fmtPct(p.cap_rate_pct)}</Text>
          <Text style={[s.tableCell, { width: '10%', textAlign: 'right' }]}>{fmtPct(p.cash_on_cash_pct)}</Text>
          <Text style={[s.tableCell, { width: '12%', textAlign: 'right', fontSize: 7 }]}>{p.recommended_approach_label || '\u2014'}</Text>
        </View>
      ))}

      {summary.diversification_notes && (
        <Text style={{ fontSize: 8.5, color: C.gray600, marginTop: 8, lineHeight: 1.4 }}>
          {summary.diversification_notes}
        </Text>
      )}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Portfolio Comparison Page
// ---------------------------------------------------------------------------

function PortfolioComparisonPage({
  summary,
  disclaimer,
}: {
  summary: PortfolioSummary;
  properties?: PropertyProspectus[];
  disclaimer: string;
}) {
  const metrics = (summary.comparison_metrics ?? []).slice(0, 10);
  if (metrics.length < 2) return null;

  return (
    <Page size="LETTER" style={s.page}>
      <Text style={{ fontSize: 14, fontFamily: 'Helvetica-Bold', color: C.gray900, marginBottom: 2 }}>
        Portfolio Comparison
      </Text>

      {/* Value comparison chart */}
      <SectionHeader>Estimated Value Comparison</SectionHeader>
      <View style={{ alignItems: 'center', marginTop: 4 }}>
        <PropertyComparisonBar
          metrics={metrics}
          field="estimated_value"
          title="Estimated Property Values"
          width={460}
          height={120}
        />
      </View>

      {/* Cash-on-Cash comparison chart */}
      <SectionHeader>Return Comparison</SectionHeader>
      <View style={{ alignItems: 'center', marginTop: 4 }}>
        <PropertyComparisonBar
          metrics={metrics}
          field="cash_on_cash_pct"
          title="Cash-on-Cash Return (%)"
          width={460}
          height={120}
        />
      </View>

      {/* Detailed comparison table */}
      <SectionHeader>Side-by-Side Metrics</SectionHeader>
      <View style={s.tableHeader}>
        <Text style={[s.tableHeaderText, { width: '26%' }]}>Property</Text>
        <Text style={[s.tableHeaderText, { width: '15%', textAlign: 'right' }]}>Value</Text>
        <Text style={[s.tableHeaderText, { width: '15%', textAlign: 'right' }]}>Cap Rate</Text>
        <Text style={[s.tableHeaderText, { width: '15%', textAlign: 'right' }]}>CoC</Text>
        <Text style={[s.tableHeaderText, { width: '15%', textAlign: 'right' }]}>CF/mo</Text>
        <Text style={[s.tableHeaderText, { width: '14%', textAlign: 'right' }]}>Strategy</Text>
      </View>
      {metrics.map((m, i) => {
        const shortAddr = m.address.split(',')[0].replace(/\s+(Berkeley|CA).*/i, '');
        return (
          <View key={i} style={s.tableRow}>
            <Text style={[s.tableCell, { width: '26%' }]}>{shortAddr}</Text>
            <Text style={[s.tableCell, { width: '15%', textAlign: 'right' }]}>{fmtCurrency(m.estimated_value)}</Text>
            <Text style={[s.tableCell, { width: '15%', textAlign: 'right' }]}>{fmtPct(m.cap_rate_pct)}</Text>
            <Text style={[s.tableCell, { width: '15%', textAlign: 'right' }]}>{fmtPct(m.cash_on_cash_pct)}</Text>
            <Text style={[s.tableCell, { width: '15%', textAlign: 'right', color: m.monthly_cash_flow >= 0 ? C.green : C.red }]}>
              {fmtCurrency(m.monthly_cash_flow)}
            </Text>
            <Text style={[s.tableCell, { width: '14%', textAlign: 'right', fontSize: 7 }]}>
              {(m as any).strategy || '\u2014'}
            </Text>
          </View>
        );
      })}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ============================================================================
// SIMILAR GROUP PAGES
// ============================================================================

function SimilarGroupOverviewPage({
  summary,
  properties,
  disclaimer,
}: {
  summary: PortfolioSummary;
  properties: PropertyProspectus[];
  disclaimer: string;
}) {
  return (
    <Page size="LETTER" style={s.page}>
      <View style={{ marginTop: 36, marginBottom: 16 }}>
        <Text style={{ fontSize: 28, fontFamily: 'Helvetica-Bold', color: C.gray900, marginBottom: 6 }}>
          Investment Comparison
        </Text>
        <View style={{ width: 60, height: 3, backgroundColor: C.amber, marginBottom: 12 }} />
        <Text style={{ fontSize: 12, color: C.gray600 }}>
          {summary.property_count} Similar Properties  |  Berkeley, California
        </Text>
        <Text style={{ fontSize: 10, color: C.gray400, marginTop: 4 }}>
          Generated {fmtDate(properties[0]?.generated_at?.split('T')[0])}
        </Text>
      </View>

      {/* Shared traits */}
      {(summary.shared_traits ?? []).length > 0 && (
        <>
          <SectionHeader>Shared Characteristics</SectionHeader>
          <CalloutBox bgColor={C.amberBg} borderColor="#FDE68A">
            {summary.shared_traits!.map((trait, i) => (
              <View key={i} style={{ flexDirection: 'row', marginBottom: 3 }}>
                <Text style={{ fontSize: 9, color: C.amber, marginRight: 6 }}>{'\u2022'}</Text>
                <Text style={{ fontSize: 9, color: C.gray700, flex: 1, lineHeight: 1.4 }}>{trait}</Text>
              </View>
            ))}
          </CalloutBox>
        </>
      )}

      {/* Group metrics */}
      <SectionHeader>Group Average Metrics</SectionHeader>
      <View style={s.metricsGrid}>
        <MetricBox label="Total Capital" value={fmtCurrency(summary.total_capital_required)} />
        <MetricBox
          label="Avg Monthly CF"
          value={fmtCurrency(summary.total_monthly_cash_flow / Math.max(summary.property_count, 1))}
          color={summary.total_monthly_cash_flow >= 0 ? C.green : C.red}
        />
        <MetricBox label="Avg Cap Rate" value={fmtPct(summary.weighted_avg_cap_rate)} />
        <MetricBox label="Avg CoC" value={fmtPct(summary.weighted_avg_coc)} />
      </View>

      {/* Comparison chart */}
      {(summary.comparison_metrics ?? []).length >= 2 && (
        <View style={{ alignItems: 'center', marginTop: 12 }}>
          <PropertyComparisonBar
            metrics={summary.comparison_metrics!}
            field="cash_on_cash_pct"
            title="Cash-on-Cash Return Comparison (%)"
            width={460}
            height={120}
          />
        </View>
      )}

      {/* Individual differences */}
      {(summary.individual_differences ?? []).length > 0 && (
        <>
          <SectionHeader>Key Differences</SectionHeader>
          {summary.individual_differences!.map((diff, i) => (
            <View key={i} style={{ flexDirection: 'row', marginBottom: 3 }}>
              <Text style={{ fontSize: 9, color: C.gray500, marginRight: 6 }}>{'\u2022'}</Text>
              <Text style={{ fontSize: 9, color: C.gray600, flex: 1, lineHeight: 1.4 }}>{diff}</Text>
            </View>
          ))}
        </>
      )}

      {/* Investment thesis */}
      {summary.investment_thesis && (
        <NarrativeBlock
          title="Investment Analysis"
          content={summary.investment_thesis}
          accentColor={C.green}
          marginTop={10}
        />
      )}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ============================================================================
// THESIS MODE PAGES
// ============================================================================

function ThesisCoverPage({
  summary,
  properties,
  disclaimer,
}: {
  summary: PortfolioSummary;
  properties: PropertyProspectus[];
  disclaimer: string;
}) {
  const stats = summary.group_statistics;
  const exampleCount = (summary.example_property_indices ?? []).length;

  return (
    <Page size="LETTER" style={s.page}>
      <View style={{ marginTop: 36, marginBottom: 16 }}>
        <Text style={{ fontSize: 28, fontFamily: 'Helvetica-Bold', color: C.gray900, marginBottom: 6 }}>
          Berkeley Investment Thesis
        </Text>
        <View style={{ width: 60, height: 3, backgroundColor: C.amber, marginBottom: 12 }} />
        <Text style={{ fontSize: 12, color: C.gray600 }}>
          {summary.property_count} Properties Analyzed
        </Text>
        <Text style={{ fontSize: 10, color: C.gray400, marginTop: 4 }}>
          Generated {fmtDate(properties[0]?.generated_at?.split('T')[0])}
          {exampleCount > 0 && `  |  ${exampleCount} example properties detailed`}
        </Text>
      </View>

      {/* Thesis narrative */}
      {summary.investment_thesis && (
        <NarrativeBlock
          title="Investment Thesis"
          content={summary.investment_thesis}
          accentColor={C.amber}
          bgColor={C.amberBg}
          fontSize={9.5}
          marginTop={4}
        />
      )}

      {/* Portfolio metrics */}
      <SectionHeader>Portfolio Statistics</SectionHeader>
      <View style={s.metricsGrid}>
        <MetricBox label="Properties" value={String(summary.property_count)} />
        <MetricBox label="Total Capital" value={fmtCurrency(summary.total_capital_required)} />
        <MetricBox
          label="Monthly Cash Flow"
          value={fmtCurrency(summary.total_monthly_cash_flow)}
          color={summary.total_monthly_cash_flow >= 0 ? C.green : C.red}
        />
        <MetricBox label="Wtd Avg CoC" value={fmtPct(summary.weighted_avg_coc)} />
      </View>

      {stats && (
        <View style={{ marginTop: 8 }}>
          <View style={s.metricsGrid}>
            <MetricBox label="Avg Price" value={fmtCurrency(stats.avg_price)} />
            <MetricBox label="Median Price" value={fmtCurrency(stats.median_price)} />
            <MetricBox label="Min Price" value={fmtCurrency(stats.min_price)} />
            <MetricBox label="Max Price" value={fmtCurrency(stats.max_price)} />
          </View>
          <View style={s.metricsGrid}>
            <MetricBox label="Avg Cap Rate" value={fmtPct(stats.avg_cap_rate)} />
            <MetricBox label="Avg CoC" value={fmtPct(stats.avg_coc)} />
          </View>
        </View>
      )}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

function ThesisStatisticsPage({
  summary,
  disclaimer,
}: {
  summary: PortfolioSummary;
  disclaimer: string;
}) {
  const stats = summary.group_statistics;

  return (
    <Page size="LETTER" style={s.page}>
      <Text style={{ fontSize: 14, fontFamily: 'Helvetica-Bold', color: C.gray900, marginBottom: 2 }}>
        Statistical Summary
      </Text>

      {/* Price distribution */}
      {stats?.price_distribution && Object.keys(stats.price_distribution).length > 0 && (
        <>
          <SectionHeader>Price Distribution</SectionHeader>
          <View style={{ alignItems: 'center', marginTop: 4 }}>
            <PropertyComparisonBar
              metrics={Object.entries(stats.price_distribution).map(([range, count]) => ({
                address: range,
                estimated_value: Number(count),
                cap_rate_pct: 0,
                cash_on_cash_pct: 0,
                monthly_cash_flow: 0,
              }))}
              field="estimated_value"
              title="Properties by Price Range"
              width={460}
              height={120}
            />
          </View>
        </>
      )}

      {/* Allocation donuts */}
      <TwoColumn
        ratio={0.5}
        gap={12}
        marginTop={12}
        left={
          summary.neighborhood_allocation && Object.keys(summary.neighborhood_allocation).length > 0 ? (
            <PortfolioAllocationDonut
              allocation={summary.neighborhood_allocation}
              title="By Neighborhood"
              width={210}
              height={120}
            />
          ) : <View />
        }
        right={
          summary.strategy_allocation && Object.keys(summary.strategy_allocation).length > 0 ? (
            <PortfolioAllocationDonut
              allocation={summary.strategy_allocation}
              title="By Strategy"
              width={210}
              height={120}
            />
          ) : <View />
        }
      />

      {/* Common traits */}
      {stats?.common_neighborhoods && stats.common_neighborhoods.length > 0 && (
        <>
          <SectionHeader>Market Characteristics</SectionHeader>
          <KVRow label="Common Neighborhoods" value={stats.common_neighborhoods.join(', ')} />
          {stats.common_zoning && stats.common_zoning.length > 0 && (
            <KVRow label="Common Zoning" value={stats.common_zoning.join(', ')} />
          )}
        </>
      )}

      {/* Example properties preview */}
      {(summary.example_property_indices ?? []).length > 0 && (
        <>
          <SectionHeader>Example Properties (Detailed Analysis Follows)</SectionHeader>
          <Text style={{ fontSize: 8.5, color: C.gray500, marginBottom: 6, lineHeight: 1.4 }}>
            The following pages contain detailed 2-page analyses for {summary.example_property_indices!.length} representative properties,
            selected to illustrate the range of investment opportunities in this portfolio.
          </Text>
        </>
      )}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ============================================================================
// DOCUMENT ASSEMBLY
// ============================================================================

function ProspectusDocument({ data }: { data: InvestmentProspectusResponse }) {
  const properties = data.properties ?? [];
  const disclaimer = properties[0]?.disclaimers?.[0] || 'For informational purposes only.';
  const summary = data.portfolio_summary;
  const mode = summary?.mode || 'single';

  // Single property: full 4-page layout
  if (!data.is_multi_property || properties.length === 1) {
    const p = properties[0];
    return (
      <Document
        title={`Investment Prospectus - ${p?.address || 'Property'}`}
        author="HomeBuyer AI"
        subject="Investment Analysis"
      >
        <CoverPage p={p} disclaimer={disclaimer} />
        <PropertyDetailsPage p={p} disclaimer={disclaimer} />
        <DevelopmentAndScenariosPage p={p} disclaimer={disclaimer} />
        <CompsAndRisksPage p={p} disclaimer={disclaimer} />
      </Document>
    );
  }

  // Thesis mode: cover + stats + example properties (condensed 2-page each)
  if (mode === 'thesis' && summary) {
    const exampleIndices = new Set(summary.example_property_indices ?? []);
    const exampleProperties = properties.filter((_, i) => exampleIndices.has(i));
    // If no examples selected, show first 3
    const displayProperties = exampleProperties.length > 0 ? exampleProperties : properties.slice(0, 3);

    return (
      <Document
        title={`Berkeley Investment Thesis - ${properties.length} Properties`}
        author="HomeBuyer AI"
        subject="Investment Thesis"
      >
        <ThesisCoverPage summary={summary} properties={properties} disclaimer={disclaimer} />
        <ThesisStatisticsPage summary={summary} disclaimer={disclaimer} />
        {displayProperties.flatMap((p, i) => [
          <CondensedPropertyPage1 key={`c1-${i}`} p={p} disclaimer={disclaimer} />,
          <CondensedPropertyPage2 key={`c2-${i}`} p={p} disclaimer={disclaimer} />,
        ])}
      </Document>
    );
  }

  // Similar mode: group overview + comparison + condensed per-property
  if (mode === 'similar' && summary) {
    return (
      <Document
        title={`Investment Comparison - ${properties.length} Properties`}
        author="HomeBuyer AI"
        subject="Investment Comparison"
      >
        <SimilarGroupOverviewPage summary={summary} properties={properties} disclaimer={disclaimer} />
        <PortfolioComparisonPage summary={summary} properties={properties} disclaimer={disclaimer} />
        {properties.flatMap((p, i) => [
          <CondensedPropertyPage1 key={`c1-${i}`} p={p} disclaimer={disclaimer} />,
          <CondensedPropertyPage2 key={`c2-${i}`} p={p} disclaimer={disclaimer} />,
        ])}
      </Document>
    );
  }

  // Curated mode (default for multi-property): overview + comparison + condensed per-property
  return (
    <Document
      title={`Portfolio Prospectus - ${properties.length} Properties`}
      author="HomeBuyer AI"
      subject="Portfolio Investment Analysis"
    >
      <CuratedPortfolioOverviewPage summary={summary!} properties={properties} disclaimer={disclaimer} />
      <PortfolioComparisonPage summary={summary!} properties={properties} disclaimer={disclaimer} />
      {properties.flatMap((p, i) => [
        <CondensedPropertyPage1 key={`c1-${i}`} p={p} disclaimer={disclaimer} />,
        <CondensedPropertyPage2 key={`c2-${i}`} p={p} disclaimer={disclaimer} />,
      ])}
    </Document>
  );
}

// ---------------------------------------------------------------------------
// Filename builder
// ---------------------------------------------------------------------------

function buildFilename(data: InvestmentProspectusResponse): string {
  const today = new Date().toISOString().split('T')[0];
  const mode = data.portfolio_summary?.mode;

  if (mode === 'thesis') {
    return `Berkeley-Investment-Thesis-${data.properties.length}-Properties-${today}.pdf`;
  }

  if (data.is_multi_property) {
    const label = mode === 'similar' ? 'Comparison' : 'Portfolio';
    return `${label}-Prospectus-${data.properties.length}-Properties-${today}.pdf`;
  }

  const addr = data.properties[0]?.address;
  if (addr) {
    const clean = addr
      .replace(/[^a-zA-Z0-9 ]/g, '')
      .trim()
      .replace(/\s+/g, '-')
      .toUpperCase();
    return `Prospectus-${clean}-${today}.pdf`;
  }
  return `Investment-Prospectus-${today}.pdf`;
}

// ---------------------------------------------------------------------------
// Download helper
// ---------------------------------------------------------------------------

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function generateProspectusPdf(
  data: InvestmentProspectusResponse,
): Promise<void> {
  const blob = await pdf(<ProspectusDocument data={data} />).toBlob();
  downloadBlob(blob, buildFilename(data));
}
