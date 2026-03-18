import { useState } from 'react';
import { ArrowRightLeft, CheckCircle2, TrendingUp, Maximize2 } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import { Modal } from '../Modal';
import type { RentVsBuyBlockData, RentVsBuyYearlySnapshot } from '../../types';

export function ChatRentVsBuyCard({ data }: { data: RentVsBuyBlockData }) {
  const [showDetail, setShowDetail] = useState(false);
  const d = data;
  const years: RentVsBuyYearlySnapshot[] = d.yearly_comparison ?? [];
  const displayYears = years.filter(
    (_, i) => i === 0 || (i + 1) % 5 === 0 || i === years.length - 1,
  );

  return (
    <>
      <div
        className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2 cursor-pointer hover:border-blue-300 hover:shadow-sm transition-all group"
        onClick={() => setShowDetail(true)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setShowDetail(true); } }}
      >
        {/* Header with input parameters */}
        <div className="px-4 py-2.5 bg-gradient-to-r from-sky-50 to-blue-50 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <ArrowRightLeft size={14} className="text-blue-600" />
            <h4 className="text-sm font-semibold text-gray-900">Rent vs Buy</h4>
            <Maximize2 size={12} className="text-gray-300 group-hover:text-blue-400 transition-colors ml-auto" />
            {d.horizon_years != null && (
              <span className="text-[10px] text-gray-400">{d.horizon_years}-year horizon</span>
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
            label="Buy Advantage"
            value={d.final_buy_advantage != null ? formatCurrency(d.final_buy_advantage) : '–'}
            color={
              d.final_buy_advantage != null
                ? d.final_buy_advantage >= 0
                  ? 'text-green-600'
                  : 'text-red-600'
                : undefined
            }
          />
          <StatCell label="Rent (net)" value={
            d.total_rent_paid != null && d.opportunity_cost_of_down_payment != null
              ? formatCurrency(d.total_rent_paid - d.opportunity_cost_of_down_payment)
              : d.total_rent_paid != null ? formatCurrency(d.total_rent_paid) : '–'
          } />
          <StatCell label="Tax Benefit" value={d.total_tax_benefit != null ? formatCurrency(d.total_tax_benefit) : '–'} />
        </div>

        {/* Year-by-year table — net columns */}
        {displayYears.length > 0 && (
          <div className="overflow-x-auto border-t border-gray-100">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
                  <th className="px-3 py-2 text-left">Year</th>
                  <th className="px-3 py-2 text-right">Rent (net)</th>
                  <th className="px-3 py-2 text-right">Own (net)</th>
                  <th className="px-3 py-2 text-right">Equity</th>
                  <th className="px-3 py-2 text-right">Advantage</th>
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
                        {y.cumulative_rent_net != null ? formatCurrency(y.cumulative_rent_net) : '–'}
                      </td>
                      <td className="px-3 py-1.5 text-right text-gray-600">
                        {y.cumulative_buy_net != null ? formatCurrency(y.cumulative_buy_net) : '–'}
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

      {/* Detail modal — full year-by-year breakdown */}
      <RentVsBuyDetailModal
        open={showDetail}
        onClose={() => setShowDetail(false)}
        data={d}
        years={years}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Detail modal — all years, all columns
// ---------------------------------------------------------------------------

function RentVsBuyDetailModal({
  open,
  onClose,
  data: d,
  years,
}: {
  open: boolean;
  onClose: () => void;
  data: RentVsBuyBlockData;
  years: RentVsBuyYearlySnapshot[];
}) {
  return (
    <Modal open={open} onClose={onClose} title="Rent vs Buy — Full Breakdown" maxWidth="max-w-5xl">
      <div className="p-4 space-y-4">
        {/* Input assumptions */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          {d.purchase_price != null && (
            <Assumption label="Purchase Price" value={formatCurrency(d.purchase_price)} />
          )}
          {d.down_payment_pct != null && (
            <Assumption label="Down Payment" value={`${d.down_payment_pct}% (${d.down_payment_amount != null ? formatCurrency(d.down_payment_amount) : '–'})`} />
          )}
          {d.mortgage_rate != null && (
            <Assumption label="Mortgage Rate" value={`${d.mortgage_rate}%`} />
          )}
          {d.current_rent != null && (
            <Assumption label="Current Rent" value={`${formatCurrency(d.current_rent)}/mo`} />
          )}
          {d.annual_appreciation_pct != null && (
            <Assumption label="Home Appreciation" value={`${d.annual_appreciation_pct}%/yr`} />
          )}
          {d.annual_rent_increase_pct != null && (
            <Assumption label="Rent Increase" value={`${d.annual_rent_increase_pct}%/yr`} />
          )}
          <Assumption label="Market Return" value="7%/yr (on down payment)" />
          <Assumption label="Selling Costs" value="6% of home value" />
        </div>

        {/* Full table */}
        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="w-full text-xs">
            <thead className="bg-gray-50">
              <tr className="text-[9px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-200">
                <th className="px-2 py-2 text-left">Yr</th>
                <th className="px-2 py-2 text-right">Rent/yr</th>
                <th className="px-2 py-2 text-right">Rent (cum)</th>
                <th className="px-2 py-2 text-right">Opp. Gain</th>
                <th className="px-2 py-2 text-right font-semibold text-gray-600">Rent (net)</th>
                <th className="px-2 py-2 text-right">Own/yr</th>
                <th className="px-2 py-2 text-right">Own (cum)</th>
                <th className="px-2 py-2 text-right">Value</th>
                <th className="px-2 py-2 text-right">Equity</th>
                <th className="px-2 py-2 text-right">Sell Cost</th>
                <th className="px-2 py-2 text-right">Tax Benefit</th>
                <th className="px-2 py-2 text-right font-semibold text-gray-600">Own (net)</th>
                <th className="px-2 py-2 text-right font-semibold">Advantage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {years.map((y, i) => {
                const adv = y.buy_advantage ?? 0;
                const isCrossover = d.crossover_year != null && y.year === d.crossover_year;
                return (
                  <tr key={i} className={isCrossover ? 'bg-green-50' : i % 2 === 0 ? 'bg-white' : 'bg-gray-50/30'}>
                    <td className="px-2 py-1 font-medium text-gray-700">
                      {isCrossover && <CheckCircle2 size={9} className="text-green-500 inline mr-0.5" />}
                      {y.year}
                    </td>
                    <td className="px-2 py-1 text-right text-gray-500">{fmt(y.annual_rent)}</td>
                    <td className="px-2 py-1 text-right text-gray-500">{fmt(y.cumulative_rent)}</td>
                    <td className="px-2 py-1 text-right text-green-600">{fmt(y.opportunity_gain)}</td>
                    <td className="px-2 py-1 text-right text-gray-900 font-medium">{fmt(y.cumulative_rent_net)}</td>
                    <td className="px-2 py-1 text-right text-gray-500">{fmt(y.annual_ownership_cost)}</td>
                    <td className="px-2 py-1 text-right text-gray-500">{fmt(y.cumulative_ownership)}</td>
                    <td className="px-2 py-1 text-right text-gray-500">{fmt(y.home_value)}</td>
                    <td className="px-2 py-1 text-right text-gray-600">{fmt(y.home_equity)}</td>
                    <td className="px-2 py-1 text-right text-red-400">{fmt(y.selling_costs)}</td>
                    <td className="px-2 py-1 text-right text-green-500">{fmt(y.tax_benefit_cumulative)}</td>
                    <td className="px-2 py-1 text-right text-gray-900 font-medium">{fmt(y.cumulative_buy_net)}</td>
                    <td className={`px-2 py-1 text-right font-bold ${adv >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {fmt(y.buy_advantage)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Formula explanation */}
        <div className="text-[10px] text-gray-400 space-y-0.5 px-1">
          <p><strong>Rent (net)</strong> = Cumulative rent − Opportunity gain (down payment invested at 7%)</p>
          <p><strong>Own (net)</strong> = Down payment + Cumulative ownership costs + Selling costs − Home equity − Tax benefits</p>
          <p><strong>Buy Advantage</strong> = Rent (net) − Own (net). Positive = buying is cheaper.</p>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(n: number | undefined | null): string {
  return n != null ? formatCurrency(n) : '–';
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

function Assumption({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] text-gray-400 uppercase">{label}</p>
      <p className="text-xs font-medium text-gray-700">{value}</p>
    </div>
  );
}
