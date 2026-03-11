/**
 * Modal showing all properties in a searchable, sortable, paginated table.
 *
 * Dual-mode:
 * 1. **Server mode** — When `sessionId` is available and `workingSetCount > 0`,
 *    fetches data from `GET /api/faketor/working-set/{session_id}` with server-side
 *    pagination, sorting, and search. Shows the full backend working set.
 * 2. **Client mode** — Fallback when no session exists. Uses the frontend
 *    `TrackedProperty[]` with client-side filtering (includes analysis column).
 */
import { useState, useMemo, useEffect, useCallback } from 'react';
import {
  Search,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Filter,
  BarChart3,
  Loader2,
} from 'lucide-react';
import { Modal } from '../Modal';
import { PropertyDetailModal } from './PropertyDetailModal';
import type { TrackedProperty } from '../../context/PropertyContext';
import type { ResponseBlockType, WorkingSetProperty } from '../../types';
import { formatCurrency, formatNumber } from '../../lib/utils';
import { getWorkingSetProperties } from '../../lib/api';

interface AllPropertiesModalProps {
  open: boolean;
  onClose: () => void;
  properties: TrackedProperty[];
  /** Backend session ID for server-side data fetching. */
  sessionId: string | null;
  /** Total properties in the backend working set. */
  workingSetCount: number;
}

const PAGE_SIZE = 25;
const CLIENT_PAGE_SIZE = 10;

type SortField = 'address' | 'neighborhood' | 'beds' | 'sqft' | 'price' | 'updated';
type SortDir = 'asc' | 'desc';

/** Sort field mapping for server mode (maps UI fields to backend column names). */
const SERVER_SORT_MAP: Record<string, string> = {
  address: 'address',
  neighborhood: 'neighborhood',
  beds: 'beds',
  sqft: 'sqft',
  price: 'last_sale_price',
  updated: 'address', // fallback — server doesn't track "updated"
};

const FILTER_OPTIONS: { type: ResponseBlockType; label: string }[] = [
  { type: 'prediction_card', label: 'Has Prediction' },
  { type: 'development_potential', label: 'Has Dev Potential' },
  { type: 'comps_table', label: 'Has Comps' },
  { type: 'rental_income', label: 'Has Rental' },
  { type: 'sell_vs_hold', label: 'Has Sell/Hold' },
];

function getPredictedPrice(tracked: TrackedProperty): number | null {
  const predBlock = tracked.blocks.find((b) => b.type === 'prediction_card');
  if (predBlock && predBlock.type === 'prediction_card') {
    return predBlock.data.predicted_price ?? null;
  }
  return tracked.property.predicted_price ?? null;
}

function getBlockTypeCount(tracked: TrackedProperty): number {
  return new Set(tracked.blocks.filter((b) => b.type !== 'property_detail').map((b) => b.type)).size;
}

export function AllPropertiesModal({
  open,
  onClose,
  properties,
  sessionId,
  workingSetCount,
}: AllPropertiesModalProps) {
  const useServerMode = !!(sessionId && workingSetCount > 0);

  // Shared state
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [sortField, setSortField] = useState<SortField>(useServerMode ? 'address' : 'updated');
  const [sortDir, setSortDir] = useState<SortDir>(useServerMode ? 'asc' : 'desc');

  // Client-mode only
  const [filterType, setFilterType] = useState<ResponseBlockType | null>(null);
  const [detailProperty, setDetailProperty] = useState<TrackedProperty | null>(null);

  // Server-mode state
  const [serverData, setServerData] = useState<{
    properties: WorkingSetProperty[];
    total: number;
    totalPages: number;
    descriptor: string;
  } | null>(null);
  const [serverLoading, setServerLoading] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  // Debounced search for server mode
  const [debouncedSearch, setDebouncedSearch] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Fetch server data when params change
  const fetchServerData = useCallback(async () => {
    if (!sessionId || !useServerMode) return;
    setServerLoading(true);
    setServerError(null);
    try {
      const resp = await getWorkingSetProperties({
        session_id: sessionId,
        page,
        page_size: PAGE_SIZE,
        sort_by: SERVER_SORT_MAP[sortField] ?? 'address',
        sort_dir: sortDir,
        search: debouncedSearch || undefined,
      });
      setServerData({
        properties: resp.properties,
        total: resp.total,
        totalPages: resp.total_pages,
        descriptor: resp.descriptor,
      });
    } catch (err) {
      console.error('Failed to fetch working set:', err);
      setServerError('Failed to load properties from server.');
    } finally {
      setServerLoading(false);
    }
  }, [sessionId, useServerMode, page, sortField, sortDir, debouncedSearch]);

  // Trigger fetch when modal opens or params change
  useEffect(() => {
    if (open && useServerMode) {
      fetchServerData();
    }
  }, [open, useServerMode, fetchServerData]);

  // Reset page when search/sort changes
  const handleSearch = (q: string) => {
    setSearch(q);
    setPage(0);
  };
  const handleFilter = (type: ResponseBlockType | null) => {
    setFilterType(type);
    setPage(0);
  };
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
    setPage(0);
  };

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      setSearch('');
      setPage(0);
      setFilterType(null);
      setDetailProperty(null);
      setServerError(null);
    }
  }, [open]);

  // ---------- Client-mode filtering ----------
  const clientFiltered = useMemo(() => {
    if (useServerMode) return [];
    let list = [...properties];
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (t) =>
          t.property.address.toLowerCase().includes(q) ||
          t.property.neighborhood?.toLowerCase().includes(q) ||
          t.property.zip_code?.includes(q),
      );
    }
    if (filterType) {
      list = list.filter((t) => t.blocks.some((b) => b.type === filterType));
    }
    list.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'address':
          cmp = a.property.address.localeCompare(b.property.address);
          break;
        case 'neighborhood':
          cmp = (a.property.neighborhood ?? '').localeCompare(b.property.neighborhood ?? '');
          break;
        case 'beds':
          cmp = (a.property.beds ?? 0) - (b.property.beds ?? 0);
          break;
        case 'sqft':
          cmp = (a.property.sqft ?? 0) - (b.property.sqft ?? 0);
          break;
        case 'price':
          cmp = (getPredictedPrice(a) ?? 0) - (getPredictedPrice(b) ?? 0);
          break;
        case 'updated':
          cmp = a.updatedAt - b.updatedAt;
          break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return list;
  }, [useServerMode, properties, search, filterType, sortField, sortDir]);

  const clientTotalPages = Math.max(1, Math.ceil(clientFiltered.length / CLIENT_PAGE_SIZE));
  const clientPageItems = clientFiltered.slice(page * CLIENT_PAGE_SIZE, (page + 1) * CLIENT_PAGE_SIZE);

  // Compute effective values based on mode
  const effectiveTotal = useServerMode ? (serverData?.total ?? workingSetCount) : clientFiltered.length;
  const effectiveTotalPages = useServerMode ? (serverData?.totalPages ?? 1) : clientTotalPages;
  const effectivePageSize = useServerMode ? PAGE_SIZE : CLIENT_PAGE_SIZE;

  const titleCount = useServerMode
    ? (serverData?.total ?? workingSetCount)
    : properties.length;

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={`All Properties (${titleCount.toLocaleString()})`}
        maxWidth="max-w-5xl"
      >
        <div className="p-6">
          {/* Search + filters */}
          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <div className="relative flex-1">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
              />
              <input
                type="text"
                value={search}
                onChange={(e) => handleSearch(e.target.value)}
                placeholder="Search by address, neighborhood, or zip..."
                className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg
                           focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300"
              />
            </div>
            {/* Analysis filter chips — only in client mode */}
            {!useServerMode && (
              <div className="flex items-center gap-1.5 flex-wrap">
                <Filter size={13} className="text-gray-400" />
                {FILTER_OPTIONS.map((f) => (
                  <button
                    key={f.type}
                    onClick={() => handleFilter(filterType === f.type ? null : f.type)}
                    className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors
                      ${
                        filterType === f.type
                          ? 'bg-indigo-100 text-indigo-700'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Loading indicator for server mode */}
          {useServerMode && serverLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={20} className="animate-spin text-indigo-400 mr-2" />
              <span className="text-sm text-gray-500">Loading properties...</span>
            </div>
          )}

          {/* Server error */}
          {useServerMode && serverError && !serverLoading && (
            <div className="text-center py-12 text-red-400 text-sm">
              {serverError}
              <button
                onClick={fetchServerData}
                className="ml-2 text-indigo-500 hover:text-indigo-700 underline"
              >
                Retry
              </button>
            </div>
          )}

          {/* ---- SERVER MODE TABLE ---- */}
          {useServerMode && !serverLoading && !serverError && serverData && (
            <>
              {serverData.properties.length > 0 ? (
                <div className="overflow-x-auto rounded-lg border border-gray-200">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-200">
                        <ThBtn field="address" label="Address" current={sortField} dir={sortDir} onClick={handleSort} />
                        <ThBtn field="neighborhood" label="Neighborhood" current={sortField} dir={sortDir} onClick={handleSort} />
                        <ThBtn field="beds" label="Bed/Ba" current={sortField} dir={sortDir} onClick={handleSort} />
                        <ThBtn field="sqft" label="Sqft" current={sortField} dir={sortDir} onClick={handleSort} />
                        <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          Lot Sqft
                        </th>
                        <ThBtn field="price" label="Last Sale" current={sortField} dir={sortDir} onClick={handleSort} />
                        <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          Year Built
                        </th>
                        <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          Zoning
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {serverData.properties.map((prop) => (
                        <tr
                          key={prop.id}
                          className="border-b border-gray-100 hover:bg-indigo-50/40 transition-colors"
                        >
                          <td className="px-3 py-2.5 font-medium text-gray-900 max-w-[200px] truncate">
                            {prop.address}
                          </td>
                          <td className="px-3 py-2.5 text-gray-600">
                            {prop.neighborhood ?? '—'}
                          </td>
                          <td className="px-3 py-2.5 text-gray-600 whitespace-nowrap">
                            {prop.beds ?? '—'}/{prop.baths ?? '—'}
                          </td>
                          <td className="px-3 py-2.5 text-gray-600">
                            {prop.sqft ? formatNumber(prop.sqft) : '—'}
                          </td>
                          <td className="px-3 py-2.5 text-gray-600">
                            {prop.lot_size_sqft ? formatNumber(prop.lot_size_sqft) : '—'}
                          </td>
                          <td className="px-3 py-2.5 font-medium text-indigo-600">
                            {prop.last_sale_price ? formatCurrency(prop.last_sale_price) : '—'}
                          </td>
                          <td className="px-3 py-2.5 text-gray-600">
                            {prop.year_built ?? '—'}
                          </td>
                          <td className="px-3 py-2.5 text-gray-600">
                            {prop.zoning_class ?? '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-center py-12 text-gray-400 text-sm">
                  {debouncedSearch
                    ? 'No properties match your search.'
                    : 'No properties in the working set.'}
                </div>
              )}
            </>
          )}

          {/* ---- CLIENT MODE TABLE ---- */}
          {!useServerMode && (
            <>
              {clientPageItems.length > 0 ? (
                <div className="overflow-x-auto rounded-lg border border-gray-200">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-200">
                        <ThBtn field="address" label="Address" current={sortField} dir={sortDir} onClick={handleSort} />
                        <ThBtn field="neighborhood" label="Neighborhood" current={sortField} dir={sortDir} onClick={handleSort} />
                        <ThBtn field="beds" label="Bed/Ba" current={sortField} dir={sortDir} onClick={handleSort} />
                        <ThBtn field="sqft" label="Sqft" current={sortField} dir={sortDir} onClick={handleSort} />
                        <ThBtn field="price" label="Est. Price" current={sortField} dir={sortDir} onClick={handleSort} />
                        <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          Analysis
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {clientPageItems.map((tracked) => {
                        const price = getPredictedPrice(tracked);
                        const analysisCount = getBlockTypeCount(tracked);
                        return (
                          <tr
                            key={tracked.property.address}
                            onClick={() => setDetailProperty(tracked)}
                            className="border-b border-gray-100 hover:bg-indigo-50/40 cursor-pointer transition-colors"
                          >
                            <td className="px-3 py-2.5 font-medium text-gray-900 max-w-[200px] truncate">
                              {tracked.property.address}
                            </td>
                            <td className="px-3 py-2.5 text-gray-600">
                              {tracked.property.neighborhood ?? '—'}
                            </td>
                            <td className="px-3 py-2.5 text-gray-600 whitespace-nowrap">
                              {tracked.property.beds ?? '—'}/{tracked.property.baths ?? '—'}
                            </td>
                            <td className="px-3 py-2.5 text-gray-600">
                              {tracked.property.sqft ? formatNumber(tracked.property.sqft) : '—'}
                            </td>
                            <td className="px-3 py-2.5 font-medium text-indigo-600">
                              {price ? formatCurrency(price) : '—'}
                            </td>
                            <td className="px-3 py-2.5">
                              {analysisCount > 0 ? (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 text-[10px] font-medium text-gray-600">
                                  <BarChart3 size={9} className="text-indigo-400" />
                                  {analysisCount}
                                </span>
                              ) : (
                                <span className="text-gray-300 text-xs">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-center py-12 text-gray-400 text-sm">
                  {properties.length === 0
                    ? 'No properties tracked yet. Chat about a property to add it here.'
                    : 'No properties match your search.'}
                </div>
              )}
            </>
          )}

          {/* Pagination — shared for both modes */}
          {effectiveTotalPages > 1 && !(useServerMode && serverLoading) && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-xs text-gray-500">
                Showing {page * effectivePageSize + 1}–
                {Math.min((page + 1) * effectivePageSize, effectiveTotal)} of{' '}
                {effectiveTotal.toLocaleString()}
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft size={16} />
                </button>
                <span className="text-xs text-gray-600">
                  Page {page + 1} of {effectiveTotalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(effectiveTotalPages - 1, p + 1))}
                  disabled={page >= effectiveTotalPages - 1}
                  className="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          )}
        </div>
      </Modal>

      {/* Detail modal for clicked row — client mode only */}
      <PropertyDetailModal
        open={!!detailProperty}
        onClose={() => setDetailProperty(null)}
        tracked={detailProperty}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Sortable table header button
// ---------------------------------------------------------------------------

function ThBtn({
  field,
  label,
  current,
  dir,
  onClick,
}: {
  field: SortField;
  label: string;
  current: SortField;
  dir: SortDir;
  onClick: (field: SortField) => void;
}) {
  const isActive = current === field;
  return (
    <th className="text-left px-3 py-2">
      <button
        onClick={() => onClick(field)}
        className={`text-[10px] font-semibold uppercase tracking-wider transition-colors
          ${isActive ? 'text-indigo-600' : 'text-gray-500 hover:text-gray-700'}`}
      >
        {label}
        {isActive && (
          dir === 'asc' ? (
            <ChevronUp size={10} className="inline ml-0.5" />
          ) : (
            <ChevronDown size={10} className="inline ml-0.5" />
          )
        )}
      </button>
    </th>
  );
}
