/**
 * Compact comparable sales table for chat inline display.
 * Shows up to 5 comps with address, date, price, and $/sqft.
 * Addresses are clickable chips that open the PropertyDetailModal.
 */
import { formatCurrency, formatDate } from '../../lib/utils';
import { AddressChip } from './AddressChip';
import type { CompBlockData } from '../../types';

interface ChatCompsTableProps {
  data: CompBlockData[];
  onAddressClick?: (address: string) => void;
}

export function ChatCompsTable({ data, onAddressClick }: ChatCompsTableProps) {
  const comps = Array.isArray(data) ? data : [];
  const display = comps.slice(0, 5);

  if (display.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        No comparable sales found.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50">
        <h4 className="text-xs font-semibold text-gray-700">
          Comparable Sales ({comps.length} found)
        </h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
              <th className="px-4 py-2">Address</th>
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-center">Bed/Ba</th>
              <th className="px-3 py-2 text-right">$/sqft</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {display.map((comp, i) => (
              <tr
                key={i}
                className={`hover:bg-gray-50 ${onAddressClick ? 'cursor-pointer' : ''}`}
                onClick={onAddressClick && comp.address ? () => onAddressClick(comp.address) : undefined}
              >
                <td className="px-4 py-2">
                  {onAddressClick && comp.address ? (
                    <AddressChip address={comp.address} onClick={onAddressClick} maxLength={26} />
                  ) : (
                    <span className="font-medium text-gray-900">{comp.address}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-gray-500">{formatDate(comp.sale_date)}</td>
                <td className="px-3 py-2 text-right font-medium text-gray-900">
                  {formatCurrency(comp.sale_price)}
                </td>
                <td className="px-3 py-2 text-center text-gray-500">
                  {comp.beds ?? '?'}/{comp.baths ?? '?'}
                </td>
                <td className="px-3 py-2 text-right text-gray-500">
                  {comp.price_per_sqft ? `$${Math.round(comp.price_per_sqft)}` : '\u2014'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
