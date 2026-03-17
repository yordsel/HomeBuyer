import { Map, CheckCircle2, Train, School } from 'lucide-react';
import { formatCurrency, formatNumber } from '../../lib/utils';
import type { AdjacentMarketBlockData } from '../../types';

const AFFORDABILITY_COLORS: Record<string, string> = {
  'Very Affordable': 'bg-green-100 text-green-700',
  Affordable: 'bg-emerald-100 text-emerald-700',
  Stretch: 'bg-yellow-100 text-yellow-700',
  'Out of Range': 'bg-red-100 text-red-700',
};

export function ChatAdjacentMarketCard({ data }: { data: AdjacentMarketBlockData }) {
  const d = data;
  const comparisons = d.comparisons ?? [];

  if (comparisons.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        No adjacent market data available.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-indigo-50 to-blue-50 border-b border-gray-100 flex items-center gap-2">
        <Map size={14} className="text-indigo-600" />
        <h4 className="text-sm font-semibold text-gray-900">Adjacent Markets</h4>
        {d.budget != null && (
          <span className="text-[10px] text-gray-400 ml-auto">
            Budget: {formatCurrency(d.budget)}
          </span>
        )}
      </div>

      {/* Summary badges */}
      <div className="px-4 py-2 border-b border-gray-100 flex flex-wrap gap-2 text-[10px]">
        {d.affordable_count != null && (
          <span className="bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">
            {d.affordable_count} affordable
          </span>
        )}
        {d.best_value && (
          <span className="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
            Best value: {d.best_value}
          </span>
        )}
      </div>

      {/* Comparison table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
              <th className="px-3 py-2 text-left">Market</th>
              <th className="px-3 py-2 text-right">Median</th>
              <th className="px-3 py-2 text-center">Afford.</th>
              <th className="px-3 py-2 text-right">SqFt Bonus</th>
              <th className="px-3 py-2 text-right">$/SqFt</th>
              <th className="px-3 py-2 text-center">BART</th>
              <th className="px-3 py-2 text-right">Commute</th>
              <th className="px-3 py-2 text-center">Schools</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {comparisons.map((c, i) => {
              const isBest = d.best_value === c.market;
              const isBerkeley =
                d.berkeley_baseline?.market != null && c.market === d.berkeley_baseline.market;
              const badgeClass =
                AFFORDABILITY_COLORS[c.affordability ?? ''] ?? 'bg-gray-100 text-gray-700';

              return (
                <tr
                  key={i}
                  className={isBest ? 'bg-indigo-50' : isBerkeley ? 'bg-blue-50' : ''}
                >
                  <td className="px-3 py-1.5 font-medium text-gray-700 whitespace-nowrap">
                    {isBest && <CheckCircle2 size={10} className="text-indigo-500 inline mr-1" />}
                    {c.market || '–'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-600">
                    {c.median_price != null ? formatCurrency(c.median_price) : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    {c.affordability && (
                      <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded-full ${badgeClass}`}>
                        {c.affordability}
                      </span>
                    )}
                  </td>
                  <td
                    className={`px-3 py-1.5 text-right font-medium ${
                      (c.sqft_bonus ?? 0) > 0 ? 'text-green-600' : (c.sqft_bonus ?? 0) < 0 ? 'text-red-600' : 'text-gray-500'
                    }`}
                  >
                    {c.sqft_bonus != null
                      ? `${c.sqft_bonus > 0 ? '+' : ''}${formatNumber(c.sqft_bonus)}`
                      : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-600">
                    {c.price_per_sqft != null ? `$${c.price_per_sqft}` : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    {c.bart_access ? (
                      <Train size={12} className="text-blue-500 inline" />
                    ) : (
                      <span className="text-gray-300">–</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-600">
                    {c.commute_sf_minutes != null ? `${c.commute_sf_minutes} min` : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    {c.school_rating != null ? (
                      <span className="flex items-center justify-center gap-0.5">
                        <School size={10} className="text-gray-400" />
                        {c.school_rating}
                      </span>
                    ) : (
                      '–'
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
