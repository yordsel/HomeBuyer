import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import type { NeighborhoodStats } from '../types';
import { formatCurrency, formatPct } from '../lib/utils';

interface NeighborhoodCardProps {
  stats: NeighborhoodStats;
  onClick?: () => void;
}

export function NeighborhoodCard({ stats, onClick }: NeighborhoodCardProps) {
  const yoy = stats.yoy_price_change_pct;
  const TrendIcon =
    yoy == null ? Minus : yoy > 0 ? TrendingUp : TrendingDown;
  const trendColor =
    yoy == null ? 'text-gray-400' : yoy > 0 ? 'text-green-600' : 'text-red-600';

  return (
    <div
      onClick={onClick}
      className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md hover:border-blue-200 transition-all cursor-pointer"
    >
      <div className="flex items-start justify-between">
        <h3 className="text-sm font-semibold text-gray-900">{stats.name}</h3>
        <div className={`flex items-center gap-1 ${trendColor}`}>
          <TrendIcon size={14} />
          <span className="text-xs font-medium">{formatPct(yoy, true)}</span>
        </div>
      </div>

      <p className="text-2xl font-bold text-gray-900 mt-2">
        {formatCurrency(stats.median_price)}
      </p>
      <p className="text-xs text-gray-500 mt-0.5">median sale price</p>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-3 text-xs">
        <div className="text-gray-500">
          $/sqft: <span className="font-medium text-gray-700">
            {stats.median_ppsf ? `$${Math.round(stats.median_ppsf)}` : '—'}
          </span>
        </div>
        <div className="text-gray-500">
          Sales: <span className="font-medium text-gray-700">{stats.sale_count}</span>
        </div>
        <div className="text-gray-500">
          Lot: <span className="font-medium text-gray-700">
            {stats.median_lot_size ? `${(stats.median_lot_size / 1000).toFixed(1)}K sqft` : '—'}
          </span>
        </div>
        <div className="text-gray-500">
          Zone: <span className="font-medium text-gray-700">
            {stats.dominant_zoning?.length > 0 ? stats.dominant_zoning.join(', ') : '—'}
          </span>
        </div>
      </div>

      {/* Property type mini-bar */}
      {Object.keys(stats.property_type_breakdown || {}).length > 0 && (
        <div className="mt-2">
          <div className="flex h-1.5 rounded-full overflow-hidden bg-gray-100">
            {Object.entries(stats.property_type_breakdown).map(([type, pct], i) => (
              <div
                key={type}
                className={`h-full ${i === 0 ? 'bg-blue-500' : i === 1 ? 'bg-green-400' : 'bg-amber-400'}`}
                style={{ width: `${pct}%` }}
                title={`${type}: ${pct}%`}
              />
            ))}
          </div>
          <p className="text-[10px] text-gray-400 mt-0.5">
            {Object.entries(stats.property_type_breakdown)
              .slice(0, 2)
              .map(([type, pct]) =>
                `${type.replace('Single Family Residential', 'SFR').replace('Condo/Co-op', 'Condo').replace('Multi-Family (2-4 Unit)', 'Multi 2-4').replace('Multi-Family (5+ Unit)', 'Multi 5+')}: ${pct}%`
              )
              .join(' · ')}
          </p>
        </div>
      )}
    </div>
  );
}
