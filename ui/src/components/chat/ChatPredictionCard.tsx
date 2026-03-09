/**
 * Compact prediction card for chat inline display.
 * Shows predicted price, confidence range, and top feature contributions.
 */
import { TrendingUp, TrendingDown } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';

interface PredictionData {
  predicted_price: number;
  price_lower: number;
  price_upper: number;
  neighborhood?: string;
  base_value?: number;
  feature_contributions?: {
    name: string;
    value: number;
    raw_feature?: string;
  }[];
}

export function ChatPredictionCard({ data }: { data: Record<string, unknown> }) {
  const d = data as unknown as PredictionData;
  const contributions = d.feature_contributions?.slice(0, 5) ?? [];

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header with predicted price */}
      <div className="px-4 py-3 bg-gradient-to-r from-green-50 to-emerald-50 border-b border-gray-100">
        <p className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">
          Predicted Value
        </p>
        <p className="text-2xl font-bold text-green-700 mt-0.5">
          {formatCurrency(d.predicted_price)}
        </p>
        <p className="text-xs text-gray-500 mt-0.5">
          90% range: {formatCurrency(d.price_lower)} {'\u2013'} {formatCurrency(d.price_upper)}
        </p>
      </div>

      {/* Top feature contributions */}
      {contributions.length > 0 && (
        <div className="px-4 py-3">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-2">
            Top Price Drivers
          </p>
          <div className="space-y-1.5">
            {contributions.map((c, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="text-gray-600 truncate mr-2">{c.name}</span>
                <span
                  className={`font-medium whitespace-nowrap flex items-center gap-0.5 ${
                    c.value >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}
                >
                  {c.value >= 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                  {c.value >= 0 ? '+' : ''}
                  {formatCurrency(c.value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
