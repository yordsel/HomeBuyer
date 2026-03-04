import { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import * as api from '../lib/tauri';
import { StatCard } from '../components/StatCard';
import { TrendChart } from '../components/TrendChart';
import { AboveListChart } from '../components/AboveListChart';
import { ViewToggle, type ViewMode } from '../components/ViewToggle';
import { formatCurrency } from '../lib/utils';
import type { MarketSnapshot, MarketSummary } from '../types';

export function MarketPage() {
  const [trend, setTrend] = useState<MarketSnapshot[]>([]);
  const [summary, setSummary] = useState<MarketSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [months, setMonths] = useState(24);
  const [view, setView] = useState<ViewMode>('cards');

  useEffect(() => {
    loadData();
  }, [months]);

  async function loadData() {
    setLoading(true);
    try {
      const [trendData, summaryData] = await Promise.all([
        api.getMarketTrend(months),
        api.getMarketSummary(),
      ]);
      setTrend(trendData);
      setSummary(summaryData);
    } catch (err) {
      toast.error('Failed to load market data');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={32} className="animate-spin text-blue-500" />
      </div>
    );
  }

  const cm = summary?.current_market;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Market Dashboard</h2>
          <p className="text-sm text-gray-500 mt-1">
            Berkeley real estate market conditions and trends.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <ViewToggle view={view} onChange={setView} showMap={false} />
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500">Period:</label>
            <select
              value={months}
              onChange={(e) => setMonths(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value={12}>12 months</option>
              <option value={24}>24 months</option>
              <option value={36}>3 years</option>
              <option value={60}>5 years</option>
            </select>
          </div>
        </div>
      </div>

      {/* Key Stats */}
      {cm && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Median Sale Price"
            value={formatCurrency(cm.median_sale_price)}
            subtitle={`Period: ${cm.period}`}
          />
          <StatCard
            label="Sale-to-List Ratio"
            value={cm.sale_to_list_ratio ? `${(cm.sale_to_list_ratio * 100).toFixed(1)}%` : '—'}
            subtitle={cm.sold_above_list_pct ? `${cm.sold_above_list_pct.toFixed(0)}% sold above list` : undefined}
            color={cm.sale_to_list_ratio && cm.sale_to_list_ratio > 1 ? 'red' : 'green'}
          />
          <StatCard
            label="30yr Mortgage Rate"
            value={cm.mortgage_rate_30yr ? `${cm.mortgage_rate_30yr.toFixed(2)}%` : '—'}
            color="blue"
          />
          <StatCard
            label="Days on Market"
            value={cm.median_days_on_market ? String(cm.median_days_on_market) : '—'}
            subtitle={cm.homes_sold_monthly ? `${cm.homes_sold_monthly} sold/month` : undefined}
          />
        </div>
      )}

      {view === 'cards' ? (
        /* ---- Charts View ---- */
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <TrendChart
              data={trend}
              dataKey="median_sale_price"
              label="Median Sale Price"
              color="#2563eb"
            />
            <TrendChart
              data={trend}
              dataKey="mortgage_rate_30yr"
              label="30yr Mortgage Rate"
              color="#dc2626"
              formatValue={(v) => `${v.toFixed(2)}%`}
              formatYAxis={(v) => `${v.toFixed(1)}%`}
            />
          </div>

          {/* Above List % — full width, key competitiveness indicator */}
          <AboveListChart data={trend} />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <TrendChart
              data={trend}
              dataKey="homes_sold"
              label="Homes Sold (Monthly)"
              color="#059669"
              formatValue={(v) => String(Math.round(v))}
              formatYAxis={(v) => String(Math.round(v))}
            />
            <TrendChart
              data={trend}
              dataKey="median_dom"
              label="Median Days on Market"
              color="#7c3aed"
              formatValue={(v) => `${Math.round(v)} days`}
              formatYAxis={(v) => `${Math.round(v)}d`}
            />
          </div>
        </>
      ) : (
        /* ---- Table View ---- */
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  <th className="px-6 py-3">Period</th>
                  <th className="px-4 py-3 text-right">Median Sale</th>
                  <th className="px-4 py-3 text-right">Median List</th>
                  <th className="px-4 py-3 text-right">Sale/List</th>
                  <th className="px-4 py-3 text-right">Above List %</th>
                  <th className="px-4 py-3 text-right">Homes Sold</th>
                  <th className="px-4 py-3 text-right">Inventory</th>
                  <th className="px-4 py-3 text-right">DOM</th>
                  <th className="px-4 py-3 text-right">30yr Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {[...trend].reverse().map((row) => (
                  <tr key={row.period} className="hover:bg-gray-50">
                    <td className="px-6 py-3 font-medium text-gray-900">{row.period}</td>
                    <td className="px-4 py-3 text-right text-gray-700">
                      {formatCurrency(row.median_sale_price)}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {formatCurrency(row.median_list_price)}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {row.sale_to_list_ratio != null
                        ? `${(row.sale_to_list_ratio * 100).toFixed(1)}%`
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {row.sold_above_list_pct != null
                        ? `${row.sold_above_list_pct.toFixed(0)}%`
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {row.homes_sold != null ? Math.round(row.homes_sold) : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {row.inventory != null ? Math.round(row.inventory) : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {row.median_dom != null ? Math.round(row.median_dom) : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {row.mortgage_rate_30yr != null
                        ? `${row.mortgage_rate_30yr.toFixed(2)}%`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Data Coverage */}
      {summary && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-2">Data Coverage</h3>
          <p className="text-xs text-gray-500">
            {summary.data_coverage.total_sales.toLocaleString()} property sales from{' '}
            {summary.data_coverage.date_range.earliest} to{' '}
            {summary.data_coverage.date_range.latest} across{' '}
            {summary.data_coverage.neighborhoods_covered} neighborhoods.
          </p>
        </div>
      )}
    </div>
  );
}
