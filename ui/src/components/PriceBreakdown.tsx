import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  ReferenceLine,
} from 'recharts';
import type { FeatureContribution } from '../types';
import { formatCurrency } from '../lib/utils';

interface PriceBreakdownProps {
  baseValue: number;
  contributions: FeatureContribution[];
  predictedPrice: number;
}

/**
 * Horizontal bar chart showing how each feature pushes the predicted
 * price above or below the baseline (average home).
 */
export function PriceBreakdown({
  baseValue,
  contributions,
  predictedPrice,
}: PriceBreakdownProps) {
  // Build chart data: sorted by absolute value, largest first
  const chartData = contributions.map((c) => ({
    name: c.name,
    value: c.value,
    raw: c.raw_feature,
  }));

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-900">
          Price Factors
        </h3>
        <p className="text-xs text-gray-500 mt-0.5">
          How each feature pushes the price above or below the baseline
        </p>
      </div>

      {/* Baseline callout */}
      <div className="px-6 py-3 flex items-center justify-between border-b border-gray-100 bg-blue-50/50">
        <span className="text-sm text-gray-700 font-medium">
          Baseline (avg Berkeley home)
        </span>
        <span className="text-sm font-bold text-blue-700">
          {formatCurrency(baseValue)}
        </span>
      </div>

      {/* Chart */}
      <div className="px-4 py-4">
        <ResponsiveContainer width="100%" height={Math.max(260, chartData.length * 36 + 40)}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 4, right: 60, left: 8, bottom: 4 }}
          >
            <XAxis
              type="number"
              tickFormatter={(v: number) => shortDollar(v)}
              tick={{ fontSize: 11, fill: '#6b7280' }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={160}
              tick={<TruncatedYTick />}
              axisLine={false}
              tickLine={false}
            />
            <ReferenceLine x={0} stroke="#d1d5db" strokeWidth={1} />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ fill: 'rgba(0,0,0,0.04)' }}
            />
            <Bar dataKey="value" radius={[4, 4, 4, 4]} barSize={22} label={<BarLabel />}>
              {chartData.map((entry, idx) => (
                <Cell
                  key={idx}
                  fill={entry.value >= 0 ? '#22c55e' : '#ef4444'}
                  opacity={0.85}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Footer summary */}
      <div className="px-6 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
        <span className="text-xs text-gray-500">
          {formatCurrency(baseValue)} + factors
        </span>
        <span className="text-sm font-bold text-gray-900">
          = {formatCurrency(predictedPrice)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom Y-axis tick — truncates long feature names with ellipsis
// ---------------------------------------------------------------------------

function TruncatedYTick(props: any) {
  const { x, y, payload } = props;
  const maxChars = 22;
  const text: string = payload?.value ?? '';
  const display = text.length > maxChars ? text.slice(0, maxChars - 1) + '…' : text;

  return (
    <text
      x={x}
      y={y}
      textAnchor="end"
      fill="#374151"
      fontSize={12}
      dominantBaseline="central"
    >
      {display}
    </text>
  );
}

// ---------------------------------------------------------------------------
// Custom bar label (dollar amount at end of each bar)
// ---------------------------------------------------------------------------

function BarLabel(props: any) {
  const { x, y, width, height, value } = props;
  if (value == null) return null;

  const isPositive = value >= 0;
  // Positive bars: label to the right of the bar tip
  // Negative bars: label to the right of the zero line (x is the zero point)
  //   to avoid overlapping with Y-axis labels on the left
  const labelX = isPositive ? x + width + 4 : x + 4;

  return (
    <text
      x={labelX}
      y={y + height / 2}
      fill={isPositive ? '#16a34a' : '#dc2626'}
      textAnchor="start"
      dominantBaseline="central"
      fontSize={11}
      fontWeight={600}
    >
      {isPositive ? '+' : ''}{shortDollar(value)}
    </text>
  );
}

// ---------------------------------------------------------------------------
// Custom tooltip
// ---------------------------------------------------------------------------

function CustomTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const isPositive = d.value >= 0;

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs">
      <p className="font-medium text-gray-900">{d.name}</p>
      <p className={isPositive ? 'text-green-600' : 'text-red-600'}>
        {isPositive ? '+' : ''}{formatCurrency(d.value)}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a dollar value as shorthand: $1.2M, $350K, -$50K */
function shortDollar(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1_000_000) {
    return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  }
  if (abs >= 1_000) {
    return `${sign}$${(abs / 1_000).toFixed(0)}K`;
  }
  return `${sign}$${abs.toFixed(0)}`;
}
