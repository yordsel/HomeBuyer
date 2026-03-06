/**
 * Compact neighborhood statistics card for chat inline display.
 * Shows median price, YoY change, sale count, and dominant zoning.
 */
import { MapPin, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { formatCurrency, formatPct, formatNumber } from '../../lib/utils';

interface NeighborhoodData {
  name?: string;
  median_price?: number;
  avg_price?: number;
  median_ppsf?: number;
  sale_count?: number;
  yoy_price_change_pct?: number;
  dominant_zoning?: string[];
  median_lot_size?: number;
  avg_year_built?: number;
  property_type_breakdown?: Record<string, number>;
}

export function ChatNeighborhoodStats({ data }: { data: Record<string, unknown> }) {
  const d = data as unknown as NeighborhoodData;

  const yoy = d.yoy_price_change_pct;
  const trendIcon =
    yoy != null && yoy > 0 ? (
      <TrendingUp size={12} className="text-green-500" />
    ) : yoy != null && yoy < 0 ? (
      <TrendingDown size={12} className="text-red-500" />
    ) : (
      <Minus size={12} className="text-gray-400" />
    );
  const trendColor =
    yoy != null && yoy > 0
      ? 'text-green-600'
      : yoy != null && yoy < 0
        ? 'text-red-600'
        : 'text-gray-500';

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-purple-50 to-indigo-50 border-b border-gray-100 flex items-center gap-2">
        <MapPin size={14} className="text-indigo-600" />
        <h4 className="text-sm font-semibold text-gray-900">
          {d.name || 'Neighborhood'}
        </h4>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-0 divide-x divide-gray-100">
        <div className="px-3 py-3 text-center">
          <p className="text-[10px] font-medium text-gray-400 uppercase">Median Price</p>
          <p className="text-sm font-bold text-gray-900 mt-0.5">
            {formatCurrency(d.median_price)}
          </p>
        </div>
        <div className="px-3 py-3 text-center">
          <p className="text-[10px] font-medium text-gray-400 uppercase">YoY Change</p>
          <p className={`text-sm font-bold mt-0.5 flex items-center justify-center gap-0.5 ${trendColor}`}>
            {trendIcon}
            {formatPct(yoy, true)}
          </p>
        </div>
        <div className="px-3 py-3 text-center">
          <p className="text-[10px] font-medium text-gray-400 uppercase">Sales</p>
          <p className="text-sm font-bold text-gray-900 mt-0.5">
            {d.sale_count != null ? formatNumber(d.sale_count) : '\u2014'}
          </p>
        </div>
        <div className="px-3 py-3 text-center">
          <p className="text-[10px] font-medium text-gray-400 uppercase">$/sqft</p>
          <p className="text-sm font-bold text-gray-900 mt-0.5">
            {d.median_ppsf != null ? `$${Math.round(d.median_ppsf)}` : '\u2014'}
          </p>
        </div>
      </div>

      {/* Zoning + property types footer */}
      {(d.dominant_zoning?.length || d.property_type_breakdown) && (
        <div className="px-4 py-2 bg-gray-50 border-t border-gray-100 flex flex-wrap gap-1">
          {d.dominant_zoning?.slice(0, 4).map((z) => (
            <span
              key={z}
              className="inline-block px-1.5 py-0.5 text-[10px] font-medium bg-indigo-100 text-indigo-700 rounded"
            >
              {z}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
