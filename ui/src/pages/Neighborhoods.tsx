import { useState, useEffect } from 'react';
import { Loader2, ArrowUpDown } from 'lucide-react';
import { toast } from 'sonner';
import * as api from '../lib/tauri';
import { NeighborhoodCard } from '../components/NeighborhoodCard';
import { NeighborhoodMap } from '../components/NeighborhoodMap';
import { ViewToggle, type ViewMode } from '../components/ViewToggle';
import { formatCurrency, formatPct } from '../lib/utils';
import type { NeighborhoodStats, NeighborhoodGeoJson } from '../types';

type SortKey = 'name' | 'median_price' | 'sale_count' | 'median_ppsf' | 'yoy_price_change_pct' | 'avg_year_built';
type SortDir = 'asc' | 'desc';

export function NeighborhoodsPage() {
  const [neighborhoods, setNeighborhoods] = useState<NeighborhoodStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [minSales, setMinSales] = useState(10);
  const [view, setView] = useState<ViewMode>('cards');
  const [sortKey, setSortKey] = useState<SortKey>('median_price');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [geojson, setGeojson] = useState<NeighborhoodGeoJson | null>(null);

  useEffect(() => {
    loadNeighborhoods();
  }, [minSales]);

  // Lazy-load GeoJSON only when switching to map view
  useEffect(() => {
    if (view === 'map' && !geojson) {
      api
        .getNeighborhoodGeoJson()
        .then(setGeojson)
        .catch((err) => {
          console.error('Failed to load GeoJSON:', err);
          toast.error('Failed to load neighborhood boundaries');
        });
    }
  }, [view, geojson]);

  async function loadNeighborhoods() {
    setLoading(true);
    try {
      const data = await api.getNeighborhoods(minSales, 2);
      setNeighborhoods(data);
    } catch (err) {
      toast.error('Failed to load neighborhoods');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir(key === 'name' ? 'asc' : 'desc');
    }
  }

  const sorted = [...neighborhoods].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number);
    return sortDir === 'asc' ? cmp : -cmp;
  });

  function SortHeader({ label, col }: { label: string; col: SortKey }) {
    const active = sortKey === col;
    return (
      <button
        onClick={() => handleSort(col)}
        className={`flex items-center gap-1 text-left ${
          active ? 'text-blue-600' : 'text-gray-500'
        }`}
      >
        {label}
        <ArrowUpDown size={12} className={active ? 'opacity-100' : 'opacity-40'} />
      </button>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Neighborhoods</h2>
          <p className="text-sm text-gray-500 mt-1">
            Berkeley neighborhoods ranked by median sale price (last 2 years).
          </p>
        </div>
        <div className="flex items-center gap-3">
          <ViewToggle view={view} onChange={setView} />
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500">Min sales:</label>
            <select
              value={minSales}
              onChange={(e) => setMinSales(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value={5}>5+</option>
              <option value={10}>10+</option>
              <option value={20}>20+</option>
              <option value={50}>50+</option>
            </select>
          </div>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={32} className="animate-spin text-blue-500" />
        </div>
      ) : neighborhoods.length === 0 ? (
        <p className="text-center text-gray-500 py-12">
          No neighborhoods with {minSales}+ sales found.
        </p>
      ) : view === 'cards' ? (
        /* ---- Card View ---- */
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {sorted.map((stats) => (
            <NeighborhoodCard key={stats.name} stats={stats} />
          ))}
        </div>
      ) : view === 'table' ? (
        /* ---- Table View ---- */
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-xs font-medium uppercase tracking-wide">
                  <th className="px-6 py-3 text-left">
                    <SortHeader label="Neighborhood" col="name" />
                  </th>
                  <th className="px-4 py-3 text-right">
                    <SortHeader label="Median Price" col="median_price" />
                  </th>
                  <th className="px-4 py-3 text-right">
                    <SortHeader label="YoY Change" col="yoy_price_change_pct" />
                  </th>
                  <th className="px-4 py-3 text-right">
                    <SortHeader label="$/sqft" col="median_ppsf" />
                  </th>
                  <th className="px-4 py-3 text-right">
                    <SortHeader label="Sales" col="sale_count" />
                  </th>
                  <th className="px-4 py-3 text-right">
                    <SortHeader label="Avg Built" col="avg_year_built" />
                  </th>
                  <th className="px-4 py-3 text-right">Lot Size</th>
                  <th className="px-4 py-3 text-left">Zone</th>
                  <th className="px-4 py-3 text-left">Property Types</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {sorted.map((n) => {
                  const yoy = n.yoy_price_change_pct;
                  const yoyColor =
                    yoy == null ? 'text-gray-400' : yoy > 0 ? 'text-green-600' : 'text-red-600';
                  return (
                    <tr key={n.name} className="hover:bg-gray-50">
                      <td className="px-6 py-3 font-medium text-gray-900">{n.name}</td>
                      <td className="px-4 py-3 text-right text-gray-700 font-medium">
                        {formatCurrency(n.median_price)}
                      </td>
                      <td className={`px-4 py-3 text-right font-medium ${yoyColor}`}>
                        {formatPct(yoy, true)}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">
                        {n.median_ppsf != null ? `$${Math.round(n.median_ppsf)}` : '—'}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">{n.sale_count}</td>
                      <td className="px-4 py-3 text-right text-gray-600">
                        {n.avg_year_built != null ? Math.round(n.avg_year_built) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">
                        {n.median_lot_size ? `${(n.median_lot_size / 1000).toFixed(1)}K` : '—'}
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-xs">
                        {n.dominant_zoning?.length > 0 ? n.dominant_zoning.join(', ') : '—'}
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-xs">
                        {Object.entries(n.property_type_breakdown || {})
                          .slice(0, 2)
                          .map(([type, pct]) =>
                            `${type.replace('Single Family Residential', 'SFR').replace('Condo/Co-op', 'Condo').replace('Multi-Family (2-4 Unit)', 'Multi 2-4').replace('Multi-Family (5+ Unit)', 'Multi 5+')}: ${pct}%`
                          )
                          .join(', ') || '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* ---- Map View ---- */
        <NeighborhoodMap neighborhoods={sorted} geojson={geojson} />
      )}
    </div>
  );
}
