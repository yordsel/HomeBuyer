import { useState } from 'react';
import {
  DollarSign,
  RefreshCw,
  Home,
  TrendingUp,
  PiggyBank,
  Receipt,
} from 'lucide-react';
import { formatCurrency, formatNumber } from '../lib/utils';
import { useRentalAnalysis } from '../hooks/useRentalAnalysis';
import { MetricBox, CollapsibleSection, CardLoading, CardError } from './shared';
import type { RentalAnalysisResponse, ExpenseBreakdown } from '../types';

interface RentalIncomeCardProps {
  latitude: number;
  longitude: number;
  address?: string;
  neighborhood?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  list_price?: number;
  /** Pre-fetched rental analysis data. When provided, the card skips its own fetch. */
  rentalData?: RentalAnalysisResponse;
}

export function RentalIncomeCard(props: RentalIncomeCardProps) {
  const { data: effectiveData, loading, error, refetch } = useRentalAnalysis(props);
  const [showExpenses, setShowExpenses] = useState(false);
  const [showMortgage, setShowMortgage] = useState(false);

  // Get the as-is scenario for the summary card
  const asIs = effectiveData?.scenarios.find((s) => s.scenario_type === 'as_is') ?? null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign size={18} className="text-green-600" />
          <h3 className="font-semibold text-gray-900">Rental Income Analysis</h3>
        </div>
        {effectiveData && (
          <button
            onClick={refetch}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600"
          >
            <RefreshCw size={12} />
            Refresh
          </button>
        )}
      </div>

      {/* Body */}
      <div className="px-6 py-4">
        {loading && (
          <CardLoading message="Analyzing rental income..." spinnerColor="text-green-500" />
        )}

        {!loading && error && (
          <CardError message={error} onRetry={refetch} />
        )}

        {!loading && asIs && (
          <div className="space-y-4">
            {/* Key Metrics Row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <MetricBox
                icon={<Home size={14} className="text-green-600" />}
                label="Monthly Rent"
                value={formatCurrency(asIs.total_monthly_rent)}
                sub={`${asIs.units[0]?.estimation_method ?? ''}`}
              />
              <MetricBox
                icon={<TrendingUp size={14} className="text-blue-600" />}
                label="Cap Rate"
                value={`${asIs.cap_rate_pct}%`}
                sub="NOI / Value"
              />
              <MetricBox
                icon={<PiggyBank size={14} className="text-purple-600" />}
                label="Cash-on-Cash"
                value={`${asIs.cash_on_cash_pct}%`}
                sub="Annual return"
              />
              <MetricBox
                icon={<Receipt size={14} className="text-amber-600" />}
                label="Monthly Cash Flow"
                value={formatCurrency(asIs.monthly_cash_flow)}
                sub={asIs.monthly_cash_flow >= 0 ? 'Positive' : 'Negative'}
                valueColor={asIs.monthly_cash_flow >= 0 ? 'text-green-700' : 'text-red-600'}
              />
            </div>

            {/* Rent per unit */}
            {asIs.units.length > 0 && (
              <div className="bg-gray-50 rounded-lg p-3">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                  Rent Estimate
                </p>
                {asIs.units.map((u, i) => (
                  <div key={i} className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">
                      {u.unit_type === 'main_house' ? 'Main House' : u.unit_type} —{' '}
                      {u.beds}bd/{u.baths}ba{u.sqft ? `, ${formatNumber(u.sqft)} sqft` : ''}
                    </span>
                    <span className="font-semibold text-gray-900">
                      {formatCurrency(u.monthly_rent)}/mo
                    </span>
                  </div>
                ))}
                {asIs.units[0]?.notes && (
                  <p className="text-xs text-gray-400 mt-1">{asIs.units[0].notes}</p>
                )}
              </div>
            )}

            {/* Expense Breakdown (collapsible) */}
            <CollapsibleSection
              title="Operating Expenses"
              subtitle={`${formatCurrency(asIs.expenses.total_annual)}/yr (${asIs.expenses.expense_ratio_pct}% ratio)`}
              open={showExpenses}
              onToggle={() => setShowExpenses(!showExpenses)}
            >
              <ExpenseTable expenses={asIs.expenses} />
            </CollapsibleSection>

            {/* Mortgage Details (collapsible) */}
            <CollapsibleSection
              title="Mortgage Analysis"
              subtitle={`${formatCurrency(asIs.mortgage.monthly_piti)}/mo PITI at ${asIs.mortgage.rate_30yr}%`}
              open={showMortgage}
              onToggle={() => setShowMortgage(!showMortgage)}
            >
              <div className="space-y-1.5 text-sm">
                <Row label="Property Value" value={formatCurrency(asIs.mortgage.property_value)} />
                <Row
                  label={`Down Payment (${asIs.mortgage.down_payment_pct}%)`}
                  value={formatCurrency(asIs.mortgage.down_payment_amount)}
                />
                <Row label="Loan Amount" value={formatCurrency(asIs.mortgage.loan_amount)} />
                {asIs.mortgage.is_jumbo && (
                  <p className="text-xs text-amber-600">Jumbo loan — may have higher rate</p>
                )}
                <div className="border-t border-gray-200 pt-1.5 mt-1.5">
                  <Row label="Monthly P&I" value={formatCurrency(asIs.mortgage.monthly_pi)} />
                  <Row label="Monthly Tax" value={formatCurrency(asIs.mortgage.monthly_tax)} />
                  <Row label="Monthly Insurance" value={formatCurrency(asIs.mortgage.monthly_insurance)} />
                  <Row label="Monthly PITI" value={formatCurrency(asIs.mortgage.monthly_piti)} bold />
                </div>
              </div>
            </CollapsibleSection>

            {/* Tax Benefits */}
            <div className="bg-blue-50 rounded-lg p-3">
              <p className="text-xs font-medium text-blue-700 uppercase tracking-wide mb-1">
                Estimated Annual Tax Savings
              </p>
              <p className="text-lg font-bold text-blue-800">
                {formatCurrency(asIs.tax_benefits.estimated_tax_savings)}
              </p>
              <p className="text-xs text-blue-600 mt-0.5">
                Depreciation: {formatCurrency(asIs.tax_benefits.depreciation_annual)} | Interest
                deduction: {formatCurrency(asIs.tax_benefits.mortgage_interest_deduction)}
              </p>
            </div>

            {/* Disclaimer */}
            {effectiveData!.disclaimers.length > 0 && (
              <p className="text-xs text-gray-400 leading-relaxed">
                {effectiveData!.disclaimers[0]}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ExpenseTable({ expenses }: { expenses: ExpenseBreakdown }) {
  const items = [
    { label: 'Property Tax (1.17%)', value: expenses.property_tax },
    { label: 'Insurance (0.35%)', value: expenses.insurance },
    { label: 'Maintenance (1%)', value: expenses.maintenance },
    { label: 'Vacancy Reserve (5%)', value: expenses.vacancy_reserve },
    ...(expenses.management_fee > 0
      ? [{ label: 'Management Fee (8%)', value: expenses.management_fee }]
      : []),
    ...(expenses.hoa > 0 ? [{ label: 'HOA', value: expenses.hoa }] : []),
  ];

  return (
    <div className="space-y-1.5 text-sm">
      {items.map((item) => (
        <Row key={item.label} label={item.label} value={formatCurrency(item.value)} />
      ))}
      <div className="border-t border-gray-200 pt-1.5">
        <Row label="Total Annual Expenses" value={formatCurrency(expenses.total_annual)} bold />
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  bold,
}: {
  label: string;
  value: string;
  bold?: boolean;
}) {
  return (
    <div className="flex justify-between">
      <span className={`text-gray-600 ${bold ? 'font-medium' : ''}`}>{label}</span>
      <span className={`${bold ? 'font-semibold text-gray-900' : 'text-gray-700'}`}>{value}</span>
    </div>
  );
}

