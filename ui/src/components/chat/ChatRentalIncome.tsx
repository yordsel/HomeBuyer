/**
 * Compact rental income card for chat inline display.
 * Shows rent estimate, expenses, and key metrics.
 */
import { Home, DollarSign } from 'lucide-react';
import { formatCurrency, formatPct } from '../../lib/utils';
import type { RentalIncomeBlockData } from '../../types';

export function ChatRentalIncome({ data }: { data: RentalIncomeBlockData }) {
  const d = data;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-emerald-50 to-green-50 border-b border-gray-100 flex items-center gap-2">
        <Home size={14} className="text-emerald-600" />
        <h4 className="text-sm font-semibold text-gray-900">
          {d.scenario_name || 'Rental Income Estimate'}
        </h4>
      </div>

      {/* Key metrics grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-0 divide-x divide-gray-100">
        <MetricCell
          label="Monthly Rent"
          value={formatCurrency(d.total_monthly_rent)}
          color="text-green-700"
        />
        <MetricCell
          label="Monthly Cash Flow"
          value={formatCurrency(d.monthly_cash_flow)}
          color={(d.monthly_cash_flow ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'}
        />
        <MetricCell
          label="Cap Rate"
          value={formatPct(d.cap_rate_pct)}
        />
        <MetricCell
          label="Cash-on-Cash"
          value={formatPct(d.cash_on_cash_pct)}
        />
      </div>

      {/* Expense and mortgage summary */}
      <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100 space-y-1">
        {d.expenses && (
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-500">
              <DollarSign size={10} className="inline" /> Annual expenses
            </span>
            <span className="text-gray-700 font-medium">
              {formatCurrency(d.expenses.total_annual)}
              {d.expenses.expense_ratio_pct != null &&
                ` (${Number(d.expenses.expense_ratio_pct).toFixed(0)}%)`}
            </span>
          </div>
        )}
        {d.mortgage && (
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-500">Monthly PITI</span>
            <span className="text-gray-700 font-medium">
              {formatCurrency(d.mortgage.monthly_piti)}
              {d.mortgage.rate_30yr != null && ` @ ${Number(d.mortgage.rate_30yr).toFixed(2)}%`}
            </span>
          </div>
        )}
      </div>
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
