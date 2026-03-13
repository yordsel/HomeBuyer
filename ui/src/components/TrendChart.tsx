import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts';
import type { MarketSnapshot } from '../types';
import { formatCurrency, computeMovingAverage, getTrendInfo } from '../lib/utils';

interface TrendChartProps {
  data: MarketSnapshot[];
  dataKey: keyof MarketSnapshot;
  label: string;
  color?: string;
  formatValue?: (v: number) => string;
  /** Y-axis tick formatter — defaults to dollar shorthand ($1.2M, $800K) */
  formatYAxis?: (v: number) => string;
}

/** Lighten a hex color by mixing with white. amount 0–1 (0 = original, 1 = white) */
function lighten(hex: string, amount: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  const lr = Math.round(r + (255 - r) * amount);
  const lg = Math.round(g + (255 - g) * amount);
  const lb = Math.round(b + (255 - b) * amount);
  return `#${lr.toString(16).padStart(2, '0')}${lg.toString(16).padStart(2, '0')}${lb.toString(16).padStart(2, '0')}`;
}

const defaultYAxisFormatter = (v: number) => {
  const n = Number(v);
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return String(n);
};

export function TrendChart({
  data,
  dataKey,
  label,
  color = '#2563eb',
  formatValue = (v) => formatCurrency(v),
  formatYAxis = defaultYAxisFormatter,
}: TrendChartProps) {
  const fadedColor = lighten(color, 0.55);
  const gradientId = `trendGrad_${String(dataKey)}`;

  // Extract raw values and compute trailing 12-month moving average
  const rawValues = data.map((d) => {
    const v = d[dataKey];
    return v != null ? (v as number) : null;
  });
  const ma12Values = computeMovingAverage(rawValues);

  const chartData = data.map((d, i) => ({
    period: d.period,
    raw: rawValues[i],
    ma12: ma12Values[i],
  }));

  // Latest MA and raw for header
  const latestMa = [...chartData].reverse().find((d) => d.ma12 != null)?.ma12;
  const latestRaw = [...chartData].reverse().find((d) => d.raw != null)?.raw;

  // Trend direction from last 6 MA values
  const nonNullMa = chartData.map((d) => d.ma12).filter((v): v is number => v != null);
  const { label: trendLabel, color: trendColor } = getTrendInfo(nonNullMa);

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{label}</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            12-month moving average
            {trendLabel && (
              <span className={`ml-2 font-semibold ${trendColor}`}>
                {trendLabel}
              </span>
            )}
          </p>
        </div>
        <div className="text-right">
          {latestMa != null && (
            <p className="text-lg font-bold text-gray-900">
              {formatValue(latestMa)}
            </p>
          )}
          {latestRaw != null && (
            <p className="text-xs text-gray-400">
              Latest: {formatValue(latestRaw)}
            </p>
          )}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart
          data={chartData}
          margin={{ top: 5, right: 20, bottom: 5, left: 10 }}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.15} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="period"
            tick={{ fontSize: 11, fill: '#6b7280' }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#6b7280' }}
            tickLine={false}
            tickFormatter={formatYAxis}
          />
          <Tooltip
            content={({ active, payload, label: tooltipLabel }) => {
              if (!active || !payload?.length) return null;
              const rawEntry = payload.find((p) => p.dataKey === 'raw');
              const maEntry = payload.find((p) => p.dataKey === 'ma12');
              const rawVal = rawEntry?.value as number | null | undefined;
              const maVal = maEntry?.value as number | null | undefined;
              return (
                <div className="bg-white rounded-lg border border-gray-200 shadow-lg px-4 py-3 text-sm">
                  <p className="font-medium text-gray-900 mb-1">{tooltipLabel}</p>
                  {maVal != null && (
                    <p className="text-gray-700">
                      <span
                        className="inline-block w-3 h-3 rounded-sm mr-2"
                        style={{ backgroundColor: color }}
                      />
                      12-mo avg: <span className="font-semibold">{formatValue(maVal)}</span>
                    </p>
                  )}
                  {rawVal != null && (
                    <p className="text-gray-500 mt-0.5">
                      <span
                        className="inline-block w-3 h-3 rounded-sm mr-2"
                        style={{ backgroundColor: fadedColor }}
                      />
                      Monthly: {formatValue(rawVal)}
                    </p>
                  )}
                </div>
              );
            }}
          />

          {/* Raw monthly — faded thin line */}
          <Line
            type="monotone"
            dataKey="raw"
            stroke={fadedColor}
            strokeWidth={1}
            strokeOpacity={0.6}
            dot={{ r: 1.5, fill: fadedColor, strokeWidth: 0 }}
            activeDot={{ r: 3, stroke: fadedColor, strokeWidth: 1, fill: '#fff' }}
            connectNulls
          />

          {/* 12-month moving average — bold with gradient fill */}
          <Area
            type="monotone"
            dataKey="ma12"
            stroke={color}
            strokeWidth={2.5}
            fill={`url(#${gradientId})`}
            activeDot={{ r: 5, stroke: color, strokeWidth: 2, fill: '#fff' }}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex items-center gap-5 mt-3 text-xs text-gray-500">
        <div className="flex items-center gap-1.5">
          <span className="w-4 h-0.5 inline-block rounded" style={{ backgroundColor: color }} />
          12-mo moving avg
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-4 h-0.5 inline-block rounded" style={{ backgroundColor: fadedColor }} />
          Monthly
        </div>
      </div>
    </div>
  );
}
