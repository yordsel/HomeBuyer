/**
 * Compact investment scenario comparison card for chat inline display.
 * Shows a comparison table of investment scenarios (as-is, ADU, SB9, etc.).
 */
import { PiggyBank, CheckCircle2 } from 'lucide-react';
import { formatCurrency, formatPct } from '../../lib/utils';
import type { InvestmentScenariosBlockData } from '../../types';

export function ChatInvestmentScenarios({ data }: { data: InvestmentScenariosBlockData }) {
  const d = data;
  const scenarios = d.scenarios ?? [];

  if (scenarios.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        No investment scenarios available.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-violet-50 to-purple-50 border-b border-gray-100 flex items-center gap-2">
        <PiggyBank size={14} className="text-purple-600" />
        <h4 className="text-sm font-semibold text-gray-900">Investment Scenarios</h4>
      </div>

      {/* Scenario comparison table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
              <th className="px-4 py-2 text-left">Scenario</th>
              <th className="px-3 py-2 text-right">Investment</th>
              <th className="px-3 py-2 text-right">Monthly Rent</th>
              <th className="px-3 py-2 text-right">Cash Flow</th>
              <th className="px-3 py-2 text-right">Cap Rate</th>
              <th className="px-3 py-2 text-right">CoC</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {scenarios.map((s, i) => {
              const isBest =
                d.best_scenario &&
                s.scenario_name?.toLowerCase().includes(d.best_scenario.toLowerCase());
              return (
                <tr key={i} className={isBest ? 'bg-green-50' : ''}>
                  <td className="px-4 py-2 font-medium text-gray-700 flex items-center gap-1">
                    {isBest && <CheckCircle2 size={12} className="text-green-500" />}
                    {s.scenario_name || s.scenario_type || 'Scenario'}
                    {s.development_feasible === false && (
                      <span className="text-[9px] text-red-400 ml-1">(N/A)</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500">
                    {formatCurrency(s.total_investment)}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-900">
                    {formatCurrency(s.total_monthly_rent)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-medium ${
                      (s.monthly_cash_flow ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {formatCurrency(s.monthly_cash_flow)}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-600">
                    {formatPct(s.cap_rate_pct)}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-600">
                    {formatPct(s.cash_on_cash_pct)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Recommendation */}
      {d.recommendation_notes && (
        <div className="px-4 py-2 bg-gray-50 border-t border-gray-100">
          <p className="text-[10px] text-gray-500">{d.recommendation_notes}</p>
        </div>
      )}
    </div>
  );
}
