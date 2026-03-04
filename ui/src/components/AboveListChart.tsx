import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts';
import type { MarketSnapshot } from '../types';

interface AboveListChartProps {
  data: MarketSnapshot[];
}

export function AboveListChart({ data }: AboveListChartProps) {
  // Build chart data with trailing 12-month moving average
  const rawValues = data.map((d) =>
    d.sold_above_list_pct != null ? d.sold_above_list_pct : null,
  );

  const chartData = data.map((d, i) => {
    const raw =
      d.sold_above_list_pct != null ? Math.round(d.sold_above_list_pct) : null;

    // Compute trailing 12-month moving average
    let ma12: number | null = null;
    const window = 12;
    const start = Math.max(0, i - window + 1);
    const slice = rawValues.slice(start, i + 1).filter((v): v is number => v != null);
    if (slice.length >= Math.min(window, i + 1) && slice.length >= 3) {
      ma12 = Math.round((slice.reduce((s, v) => s + v, 0) / slice.length) * 10) / 10;
    }

    return {
      period: d.period,
      raw,
      ma12,
      saleToList:
        d.sale_to_list_ratio != null
          ? Math.round(d.sale_to_list_ratio * 1000) / 10
          : null,
    };
  });

  // Find latest MA value for header display
  const latestMa = [...chartData].reverse().find((d) => d.ma12 != null)?.ma12;
  const latestRaw = [...chartData].reverse().find((d) => d.raw != null)?.raw;

  // Determine trend direction from MA values
  const maValues = chartData.filter((d) => d.ma12 != null);
  let trendLabel = '';
  let trendColor = 'text-gray-500';
  if (maValues.length >= 6) {
    const recent = maValues.slice(-6);
    const first = recent[0].ma12!;
    const last = recent[recent.length - 1].ma12!;
    const diff = last - first;
    if (diff < -3) {
      trendLabel = 'Declining';
      trendColor = 'text-green-600';
    } else if (diff > 3) {
      trendLabel = 'Rising';
      trendColor = 'text-red-600';
    } else {
      trendLabel = 'Stable';
      trendColor = 'text-amber-600';
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">
            Sold Above List Price — 12-Month Moving Average
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Trailing 12-month average of homes sold above asking price.
            {trendLabel && (
              <span className={`ml-2 font-semibold ${trendColor}`}>
                Trend: {trendLabel}
              </span>
            )}
          </p>
        </div>
        <div className="text-right">
          {latestMa != null && (
            <div>
              <p className="text-2xl font-bold text-gray-900">{latestMa}%</p>
              <p className="text-xs text-gray-500">12-mo avg</p>
            </div>
          )}
          {latestRaw != null && (
            <p className="text-xs text-gray-400 mt-0.5">
              Latest month: {latestRaw}%
            </p>
          )}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart
          data={chartData}
          margin={{ top: 5, right: 20, bottom: 5, left: 10 }}
        >
          <defs>
            <linearGradient id="aboveListMaGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ef4444" stopOpacity={0.2} />
              <stop offset="50%" stopColor="#f59e0b" stopOpacity={0.08} />
              <stop offset="100%" stopColor="#22c55e" stopOpacity={0.02} />
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
            domain={[0, 100]}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              // Find values from payload by dataKey
              const rawEntry = payload.find((p) => p.dataKey === 'raw');
              const maEntry = payload.find((p) => p.dataKey === 'ma12');
              const stlEntry = payload.find((p) => p.dataKey === 'saleToList');
              const rawVal = rawEntry?.value as number | null | undefined;
              const maVal = maEntry?.value as number | null | undefined;
              const stlVal = stlEntry?.value as number | null | undefined;
              return (
                <div className="bg-white rounded-lg border border-gray-200 shadow-lg px-4 py-3 text-sm">
                  <p className="font-medium text-gray-900 mb-1">{label}</p>
                  {maVal != null && (
                    <p className="text-gray-700">
                      <span
                        className="inline-block w-3 h-3 rounded-sm mr-2"
                        style={{
                          backgroundColor:
                            maVal > 50 ? '#ef4444' : '#22c55e',
                        }}
                      />
                      12-mo avg:{' '}
                      <span className="font-semibold">{maVal}%</span>
                    </p>
                  )}
                  {rawVal != null && (
                    <p className="text-gray-500 mt-0.5">
                      <span
                        className="inline-block w-3 h-3 rounded-sm mr-2"
                        style={{ backgroundColor: '#fca5a5' }}
                      />
                      Monthly: {rawVal}%
                    </p>
                  )}
                  {stlVal != null && (
                    <p className="text-gray-400 mt-0.5">
                      Sale-to-list ratio: {stlVal}%
                    </p>
                  )}
                </div>
              );
            }}
          />
          <ReferenceLine
            y={50}
            stroke="#9ca3af"
            strokeDasharray="6 4"
            strokeWidth={1}
            label={{
              value: '50%',
              position: 'right',
              fill: '#9ca3af',
              fontSize: 11,
            }}
          />

          {/* Raw monthly values — faded background dots */}
          <Line
            type="monotone"
            dataKey="raw"
            stroke="#fca5a5"
            strokeWidth={1}
            strokeOpacity={0.5}
            dot={{ r: 1.5, fill: '#fca5a5', strokeWidth: 0 }}
            activeDot={{ r: 3, stroke: '#fca5a5', strokeWidth: 1, fill: '#fff' }}
            connectNulls
          />

          {/* 12-month moving average — primary bold line with gradient fill */}
          <Area
            type="monotone"
            dataKey="ma12"
            stroke="#dc2626"
            strokeWidth={2.5}
            fill="url(#aboveListMaGradient)"
            activeDot={{
              r: 5,
              stroke: '#dc2626',
              strokeWidth: 2,
              fill: '#fff',
            }}
            connectNulls
          />

          {/* Sale-to-list ratio — dashed blue context line */}
          <Line
            type="monotone"
            dataKey="saleToList"
            stroke="#3b82f6"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            activeDot={{
              r: 4,
              stroke: '#3b82f6',
              strokeWidth: 2,
              fill: '#fff',
            }}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex items-center gap-5 mt-3 text-xs text-gray-500">
        <div className="flex items-center gap-1.5">
          <span className="w-4 h-0.5 bg-red-600 inline-block rounded" />
          12-mo moving avg
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="w-4 h-0.5 inline-block rounded"
            style={{ backgroundColor: '#fca5a5' }}
          />
          Monthly raw
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="w-4 h-0.5 bg-blue-500 inline-block rounded"
            style={{ borderTop: '1.5px dashed #3b82f6', height: 0 }}
          />
          Sale-to-list ratio %
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="w-4 h-0.5 bg-gray-400 inline-block rounded"
            style={{ borderTop: '1.5px dashed #9ca3af', height: 0 }}
          />
          50% threshold
        </div>
      </div>
    </div>
  );
}
