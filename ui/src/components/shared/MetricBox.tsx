/**
 * Reusable metric display box used across card components.
 *
 * Previously duplicated as `MetricBox` in RentalIncomeCard.tsx and
 * `StatBox` in InvestmentScenarioCard.tsx.
 */

interface MetricBoxProps {
  /** Optional icon rendered above the value */
  icon?: React.ReactNode;
  /** Metric label (e.g., "Cap Rate") */
  label: string;
  /** Formatted value string (e.g., "$1,200/mo") */
  value: string;
  /** Optional subtitle below the label */
  sub?: string;
  /** Tailwind text color class for the value (default: text-gray-900) */
  valueColor?: string;
}

export function MetricBox({ icon, label, value, sub, valueColor }: MetricBoxProps) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      {icon && <div className="flex items-center justify-center gap-1 mb-1">{icon}</div>}
      <p className={`text-lg font-bold ${valueColor ?? 'text-gray-900'}`}>{value}</p>
      <p className="text-xs font-medium text-gray-500">{label}</p>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  );
}
