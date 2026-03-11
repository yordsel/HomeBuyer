/**
 * Compact improvement simulation card for chat inline display.
 * Shows improvement categories with cost, value impact, and ROI.
 */
import { Wrench, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { formatCurrency } from '../../lib/utils';
import type { ImprovementBlockData } from '../../types';

export function ChatImprovementSim({ data }: { data: ImprovementBlockData }) {
  const d = data;
  const categories = d.categories ?? [];

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-teal-50 to-emerald-50 border-b border-gray-100 flex items-center gap-2">
        <Wrench size={14} className="text-teal-600" />
        <h4 className="text-sm font-semibold text-gray-900">Improvement ROI</h4>
      </div>

      {/* Summary */}
      {d.current_price != null && d.improved_price != null && (
        <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between text-xs">
          <div>
            <span className="text-gray-500">Total cost: </span>
            <span className="font-medium text-gray-900">{formatCurrency(d.total_cost)}</span>
          </div>
          <div>
            <span className="text-gray-500">Value gain: </span>
            <span className="font-medium text-green-600">+{formatCurrency(d.total_delta)}</span>
          </div>
          <div>
            <span className="text-gray-500">ROI: </span>
            <span className={`font-bold ${(d.roi ?? 0) >= 1 ? 'text-green-600' : 'text-red-600'}`}>
              {d.roi != null ? `${d.roi.toFixed(1)}x` : '\u2014'}
            </span>
          </div>
        </div>
      )}

      {/* Categories table */}
      {categories.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
                <th className="px-4 py-2 text-left">Category</th>
                <th className="px-3 py-2 text-right">Cost</th>
                <th className="px-3 py-2 text-right">Value +/-</th>
                <th className="px-3 py-2 text-right">ROI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {categories.map((c, i) => (
                <tr key={i}>
                  <td className="px-4 py-2 font-medium text-gray-700 capitalize">
                    {c.category.replace(/_/g, ' ')}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500">
                    {formatCurrency(c.avg_cost)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      className={`flex items-center justify-end gap-0.5 ${
                        (c.ml_delta ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
                      }`}
                    >
                      {(c.ml_delta ?? 0) >= 0 ? (
                        <ArrowUpRight size={10} />
                      ) : (
                        <ArrowDownRight size={10} />
                      )}
                      {formatCurrency(c.ml_delta)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      className={`font-medium ${
                        (c.roi ?? 0) >= 1 ? 'text-green-600' : 'text-red-600'
                      }`}
                    >
                      {c.roi != null ? `${c.roi.toFixed(1)}x` : '\u2014'}
                    </span>
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
