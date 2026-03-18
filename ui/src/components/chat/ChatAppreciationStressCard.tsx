import { TrendingDown, TrendingUp, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { AppreciationStressBlockData } from '../../types';

export function ChatAppreciationStressCard({ data }: { data: AppreciationStressBlockData }) {
  const d = data;
  const scenarios = d.scenarios ?? [];

  if (scenarios.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        No stress scenarios available.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header with input parameters */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-rose-50 to-red-50 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <TrendingDown size={14} className="text-red-500" />
          <h4 className="text-sm font-semibold text-gray-900">Appreciation Stress Test</h4>
          {d.all_scenarios_profitable != null && (
            <span
              className={`ml-auto text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                d.all_scenarios_profitable
                  ? 'bg-green-100 text-green-700'
                  : d.any_scenario_profitable
                    ? 'bg-yellow-100 text-yellow-700'
                    : 'bg-red-100 text-red-700'
              }`}
            >
              {d.all_scenarios_profitable
                ? 'All Profitable'
                : d.any_scenario_profitable
                  ? 'Mixed'
                  : 'All Unprofitable'}
            </span>
          )}
        </div>
        {d.purchase_price != null && (
          <p className="text-[10px] text-gray-500 mt-0.5">
            {formatCurrency(d.purchase_price)}
            {d.down_payment_pct != null && ` · ${d.down_payment_pct}% down`}
            {d.mortgage_rate != null && ` · ${d.mortgage_rate}% rate`}
          </p>
        )}
      </div>

      {/* Scenario grid */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
              <th className="px-3 py-2 text-left">Scenario</th>
              <th className="px-3 py-2 text-right">Appr.</th>
              {(scenarios[0]?.exits ?? []).map((e) => (
                <th key={e.year} className="px-3 py-2 text-right">
                  Yr {e.year}
                </th>
              ))}
              <th className="px-3 py-2 text-right">Breakeven</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {scenarios.map((s, i) => {
              const exits = s.exits ?? [];
              return (
                <tr key={i}>
                  <td className="px-3 py-1.5 font-medium text-gray-700 whitespace-nowrap">
                    {s.scenario_name || '–'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-600">
                    {s.annual_appreciation_pct != null ? `${s.annual_appreciation_pct}%` : '–'}
                  </td>
                  {exits.map((e, j) => (
                    <td
                      key={j}
                      className={`px-3 py-1.5 text-right font-medium ${
                        e.is_profitable ? 'text-green-600' : 'text-red-600'
                      }`}
                    >
                      {e.profit != null ? formatCurrency(e.profit) : '–'}
                    </td>
                  ))}
                  <td className="px-3 py-1.5 text-right text-gray-600">
                    {s.breakeven_year != null ? `Yr ${s.breakeven_year}` : 'Never'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Refi analysis */}
      {d.refi_analysis && (
        <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1.5">
            Refinance Opportunity
          </p>
          <div className="flex items-center gap-4 text-xs">
            <span className="text-gray-500">
              {d.refi_analysis.current_rate}% → {d.refi_analysis.refi_rate}%
            </span>
            {d.refi_analysis.monthly_savings != null && (
              <span className="text-green-600 font-medium flex items-center gap-0.5">
                <TrendingUp size={10} />
                Save {formatCurrency(d.refi_analysis.monthly_savings)}/mo
              </span>
            )}
          </div>
        </div>
      )}

      {/* Overall verdict */}
      <div className="px-4 py-2 border-t border-gray-100 text-xs text-gray-500 flex items-center gap-1.5">
        {d.all_scenarios_profitable ? (
          <CheckCircle2 size={10} className="text-green-500" />
        ) : (
          <AlertTriangle size={10} className="text-amber-500" />
        )}
        {d.scenario_count ?? scenarios.length} scenarios tested across{' '}
        {d.exit_years?.join(', ') ?? '–'} year exit windows
      </div>
    </div>
  );
}
