import { Shield, Clock, CheckCircle2, AlertTriangle } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { PmiModelBlockData } from '../../types';

export function ChatPmiModelCard({ data }: { data: PmiModelBlockData }) {
  const d = data;

  if (!d.pmi_applicable) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
        <div className="px-4 py-2.5 bg-gradient-to-r from-green-50 to-emerald-50 border-b border-gray-100 flex items-center gap-2">
          <Shield size={14} className="text-green-600" />
          <h4 className="text-sm font-semibold text-gray-900">PMI Analysis</h4>
        </div>
        <div className="px-4 py-3 text-xs text-gray-600 flex items-center gap-1.5">
          <CheckCircle2 size={12} className="text-green-500" />
          {d.no_pmi_note || 'No PMI required — down payment is 20% or more.'}
        </div>
      </div>
    );
  }

  const brackets = d.ltv_brackets ?? [];
  const wait = d.wait_analysis;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-amber-50 to-yellow-50 border-b border-gray-100 flex items-center gap-2">
        <Shield size={14} className="text-amber-600" />
        <h4 className="text-sm font-semibold text-gray-900">PMI Analysis</h4>
        {d.total_pmi_cost != null && (
          <span className="ml-auto text-sm font-bold text-amber-700">
            {formatCurrency(d.total_pmi_cost)} total
          </span>
        )}
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-0 divide-x divide-gray-100">
        <MetricCell label="Monthly PMI" value={d.monthly_pmi != null ? formatCurrency(d.monthly_pmi) : '–'} />
        <MetricCell label="PMI Rate" value={d.current_pmi_rate_pct != null ? `${d.current_pmi_rate_pct}%` : '–'} />
        <MetricCell label="Initial LTV" value={d.initial_ltv_pct != null ? `${d.initial_ltv_pct}%` : '–'} />
        <MetricCell
          label="Drops Off"
          value={
            d.pmi_dropoff_years != null
              ? `${d.pmi_dropoff_years} yrs`
              : d.pmi_dropoff_month != null
                ? `${d.pmi_dropoff_month} mo`
                : '–'
          }
        />
      </div>

      {/* LTV bracket table */}
      {brackets.length > 0 && (
        <div className="overflow-x-auto border-t border-gray-100">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
                <th className="px-3 py-2 text-left">LTV Bracket</th>
                <th className="px-3 py-2 text-right">Rate</th>
                <th className="px-3 py-2 text-right">Months</th>
                <th className="px-3 py-2 text-right">Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {brackets.map((b, i) => (
                <tr key={i}>
                  <td className="px-3 py-1.5 text-gray-700 font-medium">{b.bracket || '–'}</td>
                  <td className="px-3 py-1.5 text-right text-gray-600">
                    {b.pmi_rate_pct != null ? `${b.pmi_rate_pct}%` : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-600">{b.months_in_bracket ?? '–'}</td>
                  <td className="px-3 py-1.5 text-right text-gray-900 font-medium">
                    {b.total_cost_in_bracket != null ? formatCurrency(b.total_cost_in_bracket) : '–'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Wait analysis */}
      {wait && (
        <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1.5 flex items-center gap-1">
            <Clock size={10} />
            Buy Now vs Wait {wait.wait_months} Months
          </p>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-gray-500">PMI cost if buy now</span>
              <span className="text-gray-700 font-medium">
                {wait.total_pmi_cost_buy_now != null ? formatCurrency(wait.total_pmi_cost_buy_now) : '–'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">PMI cost if wait</span>
              <span className="text-gray-700 font-medium">
                {wait.total_pmi_cost_after_wait != null ? formatCurrency(wait.total_pmi_cost_after_wait) : '–'}
              </span>
            </div>
            {wait.verdict_description && (
              <p className="mt-1 text-xs text-gray-600 flex items-center gap-1">
                {wait.verdict === 'buy_now' && <CheckCircle2 size={10} className="text-green-500" />}
                {wait.verdict === 'wait' && <AlertTriangle size={10} className="text-amber-500" />}
                {wait.verdict_description}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-3 py-3 text-center">
      <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-sm font-bold text-gray-900 mt-0.5">{value}</p>
    </div>
  );
}
