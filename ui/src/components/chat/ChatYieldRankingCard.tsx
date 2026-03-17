import { Trophy, TrendingUp, TrendingDown } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { YieldRankingBlockData, YieldRankingProperty } from '../../types';

export function ChatYieldRankingCard({
  data,
  onAddressClick,
}: {
  data: YieldRankingBlockData;
  onAddressClick?: (address: string) => void;
}) {
  const d = data;
  const ranked = d.ranked_by_spread ?? [];

  if (ranked.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        No properties to rank.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-yellow-50 to-amber-50 border-b border-gray-100 flex items-center gap-2">
        <Trophy size={14} className="text-amber-600" />
        <h4 className="text-sm font-semibold text-gray-900">Yield Ranking</h4>
        <span className="text-[10px] text-gray-400 ml-auto">
          {d.property_count ?? ranked.length} properties
        </span>
      </div>

      {/* Summary badges */}
      <div className="px-4 py-2 border-b border-gray-100 flex flex-wrap gap-2 text-[10px]">
        {d.positive_cash_flow_count != null && (
          <span className="bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">
            {d.positive_cash_flow_count} cash-flow positive
          </span>
        )}
        {d.negative_spread_count != null && d.negative_spread_count > 0 && (
          <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">
            {d.negative_spread_count} negative spread
          </span>
        )}
      </div>

      {/* Ranking table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
              <th className="px-3 py-2 text-left">#</th>
              <th className="px-3 py-2 text-left">Address</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-right">Cap Rate</th>
              <th className="px-3 py-2 text-right">CoC</th>
              <th className="px-3 py-2 text-right">DSCR</th>
              <th className="px-3 py-2 text-right">Spread</th>
              <th className="px-3 py-2 text-right">CF/mo</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {ranked.slice(0, 10).map((p, i) => (
              <PropertyRow
                key={i}
                rank={i + 1}
                property={p}
                isBest={d.best_leverage_spread?.address === p.address}
                onAddressClick={onAddressClick}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Best picks footer */}
      {(d.best_leverage_spread || d.best_dscr || d.best_cash_on_cash) && (
        <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1.5">
            Top Picks
          </p>
          <div className="space-y-1 text-xs">
            {d.best_leverage_spread && (
              <BestPick label="Best Spread" property={d.best_leverage_spread} metric="leverage_spread_pct" />
            )}
            {d.best_dscr && <BestPick label="Best DSCR" property={d.best_dscr} metric="dscr" />}
            {d.best_cash_on_cash && (
              <BestPick label="Best CoC" property={d.best_cash_on_cash} metric="cash_on_cash_pct" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function PropertyRow({
  rank,
  property: p,
  isBest,
  onAddressClick,
}: {
  rank: number;
  property: YieldRankingProperty;
  isBest: boolean;
  onAddressClick?: (address: string) => void;
}) {
  const cf = p.monthly_cash_flow ?? 0;
  const spread = p.leverage_spread_pct ?? 0;
  return (
    <tr className={isBest ? 'bg-amber-50' : ''}>
      <td className="px-3 py-1.5 text-gray-400 font-medium">{rank}</td>
      <td className="px-3 py-1.5 text-gray-900 font-medium max-w-[180px] truncate">
        {onAddressClick && p.address ? (
          <button
            className="text-indigo-600 hover:text-indigo-800 hover:underline text-left"
            onClick={() => onAddressClick(p.address!)}
          >
            {p.address}
          </button>
        ) : (
          p.address || '–'
        )}
      </td>
      <td className="px-3 py-1.5 text-right text-gray-600">
        {p.price != null ? formatCurrency(p.price) : '–'}
      </td>
      <td className="px-3 py-1.5 text-right text-gray-600">
        {p.cap_rate_pct != null ? `${p.cap_rate_pct}%` : '–'}
      </td>
      <td className="px-3 py-1.5 text-right text-gray-600">
        {p.cash_on_cash_pct != null ? `${p.cash_on_cash_pct}%` : '–'}
      </td>
      <td className="px-3 py-1.5 text-right text-gray-600">
        {p.dscr != null ? p.dscr.toFixed(2) : '–'}
      </td>
      <td
        className={`px-3 py-1.5 text-right font-medium flex items-center justify-end gap-0.5 ${spread >= 0 ? 'text-green-600' : 'text-red-600'}`}
      >
        {spread >= 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
        {p.leverage_spread_pct != null ? `${p.leverage_spread_pct}%` : '–'}
      </td>
      <td className={`px-3 py-1.5 text-right font-medium ${cf >= 0 ? 'text-green-600' : 'text-red-600'}`}>
        {p.monthly_cash_flow != null ? formatCurrency(p.monthly_cash_flow) : '–'}
      </td>
    </tr>
  );
}

function BestPick({
  label,
  property: p,
  metric,
}: {
  label: string;
  property: YieldRankingProperty;
  metric: keyof YieldRankingProperty;
}) {
  const val = p[metric];
  return (
    <div className="flex items-center justify-between">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-700 font-medium">
        {p.address || '–'}{' '}
        <span className="text-gray-400">
          ({typeof val === 'number' ? (metric === 'dscr' ? val.toFixed(2) : `${val}%`) : '–'})
        </span>
      </span>
    </div>
  );
}
