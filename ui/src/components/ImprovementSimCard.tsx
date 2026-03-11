import { useState, useEffect } from 'react';
import {
  TrendingUp,
  Loader2,
  AlertTriangle,
  ArrowUpRight,
  ArrowDownRight,
  CheckCircle2,
  RefreshCw,
} from 'lucide-react';
import * as api from '../lib/api';
import { formatCurrency } from '../lib/utils';
import type { ImprovementSimResponse, ImprovementSimCategory } from '../types';

interface ImprovementSimCardProps {
  latitude: number;
  longitude: number;
  address?: string;
  neighborhood?: string;
  zip_code?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  property_type?: string;
}

export function ImprovementSimCard(props: ImprovementSimCardProps) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ImprovementSimResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchSimulation();
  }, [props.latitude, props.longitude, props.address, props.neighborhood, props.zip_code, props.beds, props.baths, props.sqft, props.lot_size_sqft, props.year_built, props.property_type]);

  async function fetchSimulation() {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getImprovementSimulation({
        latitude: props.latitude,
        longitude: props.longitude,
        address: props.address,
        neighborhood: props.neighborhood,
        zip_code: props.zip_code,
        beds: props.beds,
        baths: props.baths,
        sqft: props.sqft,
        lot_size_sqft: props.lot_size_sqft,
        year_built: props.year_built,
        property_type: props.property_type,
      });
      if (resp.error) {
        setError(resp.error);
      } else {
        setData(resp);
        // Pre-select improvements with positive ROI
        const positive = new Set(
          resp.categories
            .filter((c) => c.ml_predicted_delta > 0)
            .map((c) => c.category),
        );
        setSelected(positive);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function toggleCategory(cat: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

  // Compute selected totals
  const selectedCategories = data?.categories.filter((c) => selected.has(c.category)) ?? [];
  const selectedCost = selectedCategories.reduce((s, c) => s + c.avg_permit_cost, 0);
  const selectedDelta = selectedCategories.reduce((s, c) => s + c.ml_predicted_delta, 0);
  const selectedRoi = selectedCost > 0 ? selectedDelta / selectedCost : 0;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <TrendingUp size={18} className="text-indigo-500" />
          <h3 className="font-semibold text-gray-900">Improvement Recommendations</h3>
        </div>
        {data && !loading && (
          <button
            onClick={fetchSimulation}
            className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
          >
            <RefreshCw size={12} />
            Refresh
          </button>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-5 h-5 animate-spin text-indigo-400 mr-2" />
          <span className="text-sm text-gray-500">Simulating improvements...</span>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="flex items-start gap-2 text-sm">
          <AlertTriangle size={16} className="text-amber-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-gray-700">{error}</p>
            <button
              onClick={fetchSimulation}
              className="text-xs text-blue-600 hover:underline mt-1"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {/* Results */}
      {data && !loading && !error && (
        <div className="space-y-4">
          {/* Summary bar */}
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide">Current Value</p>
                <p className="text-lg font-bold text-gray-900">{formatCurrency(data.current_price)}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide">Selected Cost</p>
                <p className="text-lg font-bold text-gray-900">{formatCurrency(selectedCost)}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide">Predicted Gain</p>
                <p className={`text-lg font-bold ${selectedDelta > 0 ? 'text-green-600' : selectedDelta < 0 ? 'text-red-600' : 'text-gray-600'}`}>
                  {selectedDelta >= 0 ? '+' : ''}{formatCurrency(selectedDelta)}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide">ROI</p>
                <p className={`text-lg font-bold ${selectedRoi > 1 ? 'text-green-600' : selectedRoi > 0 ? 'text-amber-600' : 'text-red-600'}`}>
                  {selectedRoi.toFixed(1)}x
                </p>
                <p className="text-xs text-gray-400">
                  {selectedRoi > 1 ? 'Net positive' : selectedRoi > 0 ? 'Partial recovery' : 'Net loss'}
                </p>
              </div>
            </div>
          </div>

          {/* Category table with checkboxes */}
          <div>
            <p className="text-xs text-gray-500 mb-2">
              Select improvements to see combined effect on predicted value:
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase w-8"></th>
                    <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase">Category</th>
                    <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase">Avg Cost</th>
                    <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase">Value Impact</th>
                    <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase">ROI</th>
                    <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase">Market Data</th>
                  </tr>
                </thead>
                <tbody>
                  {data.categories.map((cat) => (
                    <CategoryRow
                      key={cat.category}
                      cat={cat}
                      checked={selected.has(cat.category)}
                      onToggle={() => toggleCategory(cat.category)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Caveats */}
          <div className="border-t border-gray-100 pt-3 space-y-1">
            <p className="text-xs text-gray-500 font-medium">How this works</p>
            <p className="text-xs text-gray-400">
              <strong className="text-gray-500">Value Impact</strong> — predicted price change from the ML model
              when simulating this improvement (modifying permit count, recency, and investment features). This is
              property-specific, not a market average.
            </p>
            <p className="text-xs text-gray-400">
              <strong className="text-gray-500">Market Data</strong> — correlation-based $/sqft premium from
              properties with similar permits vs. city-wide average. Not causation — reflects market preferences
              and confounding factors.
            </p>
            <p className="text-xs text-gray-400">
              <strong className="text-gray-500">Avg Cost</strong> — average permitted job value from Berkeley
              building permits. Actual costs vary significantly based on scope, contractor, and materials.
            </p>
            <p className="text-xs text-amber-600 mt-2">
              Individual improvement deltas may not sum to the combined total due to interaction effects in the model.
              The combined simulation (summary bar) is the most accurate estimate.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function CategoryRow({
  cat,
  checked,
  onToggle,
}: {
  cat: ImprovementSimCategory;
  checked: boolean;
  onToggle: () => void;
}) {
  const deltaPositive = cat.ml_predicted_delta > 0;
  const roiGood = cat.ml_roi_ratio > 1;

  return (
    <tr
      className={`border-b border-gray-100 cursor-pointer transition-colors ${checked ? 'bg-indigo-50/50' : 'hover:bg-gray-50'}`}
      onClick={onToggle}
    >
      <td className="py-2.5">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          onClick={(e) => e.stopPropagation()}
          className="w-4 h-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
        />
      </td>
      <td className="py-2.5 font-medium text-gray-900">{cat.category}</td>
      <td className="py-2.5 text-right text-gray-700">{formatCurrency(cat.avg_permit_cost)}</td>
      <td className="py-2.5 text-right">
        <span className={`inline-flex items-center gap-0.5 font-medium ${deltaPositive ? 'text-green-600' : 'text-red-600'}`}>
          {deltaPositive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
          {deltaPositive ? '+' : ''}{formatCurrency(cat.ml_predicted_delta)}
        </span>
      </td>
      <td className="py-2.5 text-right">
        <span className={`inline-flex items-center gap-0.5 text-xs font-medium px-1.5 py-0.5 rounded ${
          roiGood ? 'bg-green-50 text-green-700' : cat.ml_roi_ratio > 0 ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-700'
        }`}>
          {roiGood && <CheckCircle2 size={10} />}
          {cat.ml_roi_ratio.toFixed(1)}x
        </span>
      </td>
      <td className="py-2.5 text-right text-xs text-gray-500">
        {cat.correlation_premium_pct != null ? (
          <span className={cat.correlation_premium_pct > 0 ? 'text-green-600' : 'text-red-600'}>
            {cat.correlation_premium_pct > 0 ? '+' : ''}{cat.correlation_premium_pct.toFixed(1)}% $/sqft
          </span>
        ) : (
          '—'
        )}
        {cat.sample_count > 0 && (
          <span className="text-gray-400 ml-1">({cat.sample_count})</span>
        )}
      </td>
    </tr>
  );
}
