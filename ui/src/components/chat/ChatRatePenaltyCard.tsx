import { ArrowUpDown, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { RatePenaltyBlockData } from '../../types';

export function ChatRatePenaltyCard({ data }: { data: RatePenaltyBlockData }) {
  const d = data;
  const scenarios = d.rate_scenarios ?? [];

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-orange-50 to-amber-50 border-b border-gray-100 flex items-center gap-2">
        <ArrowUpDown size={14} className="text-orange-600" />
        <h4 className="text-sm font-semibold text-gray-900">Rate Lock Penalty</h4>
        {d.monthly_penalty != null && (
          <span
            className={`ml-auto text-lg font-bold ${(d.monthly_penalty ?? 0) > 0 ? 'text-red-600' : 'text-green-600'}`}
          >
            {d.monthly_penalty > 0 ? '+' : ''}
            {formatCurrency(d.monthly_penalty)}/mo
          </span>
        )}
      </div>

      {/* Payment comparison */}
      <div className="grid grid-cols-2 gap-0 divide-x divide-gray-100">
        <div className="px-4 py-3 text-center">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide">Existing Payment</p>
          <p className="text-sm font-bold text-gray-900 mt-0.5">
            {d.existing_monthly_payment != null ? formatCurrency(d.existing_monthly_payment) : '–'}
          </p>
          <p className="text-[10px] text-gray-400 mt-0.5">
            {d.existing_rate != null ? `${d.existing_rate}%` : '–'}
          </p>
        </div>
        <div className="px-4 py-3 text-center">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide">New Payment</p>
          <p className="text-sm font-bold text-gray-900 mt-0.5">
            {d.new_monthly_payment != null ? formatCurrency(d.new_monthly_payment) : '–'}
          </p>
          <p className="text-[10px] text-gray-400 mt-0.5">
            {d.new_rate != null ? `${d.new_rate}%` : '–'}
          </p>
        </div>
      </div>

      {/* Income context */}
      {d.penalty_pct_of_income != null && (
        <div className="px-4 py-2 border-t border-gray-100 flex items-center justify-between text-xs">
          <span className="text-gray-500">Penalty as % of income</span>
          <span
            className={`font-medium flex items-center gap-1 ${d.is_tolerable ? 'text-green-600' : 'text-red-600'}`}
          >
            {d.is_tolerable ? (
              <CheckCircle2 size={10} />
            ) : (
              <AlertTriangle size={10} />
            )}
            {d.penalty_pct_of_income.toFixed(1)}%
            {d.is_tolerable ? ' (tolerable)' : ` (>${d.tolerable_threshold_pct ?? 5}%)`}
          </span>
        </div>
      )}

      {/* Breakeven */}
      {d.breakeven_description && (
        <div className="px-4 py-2 border-t border-gray-100 text-xs text-gray-600">
          {d.breakeven_description}
        </div>
      )}

      {/* Rate scenarios table */}
      {scenarios.length > 0 && (
        <div className="overflow-x-auto border-t border-gray-100">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
                <th className="px-3 py-2 text-left">Rate</th>
                <th className="px-3 py-2 text-right">Payment</th>
                <th className="px-3 py-2 text-right">Penalty/mo</th>
                <th className="px-3 py-2 text-right">% Income</th>
                <th className="px-3 py-2 text-center">OK?</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {scenarios.map((s, i) => (
                <tr
                  key={i}
                  className={
                    s.rate != null && d.new_rate != null && s.rate === d.new_rate
                      ? 'bg-orange-50'
                      : ''
                  }
                >
                  <td className="px-3 py-1.5 font-medium text-gray-700">
                    {s.rate != null ? `${s.rate.toFixed(2)}%` : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-600">
                    {s.monthly_payment != null ? formatCurrency(s.monthly_payment) : '–'}
                  </td>
                  <td
                    className={`px-3 py-1.5 text-right font-medium ${(s.monthly_penalty ?? 0) > 0 ? 'text-red-600' : 'text-green-600'}`}
                  >
                    {s.monthly_penalty != null ? formatCurrency(s.monthly_penalty) : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-600">
                    {s.penalty_pct_of_income != null ? `${s.penalty_pct_of_income.toFixed(1)}%` : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    {s.is_tolerable != null ? (
                      s.is_tolerable ? (
                        <CheckCircle2 size={12} className="text-green-500 inline" />
                      ) : (
                        <AlertTriangle size={12} className="text-red-400 inline" />
                      )
                    ) : (
                      '–'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
