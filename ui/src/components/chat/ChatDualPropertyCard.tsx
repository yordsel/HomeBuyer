import { Building2, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { DualPropertyBlockData } from '../../types';

export function ChatDualPropertyCard({ data }: { data: DualPropertyBlockData }) {
  const d = data;
  const ext = d.extraction;
  const inv = d.investment;
  const tests = d.stress_tests ?? [];

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-violet-50 to-purple-50 border-b border-gray-100 flex items-center gap-2">
        <Building2 size={14} className="text-violet-600" />
        <h4 className="text-sm font-semibold text-gray-900">Dual Property Strategy</h4>
        {d.is_cash_flow_positive != null && (
          <span
            className={`ml-auto text-[10px] font-semibold px-2 py-0.5 rounded-full ${
              d.is_cash_flow_positive
                ? 'bg-green-100 text-green-700'
                : 'bg-red-100 text-red-700'
            }`}
          >
            {d.is_cash_flow_positive ? 'Cash-Flow Positive' : 'Cash-Flow Negative'}
          </span>
        )}
      </div>

      {/* Equity extraction */}
      {ext && (
        <div className="px-4 py-3 border-b border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-2">
            Equity Extraction — {ext.method === 'heloc' ? 'HELOC' : 'Cash-Out Refi'}
          </p>
          <div className="grid grid-cols-3 gap-3 text-xs">
            <div>
              <p className="text-gray-500">Available equity</p>
              <p className="font-medium text-gray-900">
                {d.available_equity != null ? formatCurrency(d.available_equity) : '–'}
              </p>
            </div>
            <div>
              <p className="text-gray-500">Extracted</p>
              <p className="font-medium text-gray-900">
                {ext.extraction_amount != null ? formatCurrency(ext.extraction_amount) : '–'}
              </p>
            </div>
            <div>
              <p className="text-gray-500">Monthly increase</p>
              <p className="font-medium text-red-600">
                {ext.monthly_increase != null ? `+${formatCurrency(ext.monthly_increase)}` : '–'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Investment property */}
      {inv && (
        <div className="px-4 py-3 border-b border-gray-100">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-2">
            Investment Property
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div>
              <p className="text-gray-500">Price</p>
              <p className="font-medium text-gray-900">
                {inv.investment_price != null ? formatCurrency(inv.investment_price) : '–'}
              </p>
            </div>
            <div>
              <p className="text-gray-500">Gross Rent</p>
              <p className="font-medium text-gray-900">
                {inv.monthly_gross_rent != null ? formatCurrency(inv.monthly_gross_rent) : '–'}
              </p>
            </div>
            <div>
              <p className="text-gray-500">Cap Rate</p>
              <p className="font-medium text-gray-900">
                {inv.cap_rate_pct != null ? `${inv.cap_rate_pct}%` : '–'}
              </p>
            </div>
            <div>
              <p className="text-gray-500">Net Cash Flow</p>
              <p
                className={`font-medium ${(inv.monthly_net_cash_flow ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}
              >
                {inv.monthly_net_cash_flow != null ? formatCurrency(inv.monthly_net_cash_flow) : '–'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Combined result */}
      <div className="grid grid-cols-3 gap-0 divide-x divide-gray-100">
        <MetricCell
          label="Combined CF"
          value={d.combined_monthly_cash_flow != null ? formatCurrency(d.combined_monthly_cash_flow) : '–'}
          color={(d.combined_monthly_cash_flow ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'}
        />
        <MetricCell
          label="Cash-on-Cash"
          value={d.cash_on_cash_pct != null ? `${d.cash_on_cash_pct}%` : '–'}
        />
        <MetricCell
          label="Worst Case"
          value={d.worst_case_monthly != null ? formatCurrency(d.worst_case_monthly) : '–'}
          color={(d.worst_case_monthly ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'}
        />
      </div>

      {/* Stress tests */}
      {tests.length > 0 && (
        <div className="overflow-x-auto border-t border-gray-100">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
                <th className="px-3 py-2 text-left">Scenario</th>
                <th className="px-3 py-2 text-right">Monthly CF</th>
                <th className="px-3 py-2 text-right">Delta</th>
                <th className="px-3 py-2 text-center">OK?</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {tests.map((t, i) => (
                <tr key={i} className={t.scenario === d.worst_case_scenario ? 'bg-red-50' : ''}>
                  <td className="px-3 py-1.5 text-gray-700">{t.scenario}</td>
                  <td
                    className={`px-3 py-1.5 text-right font-medium ${t.is_positive ? 'text-green-600' : 'text-red-600'}`}
                  >
                    {t.monthly_cash_flow != null ? formatCurrency(t.monthly_cash_flow) : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-500">
                    {t.delta_from_base != null ? formatCurrency(t.delta_from_base) : '–'}
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    {t.is_positive ? (
                      <CheckCircle2 size={12} className="text-green-500 inline" />
                    ) : (
                      <AlertTriangle size={12} className="text-red-400 inline" />
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

function MetricCell({
  label,
  value,
  color = 'text-gray-900',
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="px-3 py-3 text-center">
      <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide">{label}</p>
      <p className={`text-sm font-bold mt-0.5 ${color}`}>{value}</p>
    </div>
  );
}
