/**
 * SVG chart components for react-pdf prospectus.
 *
 * Built on @react-pdf/renderer SVG primitives (Svg, Rect, Line, Path, G, Text).
 * Standard chart libraries (Recharts, Chart.js) are NOT compatible with
 * react-pdf's rendering engine.
 */
import { Svg, Rect, Line, Path, G, Text as SvgText, View, Text } from '@react-pdf/renderer';
import { formatCompact, formatPct } from './utils';
import type { ProspectusScenario } from '../types';

// ---------------------------------------------------------------------------
// Color palette
// ---------------------------------------------------------------------------

export const CHART_COLORS = [
  '#D97706', // amber
  '#059669', // green
  '#2563EB', // blue
  '#7C3AED', // purple
  '#DC2626', // red
  '#0891B2', // cyan
  '#D946EF', // fuchsia
  '#EA580C', // orange
  '#4F46E5', // indigo
  '#65A30D', // lime
];

const C = {
  gray900: '#111827',
  gray700: '#374151',
  gray500: '#6B7280',
  gray400: '#9CA3AF',
  gray200: '#E5E7EB',
  gray100: '#F3F4F6',
  white: '#FFFFFF',
};

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

/** Narrow wrapper used as a BarChart valueFormatter (only receives non-null numbers). */
const fmtCompact = (n: number) => formatCompact(n);
const fmtPctShort = (n: number) => formatPct(n);

// ---------------------------------------------------------------------------
// BarChart
// ---------------------------------------------------------------------------

export interface BarChartDatum {
  label: string;
  value: number;
  color?: string;
}

interface BarChartProps {
  data: BarChartDatum[];
  width: number;
  height: number;
  title?: string;
  barColor?: string;
  valueFormatter?: (n: number) => string;
  highlightMax?: boolean;
}

export function BarChart({
  data,
  width,
  height,
  title,
  barColor = CHART_COLORS[0],
  valueFormatter = fmtCompact,
  highlightMax = false,
}: BarChartProps) {
  if (!data.length) return null;

  const padLeft = 8;
  const padRight = 8;
  const padTop = title ? 20 : 12;
  const padBottom = 28;

  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  const maxVal = Math.max(...data.map((d) => Math.abs(d.value)), 1);
  const maxIdx = highlightMax
    ? data.reduce((mi, d, i, arr) => (d.value > arr[mi].value ? i : mi), 0)
    : -1;

  const gap = Math.max(2, chartW * 0.05);
  const barW = Math.max(8, (chartW - gap * (data.length - 1)) / data.length);

  return (
    <Svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {/* Title */}
      {title && (
        <SvgText
          x={width / 2}
          y={10}
          textAnchor="middle"
          style={{ fontSize: 8, fontFamily: 'Helvetica-Bold', fill: C.gray700 } as any}
        >
          {title}
        </SvgText>
      )}

      {/* Baseline */}
      <Line
        x1={padLeft}
        y1={padTop + chartH}
        x2={padLeft + chartW}
        y2={padTop + chartH}
        strokeWidth={0.5}
        stroke={C.gray200}
      />

      {/* Bars + labels */}
      {data.map((d, i) => {
        const barH = (Math.abs(d.value) / maxVal) * chartH * 0.85;
        const x = padLeft + i * (barW + gap);
        const y = padTop + chartH - barH;
        const fill = d.color || (i === maxIdx ? '#059669' : barColor);

        // Truncate label
        const lbl = d.label.length > 10 ? d.label.slice(0, 9) + '…' : d.label;

        return (
          <G key={i}>
            {/* Bar */}
            <Rect x={x} y={y} width={barW} height={barH} fill={fill} rx={2} />

            {/* Value above bar */}
            <SvgText
              x={x + barW / 2}
              y={y - 3}
              textAnchor="middle"
              style={{ fontSize: 6.5, fontFamily: 'Helvetica-Bold', fill: C.gray700 } as any}
            >
              {valueFormatter(d.value)}
            </SvgText>

            {/* Label below */}
            <SvgText
              x={x + barW / 2}
              y={padTop + chartH + 10}
              textAnchor="middle"
              style={{ fontSize: 5.5, fill: C.gray500 } as any}
            >
              {lbl}
            </SvgText>
          </G>
        );
      })}
    </Svg>
  );
}

// ---------------------------------------------------------------------------
// DonutChart
// ---------------------------------------------------------------------------

export interface DonutChartDatum {
  label: string;
  value: number;
  color: string;
}

interface DonutChartProps {
  data: DonutChartDatum[];
  width: number;
  height: number;
  innerRadiusRatio?: number;
  centerLabel?: string;
  centerValue?: string;
  showLegend?: boolean;
}

function polarToXY(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function donutSegmentPath(
  cx: number,
  cy: number,
  outerR: number,
  innerR: number,
  startAngle: number,
  endAngle: number,
): string {
  // Handle full-circle case (single segment = 100%)
  if (endAngle - startAngle >= 359.99) {
    // Two half-circles to avoid SVG arc ambiguity
    const o1 = polarToXY(cx, cy, outerR, startAngle);
    const o2 = polarToXY(cx, cy, outerR, startAngle + 180);
    const i1 = polarToXY(cx, cy, innerR, startAngle);
    const i2 = polarToXY(cx, cy, innerR, startAngle + 180);
    return [
      `M ${o1.x} ${o1.y}`,
      `A ${outerR} ${outerR} 0 0 1 ${o2.x} ${o2.y}`,
      `A ${outerR} ${outerR} 0 0 1 ${o1.x} ${o1.y}`,
      `L ${i1.x} ${i1.y}`,
      `A ${innerR} ${innerR} 0 0 0 ${i2.x} ${i2.y}`,
      `A ${innerR} ${innerR} 0 0 0 ${i1.x} ${i1.y}`,
      'Z',
    ].join(' ');
  }

  const outerStart = polarToXY(cx, cy, outerR, startAngle);
  const outerEnd = polarToXY(cx, cy, outerR, endAngle);
  const innerStart = polarToXY(cx, cy, innerR, startAngle);
  const innerEnd = polarToXY(cx, cy, innerR, endAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;

  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
    'Z',
  ].join(' ');
}

export function DonutChart({
  data,
  width,
  height,
  innerRadiusRatio = 0.55,
  centerLabel,
  centerValue,
  showLegend = true,
}: DonutChartProps) {
  if (!data.length) return null;

  const total = data.reduce((s, d) => s + d.value, 0);
  if (total <= 0) return null;

  // Chart area (legend takes right portion)
  const legendW = showLegend ? Math.min(90, width * 0.4) : 0;
  const chartArea = width - legendW;
  const cx = chartArea / 2;
  const cy = height / 2;
  const outerR = Math.min(chartArea, height) / 2 - 4;
  const innerR = outerR * innerRadiusRatio;

  let currentAngle = 0;
  const segments = data.map((d) => {
    const sweepAngle = (d.value / total) * 360;
    const seg = {
      ...d,
      startAngle: currentAngle,
      endAngle: currentAngle + sweepAngle,
      pct: ((d.value / total) * 100).toFixed(0),
    };
    currentAngle += sweepAngle;
    return seg;
  });

  return (
    <View style={{ flexDirection: 'row', alignItems: 'center' }}>
      <Svg width={chartArea} height={height} viewBox={`0 0 ${chartArea} ${height}`}>
        {segments.map((seg, i) => (
          <Path
            key={i}
            d={donutSegmentPath(cx, cy, outerR, innerR, seg.startAngle, seg.endAngle)}
            fill={seg.color}
          />
        ))}

        {/* Center text */}
        {centerValue && (
          <SvgText
            x={cx}
            y={cy - 2}
            textAnchor="middle"
            style={{ fontSize: 10, fontFamily: 'Helvetica-Bold', fill: C.gray900 } as any}
          >
            {centerValue}
          </SvgText>
        )}
        {centerLabel && (
          <SvgText
            x={cx}
            y={cy + 10}
            textAnchor="middle"
            style={{ fontSize: 6, fill: C.gray500 } as any}
          >
            {centerLabel}
          </SvgText>
        )}
      </Svg>

      {/* Legend */}
      {showLegend && (
        <View style={{ width: legendW, paddingLeft: 4 }}>
          {segments.map((seg, i) => (
            <View key={i} style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 3 }}>
              <View
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 1,
                  backgroundColor: seg.color,
                  marginRight: 4,
                }}
              />
              <Text style={{ fontSize: 6, color: C.gray700 }}>
                {seg.label.length > 12 ? seg.label.slice(0, 11) + '…' : seg.label}{' '}
                <Text style={{ fontFamily: 'Helvetica-Bold' }}>{seg.pct}%</Text>
              </Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Pre-built chart instances
// ---------------------------------------------------------------------------

/**
 * Compare cash-on-cash % across investment scenarios.
 */
export function ScenarioComparisonBar({
  scenarios,
  width = 220,
  height = 120,
}: {
  scenarios: ProspectusScenario[];
  width?: number;
  height?: number;
}) {
  const data: BarChartDatum[] = scenarios.map((sc, i) => ({
    label: sc.scenario_name || sc.scenario_type || `Scenario ${i + 1}`,
    value: sc.cash_on_cash_pct ?? 0,
    color: CHART_COLORS[i % CHART_COLORS.length],
  }));

  return (
    <BarChart
      data={data}
      width={width}
      height={height}
      title="Cash-on-Cash Return (%)"
      valueFormatter={fmtPctShort}
      highlightMax
    />
  );
}

/**
 * Donut chart of expense categories from the best scenario.
 */
export function ExpenseDonut({
  expenses,
  width = 200,
  height = 120,
}: {
  expenses: NonNullable<ProspectusScenario['expenses']>;
  width?: number;
  height?: number;
}) {
  const items = [
    { label: 'Property Tax', value: expenses.property_tax, color: CHART_COLORS[0] },
    { label: 'Insurance', value: expenses.insurance, color: CHART_COLORS[1] },
    { label: 'Maintenance', value: expenses.maintenance, color: CHART_COLORS[2] },
    { label: 'Vacancy', value: expenses.vacancy_reserve, color: CHART_COLORS[3] },
    { label: 'Management', value: expenses.management_fee, color: CHART_COLORS[4] },
  ];
  // Filter out zero values and add HOA/utilities if nonzero
  if (expenses.hoa > 0) {
    items.push({ label: 'HOA', value: expenses.hoa, color: CHART_COLORS[5] });
  }
  if (expenses.utilities > 0) {
    items.push({ label: 'Utilities', value: expenses.utilities, color: CHART_COLORS[6] });
  }
  const data = items.filter((d) => d.value > 0);

  return (
    <DonutChart
      data={data}
      width={width}
      height={height}
      centerValue={fmtCompact(expenses.total_annual)}
      centerLabel="Annual"
    />
  );
}

/**
 * Year-by-year cash flow projection bars (green for positive, red for negative).
 */
export function CashFlowProjectionBar({
  projections,
  width = 220,
  height = 120,
}: {
  projections: NonNullable<ProspectusScenario['projections']>;
  width?: number;
  height?: number;
}) {
  const data: BarChartDatum[] = projections.map((proj) => ({
    label: `Yr ${proj.year}`,
    value: proj.cash_flow,
    color: proj.cash_flow >= 0 ? '#059669' : '#DC2626',
  }));

  return (
    <BarChart data={data} width={width} height={height} title="Annual Cash Flow" />
  );
}

/**
 * Compare property values across a portfolio.
 */
export function PropertyComparisonBar({
  metrics,
  field = 'estimated_value',
  title = 'Estimated Value',
  width = 220,
  height = 120,
}: {
  metrics: Array<{
    address: string;
    estimated_value: number;
    cap_rate_pct: number;
    cash_on_cash_pct: number;
    monthly_cash_flow: number;
  }>;
  field?: 'estimated_value' | 'cap_rate_pct' | 'cash_on_cash_pct' | 'monthly_cash_flow';
  title?: string;
  width?: number;
  height?: number;
}) {
  const formatter =
    field === 'cap_rate_pct' || field === 'cash_on_cash_pct'
      ? fmtPctShort
      : fmtCompact;

  const data: BarChartDatum[] = metrics.map((m, i) => {
    // Use just the street number/name for brevity
    const shortAddr = m.address.split(',')[0].replace(/\s+(Berkeley|CA).*/i, '');
    return {
      label: shortAddr.length > 12 ? shortAddr.slice(0, 11) + '…' : shortAddr,
      value: m[field],
      color: CHART_COLORS[i % CHART_COLORS.length],
    };
  });

  return (
    <BarChart
      data={data}
      width={width}
      height={height}
      title={title}
      valueFormatter={formatter}
      highlightMax
    />
  );
}

/**
 * Portfolio allocation donut (neighborhood or strategy distribution).
 */
export function PortfolioAllocationDonut({
  allocation,
  title,
  width = 200,
  height = 120,
}: {
  allocation: Record<string, number>;
  title?: string;
  width?: number;
  height?: number;
}) {
  const entries = Object.entries(allocation).sort((a, b) => b[1] - a[1]);
  const data: DonutChartDatum[] = entries.map(([label, value], i) => ({
    label,
    value,
    color: CHART_COLORS[i % CHART_COLORS.length],
  }));
  const total = entries.reduce((s, [, v]) => s + v, 0);

  return (
    <View>
      {title && (
        <Text
          style={{
            fontSize: 7,
            fontFamily: 'Helvetica-Bold',
            color: C.gray700,
            textAlign: 'center',
            marginBottom: 2,
          }}
        >
          {title}
        </Text>
      )}
      <DonutChart
        data={data}
        width={width}
        height={height}
        centerValue={String(total)}
        centerLabel="Properties"
      />
    </View>
  );
}
