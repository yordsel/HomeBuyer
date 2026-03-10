/**
 * PDF document generation for the Investment Prospectus.
 *
 * Uses @react-pdf/renderer to create a professional letter-size PDF
 * from InvestmentProspectusResponse data. Lazy-loaded to avoid
 * impacting the initial bundle.
 */
import {
  Document,
  Page,
  Text,
  View,
  StyleSheet,
  pdf,
} from '@react-pdf/renderer';
import type {
  InvestmentProspectusResponse,
  PropertyProspectus,
  PortfolioSummary,
  ProspectusScenario,
  ProspectusComparable,
} from '../types';

// ---------------------------------------------------------------------------
// Colors
// ---------------------------------------------------------------------------
const C = {
  amber: '#D97706',
  amberLight: '#FEF3C7',
  green: '#059669',
  red: '#DC2626',
  gray900: '#111827',
  gray700: '#374151',
  gray600: '#4B5563',
  gray500: '#6B7280',
  gray400: '#9CA3AF',
  gray200: '#E5E7EB',
  gray100: '#F3F4F6',
  gray50: '#F9FAFB',
  white: '#FFFFFF',
};

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------
const s = StyleSheet.create({
  page: {
    fontFamily: 'Helvetica',
    fontSize: 9,
    color: C.gray700,
    paddingTop: 54,
    paddingBottom: 54,
    paddingHorizontal: 54,
  },
  // Section headers
  sectionHeader: {
    fontSize: 11,
    fontFamily: 'Helvetica-Bold',
    color: C.amber,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginTop: 18,
    marginBottom: 4,
    paddingBottom: 4,
    borderBottomWidth: 1,
    borderBottomColor: C.amber,
  },
  // Key/value row
  kvRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 2,
  },
  kvLabel: { color: C.gray500, fontSize: 9 },
  kvValue: { fontFamily: 'Helvetica-Bold', fontSize: 9, color: C.gray900 },
  // Table
  tableHeader: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: C.gray200,
    paddingBottom: 3,
    marginBottom: 3,
  },
  tableHeaderText: {
    fontFamily: 'Helvetica-Bold',
    fontSize: 8,
    color: C.gray500,
    textTransform: 'uppercase',
  },
  tableRow: {
    flexDirection: 'row',
    paddingVertical: 2,
    borderBottomWidth: 0.5,
    borderBottomColor: C.gray100,
  },
  tableRowHighlight: {
    backgroundColor: '#ECFDF5',
  },
  tableCell: { fontSize: 8.5, color: C.gray700 },
  // Footer
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    borderTopWidth: 0.5,
    borderTopColor: C.gray200,
    paddingTop: 4,
    marginTop: 'auto',
  },
  footerText: { fontSize: 7, color: C.gray400 },
  // Metrics grid
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginTop: 6,
    gap: 0,
  },
  metricCell: {
    width: '25%',
    paddingVertical: 6,
    alignItems: 'center',
  },
  metricLabel: {
    fontSize: 7.5,
    color: C.gray500,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  metricValue: {
    fontSize: 13,
    fontFamily: 'Helvetica-Bold',
    color: C.gray900,
    marginTop: 2,
  },
  // Badge
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 10,
    marginRight: 6,
    marginBottom: 4,
  },
  badgeEligible: { backgroundColor: '#ECFDF5', borderWidth: 0.5, borderColor: '#A7F3D0' },
  badgeIneligible: { backgroundColor: C.gray50, borderWidth: 0.5, borderColor: C.gray200 },
  badgeText: { fontSize: 8 },
});

// ---------------------------------------------------------------------------
// Format helpers (duplicated from utils.ts — can't share React DOM utils w/ PDF)
// ---------------------------------------------------------------------------

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return '\u2014';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(n);
}

function fmtPct(pct: number | null | undefined, showSign = false): string {
  if (pct == null) return '\u2014';
  const prefix = showSign && pct > 0 ? '+' : '';
  return `${prefix}${pct.toFixed(1)}%`;
}

function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '\u2014';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

function fmtNumber(n: number | null | undefined): string {
  if (n == null) return '\u2014';
  return new Intl.NumberFormat('en-US').format(n);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PageFooter({ disclaimer }: { disclaimer?: string }) {
  return (
    <View style={s.footer}>
      <Text style={s.footerText}>{disclaimer || 'For informational purposes only.'}</Text>
      <Text style={s.footerText}>HomeBuyer AI</Text>
    </View>
  );
}

function KVRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={s.kvRow}>
      <Text style={s.kvLabel}>{label}</Text>
      <Text style={s.kvValue}>{value}</Text>
    </View>
  );
}

function SectionHeader({ children }: { children: string }) {
  return <Text style={s.sectionHeader}>{children}</Text>;
}

function MetricBox({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <View style={s.metricCell}>
      <Text style={s.metricLabel}>{label}</Text>
      <Text style={[s.metricValue, color ? { color } : {}]}>{value}</Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Cover Page
// ---------------------------------------------------------------------------

function CoverPage({ p, disclaimer }: { p: PropertyProspectus; disclaimer: string }) {
  return (
    <Page size="LETTER" style={s.page}>
      {/* Title block */}
      <View style={{ marginTop: 72, marginBottom: 24 }}>
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

      {/* Executive Summary */}
      <SectionHeader>Executive Summary</SectionHeader>
      <View
        style={{
          backgroundColor: '#ECFDF5',
          borderRadius: 4,
          padding: 12,
          marginTop: 4,
          marginBottom: 8,
        }}
      >
        <Text style={{ fontSize: 12, fontFamily: 'Helvetica-Bold', color: C.green }}>
          {p.recommended_approach_label || 'Analysis Complete'}
        </Text>
        {p.strategy_rationale && (
          <Text style={{ fontSize: 9.5, color: C.gray600, marginTop: 6, lineHeight: 1.5 }}>
            {p.strategy_rationale}
          </Text>
        )}
      </View>

      {/* Key Metrics */}
      <SectionHeader>Key Metrics</SectionHeader>
      <View style={s.metricsGrid}>
        <MetricBox label="Estimated Value" value={fmtCurrency(p.estimated_value)} />
        <MetricBox label="Capital Required" value={fmtCurrency(p.capital_required)} />
        <MetricBox
          label="Monthly Cash Flow"
          value={fmtCurrency(p.monthly_cash_flow)}
          color={p.monthly_cash_flow >= 0 ? C.green : C.red}
        />
        <MetricBox label="Annual Return" value={fmtPct(p.projected_annual_return_pct)} />
        <MetricBox label="Cap Rate" value={fmtPct(p.cap_rate_pct)} />
        <MetricBox label="Cash-on-Cash" value={fmtPct(p.cash_on_cash_pct)} />
        <MetricBox
          label="GRM"
          value={p.gross_rent_multiplier ? p.gross_rent_multiplier.toFixed(1) : '\u2014'}
        />
        <MetricBox label="Time Horizon" value={`${p.time_horizon_years} years`} />
      </View>

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

      {/* Valuation */}
      <SectionHeader>Valuation</SectionHeader>
      <KVRow label="Estimated Value" value={fmtCurrency(p.estimated_value)} />
      <KVRow label="Low Estimate" value={fmtCurrency(p.value_range_low)} />
      <KVRow label="High Estimate" value={fmtCurrency(p.value_range_high)} />
      {p.value_per_sqft != null && (
        <KVRow label="Value per Sqft" value={`$${p.value_per_sqft.toFixed(0)}`} />
      )}

      {/* Market Context */}
      <SectionHeader>Market Context</SectionHeader>
      <View style={{ flexDirection: 'row' }}>
        <View style={{ width: '50%', paddingRight: 12 }}>
          {p.neighborhood_median_price != null && (
            <KVRow label={`${p.neighborhood} Median`} value={fmtCurrency(p.neighborhood_median_price)} />
          )}
          {p.city_median_price != null && (
            <KVRow label="Berkeley Median" value={fmtCurrency(p.city_median_price)} />
          )}
          {p.neighborhood_yoy_change_pct != null && (
            <KVRow label="YoY Change" value={fmtPct(p.neighborhood_yoy_change_pct, true)} />
          )}
        </View>
        <View style={{ width: '50%', paddingLeft: 12 }}>
          {p.neighborhood_avg_ppsf != null && (
            <KVRow label="Avg $/sqft" value={`$${p.neighborhood_avg_ppsf.toFixed(0)}`} />
          )}
          {p.mortgage_rate_30yr != null && (
            <KVRow label="Mortgage Rate (30yr)" value={`${p.mortgage_rate_30yr.toFixed(2)}%`} />
          )}
          {p.median_dom != null && (
            <KVRow label="Median Days on Market" value={`${p.median_dom} days`} />
          )}
        </View>
      </View>

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
          {/* Header */}
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
          {p.recommendation_notes && (
            <Text style={{ fontSize: 8.5, color: C.gray600, marginTop: 6, lineHeight: 1.4 }}>
              {p.recommendation_notes}
            </Text>
          )}
        </>
      )}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

function DevBadge({
  label,
  eligible,
  detail,
}: {
  label: string;
  eligible: boolean;
  detail?: string;
}) {
  return (
    <View style={[s.badge, eligible ? s.badgeEligible : s.badgeIneligible]}>
      <Text style={[s.badgeText, { color: eligible ? C.green : C.gray400 }]}>
        {eligible ? '\u2713' : '\u2014'} {label}
        {eligible && detail ? ` (${detail})` : ''}
      </Text>
    </View>
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
                {c.price_per_sqft ? `$${c.price_per_sqft.toFixed(0)}` : '\u2014'}
              </Text>
              <Text style={[s.tableCell, { width: '16%', textAlign: 'right' }]}>
                {fmtDate(c.sale_date)}
              </Text>
            </View>
          ))}
        </>
      )}

      {/* Risk Factors */}
      {risks.length > 0 && (
        <>
          <SectionHeader>Risk Factors</SectionHeader>
          {risks.map((risk: string, i: number) => (
            <View key={i} style={{ flexDirection: 'row', marginBottom: 4 }}>
              <Text style={{ color: C.amber, fontSize: 9, marginRight: 6 }}>{'\u26A0'}</Text>
              <Text style={{ fontSize: 9, color: C.gray600, flex: 1, lineHeight: 1.4 }}>
                {risk}
              </Text>
            </View>
          ))}
        </>
      )}

      {/* Disclaimers */}
      <SectionHeader>Disclaimers</SectionHeader>
      {(p.disclaimers ?? []).map((d: string, i: number) => (
        <Text key={i} style={{ fontSize: 7.5, color: C.gray400, marginBottom: 2, lineHeight: 1.4 }}>
          {d}
        </Text>
      ))}

      {/* Data Sources */}
      <SectionHeader>Data Sources</SectionHeader>
      <Text style={{ fontSize: 8, color: C.gray500, lineHeight: 1.4 }}>
        {(p.data_sources ?? []).join(' \u2022 ')}
      </Text>

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Portfolio Summary Page (multi-property only)
// ---------------------------------------------------------------------------

function PortfolioSummaryPage({
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
      <View style={{ marginTop: 48, marginBottom: 24 }}>
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

      {summary.diversification_notes && (
        <Text style={{ fontSize: 9, color: C.gray600, marginTop: 12, lineHeight: 1.5 }}>
          {summary.diversification_notes}
        </Text>
      )}

      {/* Property listing table */}
      <SectionHeader>Properties</SectionHeader>
      <View style={s.tableHeader}>
        <Text style={[s.tableHeaderText, { width: '34%' }]}>Address</Text>
        <Text style={[s.tableHeaderText, { width: '18%', textAlign: 'right' }]}>Est. Value</Text>
        <Text style={[s.tableHeaderText, { width: '18%', textAlign: 'right' }]}>Cash Flow/mo</Text>
        <Text style={[s.tableHeaderText, { width: '15%', textAlign: 'right' }]}>Cap Rate</Text>
        <Text style={[s.tableHeaderText, { width: '15%', textAlign: 'right' }]}>Strategy</Text>
      </View>
      {properties.map((p, i) => (
        <View key={i} style={s.tableRow}>
          <Text style={[s.tableCell, { width: '34%' }]}>{p.address || p.neighborhood}</Text>
          <Text style={[s.tableCell, { width: '18%', textAlign: 'right' }]}>
            {fmtCurrency(p.estimated_value)}
          </Text>
          <Text
            style={[
              s.tableCell,
              {
                width: '18%',
                textAlign: 'right',
                color: p.monthly_cash_flow >= 0 ? C.green : C.red,
              },
            ]}
          >
            {fmtCurrency(p.monthly_cash_flow)}
          </Text>
          <Text style={[s.tableCell, { width: '15%', textAlign: 'right' }]}>
            {fmtPct(p.cap_rate_pct)}
          </Text>
          <Text style={[s.tableCell, { width: '15%', textAlign: 'right', fontSize: 7.5 }]}>
            {p.recommended_approach_label || '\u2014'}
          </Text>
        </View>
      ))}

      <PageFooter disclaimer={disclaimer} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Full Document
// ---------------------------------------------------------------------------

function ProspectusDocument({ data }: { data: InvestmentProspectusResponse }) {
  const properties = data.properties ?? [];
  const disclaimer = properties[0]?.disclaimers?.[0] || 'For informational purposes only.';

  return (
    <Document
      title={
        data.is_multi_property
          ? `Portfolio Prospectus - ${properties.length} Properties`
          : `Investment Prospectus - ${properties[0]?.address || 'Property'}`
      }
      author="HomeBuyer AI"
      subject="Investment Analysis"
    >
      {/* Portfolio summary page (multi-property only) */}
      {data.is_multi_property && data.portfolio_summary && (
        <PortfolioSummaryPage
          summary={data.portfolio_summary}
          properties={properties}
          disclaimer={disclaimer}
        />
      )}

      {/* Per-property pages — Pages must be direct children of Document */}
      {properties.flatMap((p, i) => [
        <CoverPage key={`cover-${i}`} p={p} disclaimer={disclaimer} />,
        <PropertyDetailsPage key={`details-${i}`} p={p} disclaimer={disclaimer} />,
        <DevelopmentAndScenariosPage key={`dev-${i}`} p={p} disclaimer={disclaimer} />,
        <CompsAndRisksPage key={`comps-${i}`} p={p} disclaimer={disclaimer} />,
      ])}
    </Document>
  );
}

// ---------------------------------------------------------------------------
// Filename builder
// ---------------------------------------------------------------------------

function buildFilename(data: InvestmentProspectusResponse): string {
  const today = new Date().toISOString().split('T')[0];

  if (data.is_multi_property) {
    return `Portfolio-Prospectus-${data.properties.length}-Properties-${today}.pdf`;
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
// Public API — lazy-loads @react-pdf/renderer
// ---------------------------------------------------------------------------

export async function generateProspectusPdf(
  data: InvestmentProspectusResponse,
): Promise<void> {
  const blob = await pdf(<ProspectusDocument data={data} />).toBlob();
  downloadBlob(blob, buildFilename(data));
}
