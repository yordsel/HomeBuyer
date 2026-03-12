import { useState } from 'react';
import { DollarSign, Loader2, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import * as api from '../lib/api';
import { StatCard } from '../components/StatCard';
import { formatCurrency } from '../lib/utils';
import type { AffordabilityResult } from '../types';

export function AffordPage() {
  const [budget, setBudget] = useState(8000);
  const [downPct, setDownPct] = useState(20);
  const [hoa, setHoa] = useState(0);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AffordabilityResult | null>(null);

  async function handleCalculate() {
    setLoading(true);
    try {
      const data = await api.getAffordability(budget, downPct, hoa);
      setResult(data);
    } catch (err) {
      toast.error('Calculation failed');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Affordability Calculator</h2>
        <p className="text-sm text-gray-500 mt-1">
          See what you can afford and which Berkeley neighborhoods are in range.
        </p>
      </div>

      {/* Inputs */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-5">
        {/* Monthly Budget */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Monthly Budget: <span className="text-blue-600 font-bold">{formatCurrency(budget)}</span>
          </label>
          <input
            type="range"
            min={2000}
            max={25000}
            step={500}
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>$2,000</span>
            <span>$25,000</span>
          </div>
        </div>

        {/* Down Payment */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Down Payment: <span className="text-blue-600 font-bold">{downPct}%</span>
          </label>
          <input
            type="range"
            min={5}
            max={50}
            step={5}
            value={downPct}
            onChange={(e) => setDownPct(Number(e.target.value))}
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>5%</span>
            <span>50%</span>
          </div>
        </div>

        {/* HOA */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Monthly HOA
          </label>
          <input
            type="number"
            min={0}
            step={50}
            value={hoa}
            onChange={(e) => setHoa(Number(e.target.value))}
            className="w-32 border border-gray-300 rounded-lg px-3 py-2 text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <button
          onClick={handleCalculate}
          disabled={loading}
          className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium
                     hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2 transition-colors"
        >
          {loading ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Calculating...
            </>
          ) : (
            <>
              <DollarSign size={16} />
              Calculate
            </>
          )}
        </button>
      </div>

      {/* Results */}
      {result && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="Max Affordable Price"
              value={formatCurrency(result.max_affordable_price)}
              color="blue"
            />
            <StatCard
              label="Down Payment"
              value={formatCurrency(result.down_payment_amount)}
            />
            <StatCard
              label="Loan Amount"
              value={formatCurrency(result.loan_amount)}
            />
            <StatCard
              label="30yr Rate"
              value={`${Number(result.mortgage_rate_30yr).toFixed(2)}%`}
            />
          </div>

          {result.is_jumbo_loan && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
              <AlertTriangle size={18} className="text-amber-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-amber-800">Jumbo Loan</p>
                <p className="text-sm text-amber-600 mt-0.5">
                  This exceeds the {formatCurrency(result.jumbo_threshold)} conforming loan limit.
                  Jumbo loans may have higher rates and stricter requirements.
                </p>
              </div>
            </div>
          )}

          {/* Affordable Neighborhoods */}
          {result.affordable_neighborhoods.length > 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-100">
                <h3 className="text-sm font-semibold text-gray-900">
                  Neighborhoods in Your Range
                </h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                      <th className="px-6 py-3">Neighborhood</th>
                      <th className="px-4 py-3 text-right">Recent Sales</th>
                      <th className="px-4 py-3 text-right">Avg Price</th>
                      <th className="px-4 py-3 text-right">Lowest Sale</th>
                      <th className="px-4 py-3 text-left">Types</th>
                      <th className="px-4 py-3 text-left">Zoning</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {result.affordable_neighborhoods.map((n) => (
                      <tr key={n.name} className="hover:bg-gray-50">
                        <td className="px-6 py-3 font-medium text-gray-900">{n.name}</td>
                        <td className="px-4 py-3 text-right text-gray-600">
                          {n.recent_sales_in_range}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600">
                          {formatCurrency(n.avg_price)}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600">
                          {formatCurrency(n.lowest_recent_sale)}
                        </td>
                        <td className="px-4 py-3 text-gray-600 text-xs">
                          {Object.entries(n.property_type_breakdown || {})
                            .slice(0, 2)
                            .map(([type, pct]) =>
                              `${type.replace('Single Family Residential', 'SFR').replace('Condo/Co-op', 'Condo').replace('Multi-Family (2-4 Unit)', 'Multi 2-4').replace('Multi-Family (5+ Unit)', 'Multi 5+')}: ${pct}%`
                            )
                            .join(', ') || '—'}
                        </td>
                        <td className="px-4 py-3 text-gray-600 text-xs">
                          {(n.dominant_zoning || []).join(', ') || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No neighborhoods with recent sales under {formatCurrency(result.max_affordable_price)}.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
