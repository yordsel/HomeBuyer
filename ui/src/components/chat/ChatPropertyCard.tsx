/**
 * Compact property detail card for chat inline display.
 * Shows key property info after a lookup_property tool call.
 * The entire card is clickable — clicking opens the PropertyDetailModal.
 */
import { Home, MapPin, Ruler, Calendar, DollarSign, LayoutGrid, ExternalLink } from 'lucide-react';
import { formatCurrency, formatNumber } from '../../lib/utils';
import type { PropertyDetailBlockData } from '../../types';

interface ChatPropertyCardProps {
  data: PropertyDetailBlockData;
  onAddressClick?: (address: string) => void;
}

export function ChatPropertyCard({ data, onAddressClick }: ChatPropertyCardProps) {
  const d = data;
  const isClickable = !!onAddressClick && !!d.address;

  const handleClick = () => {
    if (isClickable) {
      onAddressClick!(d.address!);
    }
  };

  return (
    <div
      onClick={handleClick}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onKeyDown={isClickable ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleClick(); } } : undefined}
      className={`bg-white rounded-lg border overflow-hidden my-2 transition-all
        ${isClickable
          ? 'border-gray-200 hover:border-indigo-300 hover:shadow-md cursor-pointer group'
          : 'border-gray-200'
        }`}
    >
      {/* Header */}
      <div className={`px-4 py-3 border-b border-gray-100 transition-colors
        ${isClickable
          ? 'bg-gradient-to-r from-blue-50 to-indigo-50 group-hover:from-indigo-50 group-hover:to-indigo-100'
          : 'bg-gradient-to-r from-blue-50 to-indigo-50'
        }`}>
        <div className="flex items-center gap-2">
          <Home size={16} className={`shrink-0 transition-colors ${isClickable ? 'text-indigo-600 group-hover:text-indigo-700' : 'text-indigo-600'}`} />
          <h4 className={`text-sm font-semibold flex-1 transition-colors ${isClickable ? 'text-gray-900 group-hover:text-indigo-700' : 'text-gray-900'}`}>
            {d.address || 'Property Details'}
          </h4>
          {isClickable && (
            <ExternalLink size={14} className="text-gray-400 group-hover:text-indigo-500 transition-colors shrink-0" />
          )}
        </div>
        {d.neighborhood && (
          <div className="flex items-center gap-1 mt-0.5 ml-6">
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

      {/* Property type / use + click hint */}
      {(d.property_type || d.use_description || isClickable) && (
        <div className="px-4 py-2 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
          <span className="text-xs text-gray-500">
            {d.property_type || d.use_description || ''}
            {d.last_sale_date ? ` \u2022 Last sold ${d.last_sale_date}` : ''}
          </span>
          {isClickable && (
            <span className="text-[10px] text-gray-400 group-hover:text-indigo-500 transition-colors">
              Click for details
            </span>
          )}
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
