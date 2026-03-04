import { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import { toast } from 'sonner';
import * as api from '../lib/tauri';
import { StatCard } from '../components/StatCard';
import { formatCurrency, formatPct } from '../lib/utils';
import type { ModelInfo } from '../types';

export function ModelInfoPage() {
  const [info, setInfo] = useState<ModelInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadModelInfo();
  }, []);

  async function loadModelInfo() {
    try {
      const data = await api.getModelInfo();
      setInfo(data);
    } catch (err) {
      toast.error('Failed to load model info');
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

  if (!info) {
    return (
      <div className="text-center py-20 text-gray-500">
        No model found. Run <code className="bg-gray-100 px-1 rounded">homebuyer train</code> first.
      </div>
    );
  }

  // Prepare feature importance data (top 15)
  const featureData = Object.entries(info.feature_importances)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 15)
    .map(([name, value]) => ({
      name: name.replace(/_/g, ' '),
      importance: Math.round(value * 10000) / 100,
    }));

  const m = info.metrics;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Model Info</h2>
        <p className="text-sm text-gray-500 mt-1">
          Trained {new Date(info.trained_at).toLocaleDateString('en-US', {
            year: 'numeric', month: 'short', day: 'numeric',
          })} on {info.train_size.toLocaleString()} sales, tested on {info.test_size.toLocaleString()}.
        </p>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Mean Absolute Error"
          value={formatCurrency(m.mae)}
          color="blue"
        />
        <StatCard
          label="MAPE"
          value={formatPct(m.mape)}
          subtitle="Mean Absolute % Error"
        />
        <StatCard
          label="R-Squared"
          value={m.r2.toFixed(4)}
          subtitle="Variance explained"
        />
        <StatCard
          label="90% CI Coverage"
          value={m.interval_coverage ? formatPct(m.interval_coverage) : '—'}
          subtitle="Actual within predicted range"
          color="green"
        />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Within 10%" value={formatPct(m.within_10pct)} />
        <StatCard label="Within 20%" value={formatPct(m.within_20pct)} />
        <StatCard label="Features" value={String(info.feature_count)} />
        <StatCard label="Data Cutoff" value={info.data_cutoff_date} />
      </div>

      {/* Feature Importance Chart */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">
          Top 15 Feature Importances (%)
        </h3>
        <ResponsiveContainer width="100%" height={400}>
          <BarChart data={featureData} layout="vertical" margin={{ left: 120 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 11 }} />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 11 }}
              width={110}
            />
            <Tooltip
              formatter={(value: number) => [`${value.toFixed(2)}%`, 'Importance']}
              contentStyle={{
                borderRadius: '8px',
                border: '1px solid #e5e7eb',
                fontSize: '13px',
              }}
            />
            <Bar dataKey="importance" fill="#3b82f6" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Neighborhood Accuracy */}
      {info.neighborhood_metrics.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100">
            <h3 className="text-sm font-semibold text-gray-900">
              Per-Neighborhood Accuracy (test set)
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  <th className="px-6 py-3">Neighborhood</th>
                  <th className="px-4 py-3 text-right">Test Sales</th>
                  <th className="px-4 py-3 text-right">MAPE</th>
                  <th className="px-4 py-3 text-right">MAE</th>
                  <th className="px-4 py-3 text-right">Within 10%</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {info.neighborhood_metrics
                  .filter((n) => n.test_count >= 5)
                  .sort((a, b) => a.mape - b.mape)
                  .map((n) => (
                    <tr key={n.neighborhood} className="hover:bg-gray-50">
                      <td className="px-6 py-3 font-medium text-gray-900">{n.neighborhood}</td>
                      <td className="px-4 py-3 text-right text-gray-600">{n.test_count}</td>
                      <td className="px-4 py-3 text-right text-gray-600">{n.mape.toFixed(1)}%</td>
                      <td className="px-4 py-3 text-right text-gray-600">{formatCurrency(n.mae)}</td>
                      <td className="px-4 py-3 text-right text-gray-600">{n.within_10pct.toFixed(1)}%</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Hyperparameters */}
      {Object.keys(info.hyperparameters).length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Best Hyperparameters</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {Object.entries(info.hyperparameters).map(([key, val]) => (
              <div key={key} className="bg-gray-50 rounded-lg px-3 py-2">
                <p className="text-xs text-gray-500">{key.replace(/_/g, ' ')}</p>
                <p className="text-sm font-mono font-medium text-gray-900">{String(val)}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
