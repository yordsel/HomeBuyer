import { ArrowRightLeft, CheckCircle2, TrendingUp } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { RentVsBuyBlockData, RentVsBuyYearlySnapshot } from '../../types';

export function ChatRentVsBuyCard({ data }: { data: RentVsBuyBlockData }) {
  const d = data;
  const years: RentVsBuyYearlySnapshot[] = d.yearly_comparison ?? [];
  const displayYears = years.filter(
    (_, i) => i === 0 || (i + 1) % 5 === 0 || i === years.length - 1,
  );

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header with input parameters */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-sky-50 to-blue-50 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <ArrowRightLeft size={14} className="text-blue-600" />
          <h4 className="text-sm font-semibold text-gray-900">Rent vs Buy</h4>
          {d.horizon_years != null && (
            <span className="text-[10px] text-gray-400 ml-auto">{d.horizon_years}-year horizon</span>
          )}
        </div>
        {d.purchase_price != null && (
          <p className="text-[10px] text-gray-500 mt-0.5">
            {formatCurrency(d.purchase_price)}
            {d.down_payment_pct != null && ` · ${d.down_payment_pct}% down`}
            {d.current_rent != null && ` · ${formatCurrency(d.current_rent)}/mo rent`}
          </p>
        )}
      </div>

      {/* Key stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-0 divide-x divide-gray-100">
        <StatCell label="Crossover Year" value={d.crossover_year != null ? `Year ${d.crossover_year}` : 'Never'} />
        <StatCell
          label="Final Buy Advantage"
          value={d.final_buy_advantage != null ? formatCurrency(d.final_buy_advantage) : '–'}
          color={
            d.final_buy_advantage != null
              ? d.final_buy_advantage >= 0
                ? 'text-green-600'
                : 'text-red-600'
              : undefined
          }
        />
        <StatCell label="Total Rent Paid" value={d.total_rent_paid != null ? formatCurrency(d.total_rent_paid) : '–'} />
        <StatCell label="Total Own Cost" value={d.total_ownership_paid != null ? formatCurrency(d.total_ownership_paid) : '–'} />
      </div>

      {/* Year-by-year table (sampled) */}
      {displayYears.length > 0 && (
        <div className="overflow-x-auto border-t border-gray-100">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
                <th className="px-3 py-2 text-left">Year</th>
                <th className="px-3 py-2 text-right">Rent (cum.)</th>
                <th className="px-3 py-2 text-right">Own (cum.)</th>
                <th className="px-3 py-2 text-right">Home Equity</th>
                <th className="px-3 py-2 text-right">Buy Adv.</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {displayYears.map((y, i) => {
                const adv = y.buy_advantage ?? 0;
                return (
                  <tr
                    key={i}
                    className={
                      d.crossover_year != null && y.year === d.crossover_year ? 'bg-green-50' : ''
                    }
                  >
                    <td className="px-3 py-1.5 font-medium text-gray-700 flex items-center gap-1">
                      {d.crossover_year != null && y.year === d.crossover_year && (
                        <CheckCircle2 size={10} className="text-green-500" />
                      )}
                      {y.year}
                    </td>
                    <td className="px-3 py-1.5 text-right text-gray-600">
                      {y.cumulative_rent != null ? formatCurrency(y.cumulative_rent) : '–'}
                    </td>
                    <td className="px-3 py-1.5 text-right text-gray-600">
                      {y.cumulative_ownership != null ? formatCurrency(y.cumulative_ownership) : '–'}
                    </td>
                    <td className="px-3 py-1.5 text-right text-gray-600">
                      {y.home_equity != null ? formatCurrency(y.home_equity) : '–'}
                    </td>
                    <td
                      className={`px-3 py-1.5 text-right font-medium ${adv >= 0 ? 'text-green-600' : 'text-red-600'}`}
                    >
                      {y.buy_advantage != null ? formatCurrency(y.buy_advantage) : '–'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Crossover note */}
      {d.crossover_description && (
        <div className="px-4 py-2 bg-gray-50 border-t border-gray-100 flex items-center gap-1.5 text-xs text-gray-500">
          <TrendingUp size={10} className="text-blue-500 shrink-0" />
          {d.crossover_description}
        </div>
      )}
    </div>
  );
}

function StatCell({
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
