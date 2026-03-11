/**
 * Compact search results table for inline chat display.
 * Renders the property_search_results block from the search_properties tool.
 * Shows up to 10 properties with key stats, predicted price, and dev badges.
 * Addresses are clickable chips that open the PropertyDetailModal.
 */
import { Search, Layers } from 'lucide-react';
import { formatCurrency, formatNumber } from '../../lib/utils';
import { AddressChip } from './AddressChip';
import type { PropertySearchResultsData, SearchResultProperty } from '../../types';

const MAX_INLINE = 10;

interface ChatSearchResultsProps {
  data: PropertySearchResultsData;
  onAddressClick?: (address: string) => void;
}

export function ChatSearchResults({ data, onAddressClick }: ChatSearchResultsProps) {
  const d = data;
  const results = d.results ?? [];
  const display = results.slice(0, MAX_INLINE);

  if (results.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4 my-2 text-center text-xs text-gray-500">
        <Search size={16} className="mx-auto mb-1 text-gray-300" />
        {d.message ?? 'No properties matched your search.'}
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
            <Search size={12} className="text-gray-400" />
            Property Search Results
          </h4>
          <span className="text-[10px] text-gray-500">
            {d.total_found} found
            {d.total_matching > d.total_found && ` of ${d.total_matching} matching`}
          </span>
        </div>
        {/* Filter pills */}
        {d.filters_applied && Object.keys(d.filters_applied).length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {Object.entries(d.filters_applied).map(([key, val]) => (
              <span
                key={key}
                className="inline-flex items-center px-2 py-0.5 rounded-full bg-indigo-50 text-[9px] font-medium text-indigo-600"
              >
                {formatFilterLabel(key, val)}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] font-medium text-gray-400 uppercase tracking-wide border-b border-gray-100">
              <th className="px-4 py-2">Address</th>
              <th className="px-3 py-2">Zone</th>
              <th className="px-3 py-2 text-center">Bed/Ba</th>
              <th className="px-3 py-2 text-right">Sqft</th>
              <th className="px-3 py-2 text-right">Est. Price</th>
              <th className="px-3 py-2">Dev</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {display.map((prop, i) => (
              <SearchResultRow
                key={prop.address ?? i}
                property={prop}
                onAddressClick={onAddressClick}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      {results.length > MAX_INLINE && (
        <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 text-center">
          <p className="text-[10px] text-gray-500">
            Showing {MAX_INLINE} of {results.length} results — see the Context panel for all properties
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row component
// ---------------------------------------------------------------------------

function SearchResultRow({
  property: p,
  onAddressClick,
}: {
  property: SearchResultProperty;
  onAddressClick?: (address: string) => void;
}) {
  const dev = p.development;

  return (
    <tr
      className={`hover:bg-gray-50 ${onAddressClick ? 'cursor-pointer' : ''}`}
      onClick={onAddressClick && p.address ? () => onAddressClick(p.address) : undefined}
    >
      <td className="px-4 py-2">
        <div className="flex items-center gap-1.5">
          <div className="min-w-0">
            {onAddressClick && p.address ? (
              <AddressChip address={p.address} onClick={onAddressClick} maxLength={28} />
            ) : (
              <p className="font-medium text-gray-900 truncate max-w-[180px]">
                {p.address}
              </p>
            )}
            {p.neighborhood && (
              <p className="text-[10px] text-gray-400 truncate mt-0.5">
                {p.neighborhood}
                {p.zip_code ? ` · ${p.zip_code}` : ''}
              </p>
            )}
          </div>
        </div>
      </td>
      <td className="px-3 py-2 text-gray-500 whitespace-nowrap">
        {p.zoning_class ?? '—'}
      </td>
      <td className="px-3 py-2 text-center text-gray-500 whitespace-nowrap">
        {p.beds ?? '—'}/{p.baths ?? '—'}
      </td>
      <td className="px-3 py-2 text-right text-gray-500">
        {p.sqft ? formatNumber(p.sqft) : '—'}
      </td>
      <td className="px-3 py-2 text-right font-medium text-indigo-600">
        {p.predicted_price ? formatCurrency(p.predicted_price) : '—'}
      </td>
      <td className="px-3 py-2">
        {dev ? (
          <div className="flex items-center gap-1 flex-wrap">
            {dev.adu_eligible && (
              <DevBadge label="ADU" color="text-emerald-600 bg-emerald-50" />
            )}
            {dev.sb9_eligible && (
              <DevBadge label="SB9" color="text-blue-600 bg-blue-50" />
            )}
            {dev.middle_housing_eligible && (
              <DevBadge label="MH" color="text-purple-600 bg-purple-50" />
            )}
            {dev.effective_max_units != null && dev.effective_max_units > 1 && (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium text-amber-600 bg-amber-50">
                <Layers size={8} />
                {dev.effective_max_units}u
              </span>
            )}
          </div>
        ) : (
          <span className="text-gray-300">—</span>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function DevBadge({ label, color }: { label: string; color: string }) {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold ${color}`}>
      {label}
    </span>
  );
}

function formatFilterLabel(key: string, value: unknown): string {
  const label = key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());

  if (Array.isArray(value)) {
    return `${label}: ${value.join(', ')}`;
  }
  if (typeof value === 'boolean') {
    return value ? label : `No ${label}`;
  }
  return `${label}: ${String(value)}`;
}
