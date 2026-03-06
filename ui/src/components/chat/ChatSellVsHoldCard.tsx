/**
 * Compact sell vs hold card for chat inline display.
 * Shows 1yr/3yr/5yr projections and rental yield summary.
 */
import { Scale, TrendingUp } from 'lucide-react';
import { formatCurrency, formatPct } from '../../lib/utils';

interface SellVsHoldData {
  current_predicted_value?: number;
  confidence_range?: [number, number];
  neighborhood?: string;
  yoy_appreciation_pct?: number;
  mortgage_rate_30yr?: number;
  hold_scenarios?: Record<
    string,
    {
      projected_value?: number;
      appreciation_pct?: number;
      gross_gain?: number;
      estimated_sell_costs?: number;
      net_gain?: number;
    }
  >;
  rental_estimate?: {
    monthly_rent?: number;
    annual_gross_rent?: number;
    annual_net_rent?: number;
    cap_rate_pct?: number;
    price_to_rent_ratio?: number;
    expense_ratio_pct?: number;
    estimation_method?: string;
  };
}

export function ChatSellVsHoldCard({ data }: { data: Record<string, unknown> }) {
  const d = data as unknown as SellVsHoldData;
  const scenarios = d.hold_scenarios ?? {};

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-blue-50 to-cyan-50 border-b border-gray-100 flex items-center gap-2">
        <Scale size={14} className="text-blue-600" />
        <h4 className="text-sm font-semibold text-gray-900">Sell vs Hold Analysis</h4>
      </div>

      {/* Current value */}
      {d.current_predicted_value && (
        <div className="px-4 py-2 border-b border-gray-100 flex items-center justify-between">
          <span className="text-xs text-gray-500">Current Value</span>
          <span className="text-sm font-bold text-gray-900">
            {formatCurrency(d.current_predicted_value)}
          </span>
        </div>
      )}

      {/* Projection table */}
      {Object.keys(scenarios).length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
                <th className="px-4 py-2 text-left">Period</th>
                <th className="px-3 py-2 text-right">Value</th>
                <th className="px-3 py-2 text-right">Gain</th>
                <th className="px-3 py-2 text-right">Net (after costs)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {Object.entries(scenarios).map(([period, s]) => (
                <tr key={period}>
                  <td className="px-4 py-2 font-medium text-gray-700 flex items-center gap-1">
                    <TrendingUp size={10} className="text-green-500" />
                    {period}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-900">
                    {formatCurrency(s.projected_value)}
                  </td>
                  <td className="px-3 py-2 text-right text-green-600">
                    +{formatPct(s.appreciation_pct)}
                  </td>
                  <td className="px-3 py-2 text-right font-medium text-gray-900">
                    {formatCurrency(s.net_gain)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Rental yield summary */}
      {d.rental_estimate && (
        <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase mb-1">Rental Yield</p>
          <div className="flex gap-4 text-xs">
            <span className="text-gray-600">
              Rent: <strong>{formatCurrency(d.rental_estimate.monthly_rent)}</strong>/mo
            </span>
            <span className="text-gray-600">
              Cap rate: <strong>{formatPct(d.rental_estimate.cap_rate_pct)}</strong>
            </span>
            <span className="text-gray-600">
              P/R: <strong>{d.rental_estimate.price_to_rent_ratio?.toFixed(1) ?? '\u2014'}</strong>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
