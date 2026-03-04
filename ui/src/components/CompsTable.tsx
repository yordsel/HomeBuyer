import type { ComparableProperty } from '../types';
import { formatCurrency, formatDate, truncate } from '../lib/utils';

interface CompsTableProps {
  comps: ComparableProperty[];
}

export function CompsTable({ comps }: CompsTableProps) {
  if (comps.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6 text-center text-gray-500">
        No comparable sales found.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-900">Comparable Recent Sales</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
              <th className="px-6 py-3">Address</th>
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3 text-right">Price</th>
              <th className="px-4 py-3 text-center">Beds</th>
              <th className="px-4 py-3 text-right">Sqft</th>
              <th className="px-4 py-3 text-right">$/sqft</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {comps.map((comp, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="px-6 py-3 font-medium text-gray-900">
                  {truncate(comp.address, 32)}
                </td>
                <td className="px-4 py-3 text-gray-600">{formatDate(comp.sale_date)}</td>
                <td className="px-4 py-3 text-right font-medium text-gray-900">
                  {formatCurrency(comp.sale_price)}
                </td>
                <td className="px-4 py-3 text-center text-gray-600">
                  {comp.beds ?? '—'}
                </td>
                <td className="px-4 py-3 text-right text-gray-600">
                  {comp.sqft?.toLocaleString() ?? '—'}
                </td>
                <td className="px-4 py-3 text-right text-gray-600">
                  {comp.price_per_sqft ? `$${Math.round(comp.price_per_sqft)}` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
