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
          Avg Built: <span className="font-medium text-gray-700">
            {stats.avg_year_built ?? '—'}
          </span>
        </div>
        <div className="text-gray-500">
          Avg $/sqft: <span className="font-medium text-gray-700">
            {stats.avg_ppsf ? `$${Math.round(stats.avg_ppsf)}` : '—'}
          </span>
        </div>
      </div>
    </div>
  );
}
