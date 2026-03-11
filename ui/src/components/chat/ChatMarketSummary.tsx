/**
 * Compact market summary card for chat inline display.
 * Shows 4 key market metrics as a stat grid.
 */
import { BarChart3, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { MarketBlockData } from '../../types';

export function ChatMarketSummary({ data }: { data: MarketBlockData }) {
  const d = data;
  const m = d.current_market;

  if (!m) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        Market data unavailable.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-sky-50 to-blue-50 border-b border-gray-100 flex items-center gap-2">
        <BarChart3 size={14} className="text-blue-600" />
        <h4 className="text-sm font-semibold text-gray-900">Berkeley Market Overview</h4>
        {m.period && <span className="text-[10px] text-gray-400 ml-auto">{m.period}</span>}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-0 divide-x divide-gray-100">
        <StatCell label="Median Price" value={formatCurrency(m.median_sale_price)} />
        <StatCell
          label="Sale/List"
          value={m.sale_to_list_ratio ? `${(m.sale_to_list_ratio * 100).toFixed(1)}%` : '\u2014'}
        />
        <StatCell
          label="Days on Market"
          value={m.median_days_on_market != null ? String(m.median_days_on_market) : '\u2014'}
        />
        <StatCell
          label="30yr Rate"
          value={m.mortgage_rate_30yr ? `${m.mortgage_rate_30yr.toFixed(2)}%` : '\u2014'}
        />
      </div>

      {/* Top neighborhoods */}
      {d.top_neighborhoods_by_price && d.top_neighborhoods_by_price.length > 0 && (
        <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase mb-1.5">Top Neighborhoods</p>
          <div className="space-y-1">
            {d.top_neighborhoods_by_price.slice(0, 4).map((n) => (
              <div key={n.name} className="flex items-center justify-between text-xs">
                <span className="text-gray-600 truncate mr-2">{n.name}</span>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">
                    {formatCurrency(n.median_price)}
                  </span>
                  {n.yoy_change != null && (
                    <span
                      className={`flex items-center gap-0.5 ${
                        n.yoy_change > 0 ? 'text-green-600' : n.yoy_change < 0 ? 'text-red-600' : 'text-gray-400'
                      }`}
                    >
                      {n.yoy_change > 0 ? <TrendingUp size={10} /> : n.yoy_change < 0 ? <TrendingDown size={10} /> : <Minus size={10} />}
                      {n.yoy_change > 0 ? '+' : ''}{n.yoy_change.toFixed(1)}%
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-3 py-3 text-center">
      <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-sm font-bold text-gray-900 mt-0.5">{value}</p>
    </div>
  );
}
