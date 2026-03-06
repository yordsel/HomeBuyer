/**
 * Compact property detail card for chat inline display.
 * Shows key property info after a lookup_property tool call.
 */
import { Home, MapPin, Ruler, Calendar, DollarSign, LayoutGrid } from 'lucide-react';
import { formatCurrency, formatNumber } from '../../lib/utils';

interface PropertyData {
  address?: string;
  neighborhood?: string;
  zip_code?: string;
  zoning_class?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  property_type?: string;
  use_description?: string;
  last_sale_price?: number;
  last_sale_date?: string;
  building_sqft?: number;
}

export function ChatPropertyCard({ data }: { data: Record<string, unknown> }) {
  const d = data as unknown as PropertyData;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden my-2">
      {/* Header */}
      <div className="px-4 py-3 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <Home size={16} className="text-indigo-600" />
          <h4 className="text-sm font-semibold text-gray-900">{d.address || 'Property Details'}</h4>
        </div>
        {d.neighborhood && (
          <div className="flex items-center gap-1 mt-0.5">
            <MapPin size={12} className="text-gray-400" />
            <span className="text-xs text-gray-500">
              {d.neighborhood}
              {d.zip_code ? ` \u2022 ${d.zip_code}` : ''}
              {d.zoning_class ? ` \u2022 ${d.zoning_class}` : ''}
            </span>
          </div>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-0 divide-x divide-gray-100">
        {d.beds != null && (
          <StatCell label="Beds" value={String(d.beds)} />
        )}
        {d.baths != null && (
          <StatCell label="Baths" value={String(d.baths)} />
        )}
        {(d.sqft != null || d.building_sqft != null) && (
          <StatCell
            label="Sqft"
            value={formatNumber(d.sqft ?? d.building_sqft)}
            icon={<Ruler size={12} />}
          />
        )}
        {d.lot_size_sqft != null && (
          <StatCell
            label="Lot"
            value={formatNumber(d.lot_size_sqft)}
            icon={<LayoutGrid size={12} />}
          />
        )}
        {d.year_built != null && (
          <StatCell
            label="Built"
            value={String(d.year_built)}
            icon={<Calendar size={12} />}
          />
        )}
        {d.last_sale_price != null && (
          <StatCell
            label="Last Sale"
            value={formatCurrency(d.last_sale_price)}
            icon={<DollarSign size={12} />}
          />
        )}
      </div>

      {/* Property type / use */}
      {(d.property_type || d.use_description) && (
        <div className="px-4 py-2 bg-gray-50 border-t border-gray-100">
          <span className="text-xs text-gray-500">
            {d.property_type || d.use_description}
            {d.last_sale_date ? ` \u2022 Last sold ${d.last_sale_date}` : ''}
          </span>
        </div>
      )}
    </div>
  );
}

function StatCell({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="px-3 py-2.5 text-center">
      <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide flex items-center justify-center gap-0.5">
        {icon}
        {label}
      </p>
      <p className="text-sm font-semibold text-gray-900 mt-0.5">{value}</p>
    </div>
  );
}
