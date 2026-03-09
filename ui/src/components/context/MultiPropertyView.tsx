/**
 * Multi-property list view for the sidebar.
 * Shows summary header (clickable → AllPropertiesModal) and
 * up to 25 most recent property cards. Click a card → single-property view.
 */
import {
  Home,
  MapPin,
  Bed,
  Bath,
  Ruler,
  ChevronRight,
  BarChart3,
  Layers,
  TrendingUp,
  Table2,
} from 'lucide-react';
import type { TrackedProperty } from '../../context/PropertyContext';
import type { ResponseBlockType } from '../../types';
import { formatCurrency, formatNumber } from '../../lib/utils';

const MAX_VISIBLE = 25;

interface MultiPropertyViewProps {
  properties: TrackedProperty[];
  activeAddress: string | undefined;
  onSelectProperty: (tracked: TrackedProperty) => void;
  onViewAll: () => void;
  /** Total properties in the backend working set (may be larger than tracked). */
  totalWorkingSetCount?: number;
}

/** Badge config for analysis types. */
const BLOCK_BADGES: {
  type: ResponseBlockType;
  icon: typeof BarChart3;
  label: string;
  color: string;
}[] = [
  { type: 'prediction_card', icon: BarChart3, label: 'Price', color: 'text-blue-500' },
  { type: 'development_potential', icon: Layers, label: 'Dev', color: 'text-emerald-500' },
  { type: 'comps_table', icon: TrendingUp, label: 'Comps', color: 'text-amber-500' },
  { type: 'sell_vs_hold', icon: TrendingUp, label: 'S/H', color: 'text-purple-500' },
  { type: 'rental_income', icon: Home, label: 'Rent', color: 'text-rose-500' },
];

export function MultiPropertyView({
  properties,
  activeAddress,
  onSelectProperty,
  onViewAll,
  totalWorkingSetCount,
}: MultiPropertyViewProps) {
  const count = properties.length;
  // Show most recent first, cap at 25
  const visible = [...properties].reverse().slice(0, MAX_VISIBLE);

  // "View Table" label hints at full working set when more exist on the server
  const hasMore = totalWorkingSetCount != null && totalWorkingSetCount > count;

  return (
    <div className="flex flex-col h-full">
      {/* Compact action bar */}
      <button
        onClick={onViewAll}
        className="flex items-center justify-between px-3.5 py-2 border-b border-gray-100
                   hover:bg-gray-50/80 transition-colors group text-left shrink-0"
      >
        <p className="text-[11px] font-medium text-gray-500">
          {count} {count === 1 ? 'property' : 'properties'}
        </p>
        <div className="flex items-center gap-1 text-[11px] text-indigo-500 group-hover:text-indigo-700 transition-colors shrink-0">
          <Table2 size={12} />
          {hasMore
            ? `View All ${totalWorkingSetCount!.toLocaleString()}`
            : 'View Table'}
        </div>
      </button>

      {/* Property list */}
      <div className="flex-1 overflow-y-auto px-2.5 py-2.5 space-y-2">
        {visible.map((tracked) => (
          <PropertyListCard
            key={tracked.property.address}
            tracked={tracked}
            isActive={activeAddress === tracked.property.address}
            onClick={() => onSelectProperty(tracked)}
          />
        ))}
        {count > MAX_VISIBLE && (
          <button
            onClick={onViewAll}
            className="w-full text-center py-2 text-[11px] text-indigo-500 hover:text-indigo-700 transition-colors"
          >
            +{(count - MAX_VISIBLE).toLocaleString()} more in sidebar — view all
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact property card for the multi-property list
// ---------------------------------------------------------------------------

function PropertyListCard({
  tracked,
  isActive,
  onClick,
}: {
  tracked: TrackedProperty;
  isActive: boolean;
  onClick: () => void;
}) {
  const { property, blocks } = tracked;
  const blockTypes = new Set(blocks.map((b) => b.type));

  const predBlock = blocks.find((b) => b.type === 'prediction_card');
  const predictedPrice = predBlock
    ? (predBlock.data as Record<string, unknown>).predicted_price as number | undefined
    : property.predicted_price;

  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-xl border transition-all duration-150
                  hover:shadow-md hover:border-indigo-200 group
                  ${
                    isActive
                      ? 'border-indigo-300 bg-indigo-50/50 shadow-sm'
                      : 'border-gray-200 bg-white'
                  }`}
    >
      <div className="px-3 py-2.5 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <Home
              size={12}
              className={isActive ? 'text-indigo-600' : 'text-gray-400'}
            />
            <p className="text-[12px] font-semibold text-gray-900 truncate">
              {property.address}
            </p>
          </div>
          {property.neighborhood && (
            <div className="flex items-center gap-1 mt-0.5 ml-[18px]">
              <MapPin size={9} className="text-gray-400 shrink-0" />
              <span className="text-[10px] text-gray-500 truncate">
                {property.neighborhood}
                {property.zip_code ? ` · ${property.zip_code}` : ''}
              </span>
            </div>
          )}
        </div>
        <ChevronRight
          size={12}
          className="text-gray-300 group-hover:text-indigo-400 transition-colors shrink-0 mt-1"
        />
      </div>

      {/* Compact stats + price row */}
      <div className="px-3 pb-2 flex items-center gap-2.5 text-[10px] text-gray-500">
        {property.beds != null && (
          <span className="flex items-center gap-0.5">
            <Bed size={9} /> {property.beds}
          </span>
        )}
        {property.baths != null && (
          <span className="flex items-center gap-0.5">
            <Bath size={9} /> {property.baths}
          </span>
        )}
        {property.sqft != null && (
          <span className="flex items-center gap-0.5">
            <Ruler size={9} /> {formatNumber(property.sqft)}
          </span>
        )}
        {predictedPrice != null && (
          <span className="ml-auto text-[11px] font-medium text-indigo-600">
            {formatCurrency(predictedPrice)}
          </span>
        )}
      </div>

      {/* Analysis badges + development summary fallback */}
      {(blockTypes.size > 0 || property.development_summary) && (
        <div className="px-3 pb-2.5 flex items-center gap-1 flex-wrap">
          {BLOCK_BADGES.filter((b) => blockTypes.has(b.type)).map((badge) => {
            const Icon = badge.icon;
            return (
              <span
                key={badge.type}
                className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-gray-50 text-[9px] font-medium text-gray-500"
              >
                <Icon size={8} className={badge.color} />
                {badge.label}
              </span>
            );
          })}
          {/* Show dev summary badges from search results when no full dev block */}
          {!blockTypes.has('development_potential') &&
            property.development_summary && (
              <>
                {property.development_summary.adu_eligible && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-emerald-50 text-[9px] font-semibold text-emerald-600">
                    ADU
                  </span>
                )}
                {property.development_summary.sb9_eligible && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-blue-50 text-[9px] font-semibold text-blue-600">
                    SB9
                  </span>
                )}
              </>
            )}
        </div>
      )}
    </button>
  );
}
