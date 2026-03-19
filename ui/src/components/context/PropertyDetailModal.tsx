/**
 * Modal showing full property details and all associated analysis blocks.
 * Opens when clicking a property card in the context sidebar.
 */
import {
  Home,
  MapPin,
  Bed,
  Bath,
  Ruler,
  Calendar,
  DollarSign,
  LayoutGrid,
  Tag,
  Sparkles,
  RefreshCw,
} from 'lucide-react';
import { Modal } from '../Modal';
import { BlockRenderer } from '../chat/BlockRenderer';
import type { TrackedProperty } from '../../context/PropertyContext';
import { usePropertyContext } from '../../context/PropertyContext';
import { useBuyerContext } from '../../context/BuyerContext';
import { formatCurrency, formatNumber } from '../../lib/utils';

interface PropertyDetailModalProps {
  open: boolean;
  onClose: () => void;
  tracked: TrackedProperty | null;
}

export function PropertyDetailModal({
  open,
  onClose,
  tracked,
}: PropertyDetailModalProps) {
  const { sendChatMessage, clearPropertyBlocks } = usePropertyContext();
  const { segment } = useBuyerContext();

  if (!tracked) return null;

  const { property, blocks } = tracked;

  return (
    <Modal open={open} onClose={onClose} title={property.address} maxWidth="max-w-4xl">
      <div className="p-6 space-y-6">
        {/* Property overview section */}
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-xl p-5">
          {/* Location */}
          <div className="flex items-center gap-2 mb-4">
            <Home size={18} className="text-indigo-600" />
            <div>
              <h3 className="text-base font-bold text-gray-900">
                {property.address}
              </h3>
              {property.neighborhood && (
                <div className="flex items-center gap-1 mt-0.5">
                  <MapPin size={12} className="text-gray-400" />
                  <span className="text-sm text-gray-600">
                    {property.neighborhood}
                    {property.zip_code ? ` · ${property.zip_code}` : ''}
                    {property.zoning_class
                      ? ` · ${property.zoning_class}`
                      : ''}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
            {property.beds != null && (
              <StatTile icon={Bed} label="Beds" value={String(property.beds)} />
            )}
            {property.baths != null && (
              <StatTile
                icon={Bath}
                label="Baths"
                value={String(property.baths)}
              />
            )}
            {(property.computed_bldg_sqft != null || property.sqft != null) && (
              <StatTile
                icon={Ruler}
                label="Sqft"
                value={formatNumber(property.computed_bldg_sqft ?? property.sqft)}
              />
            )}
            {property.lot_size_sqft != null && (
              <StatTile
                icon={LayoutGrid}
                label="Lot Sqft"
                value={formatNumber(property.lot_size_sqft)}
              />
            )}
            {property.year_built != null && (
              <StatTile
                icon={Calendar}
                label="Built"
                value={String(property.year_built)}
              />
            )}
            {property.last_sale_price != null && (
              <StatTile
                icon={DollarSign}
                label="Last Sale"
                value={formatCurrency(property.last_sale_price)}
              />
            )}
          </div>

          {/* Property type */}
          {property.property_type && (
            <div className="mt-3 flex items-center gap-1.5 text-xs text-gray-500">
              <Tag size={11} />
              {property.property_type}
              {property.last_sale_date
                ? ` · Last sold ${property.last_sale_date}`
                : ''}
            </div>
          )}
        </div>

        {/* Analysis blocks — skip property_detail since the overview covers it */}
        {(() => {
          const analysisBlocks = blocks.filter(
            (b) => b.type !== 'property_detail',
          );
          if (analysisBlocks.length > 0) {
            return (
              <div>
                <h4 className="text-sm font-semibold text-gray-700 mb-3">
                  Analysis ({analysisBlocks.length})
                </h4>
                <div className="space-y-3">
                  {analysisBlocks.map((block, i) => (
                    <BlockRenderer
                      key={`${block.type}-${i}`}
                      block={block}
                    />
                  ))}
                </div>
              </div>
            );
          }
          return null;
        })()}

        {/* Run / Refresh analysis button */}
        {(() => {
          const hasAnalysis = blocks.filter((b) => b.type !== 'property_detail').length > 0;
          const analysisPrompt = getAnalysisPrompt(property.address, property.property_category, segment);
          return (
            <div className="text-center py-6">
              {!hasAnalysis && (
                <p className="text-sm text-gray-400 mb-4">No analysis yet for this property.</p>
              )}
              <button
                onClick={() => {
                  if (hasAnalysis) {
                    clearPropertyBlocks(property.address);
                  }
                  sendChatMessage?.(analysisPrompt);
                  onClose();
                }}
                disabled={!sendChatMessage}
                className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg
                           text-sm font-medium transition-colors
                           disabled:opacity-40 disabled:cursor-not-allowed
                           ${
                             hasAnalysis
                               ? 'border border-gray-300 text-gray-600 hover:bg-gray-50'
                               : 'bg-indigo-600 text-white hover:bg-indigo-700'
                           }`}
              >
                {hasAnalysis ? (
                  <>
                    <RefreshCw size={14} />
                    Refresh Analysis
                  </>
                ) : (
                  <>
                    <Sparkles size={14} />
                    Run Full Analysis
                  </>
                )}
              </button>
            </div>
          );
        })()}
      </div>
    </Modal>
  );
}

/** Build a property-type and segment-aware prompt for full analysis. */
function getAnalysisPrompt(address: string, category?: string, segment?: string): string {
  // Base prompt varies by property type
  let base: string;
  switch (category) {
    case 'condo':
    case 'coop':
    case 'townhouse':
      base =
        `Give me a full analysis of ${address} including price prediction, ` +
        `comparable unit sales, sell vs hold outlook, improvement ROI, and as-is rental income.`;
      break;
    case 'land':
      base =
        `Give me a full analysis of ${address} including price prediction, ` +
        `comparable land sales, sell vs hold outlook, and what can be built based on zoning.`;
      break;
    case 'apartment':
      base =
        `Give me a full analysis of ${address} including price prediction, ` +
        `comparable sales, sell vs hold outlook, improvement ROI, and rental income for existing units.`;
      break;
    default:
      base = `Give me a full analysis of ${address}.`;
  }

  // Enrich with segment-specific analysis requests
  const segmentExtra = _segmentAnalysisExtra(segment);
  return segmentExtra ? `${base} ${segmentExtra}` : base;
}

/** Segment-specific additions to the full analysis prompt. */
function _segmentAnalysisExtra(segment?: string): string {
  switch (segment) {
    case 'stretcher':
      return 'Include a true monthly cost breakdown and rent-vs-buy comparison.';
    case 'first_time_buyer':
      return 'Include true monthly cost breakdown and PMI analysis with timeline.';
    case 'down_payment_constrained':
      return 'Include PMI cost modeling and true monthly cost breakdown.';
    case 'equity_trapped_upgrader':
      return 'Include rate lock penalty analysis for my existing mortgage.';
    case 'competitive_bidder':
      return 'Include a competition assessment for this neighborhood and price range.';
    case 'cash_buyer':
      return 'Include appreciation stress test scenarios.';
    case 'equity_leveraging_investor':
      return 'Include a dual property strategy analysis using my existing equity.';
    case 'leveraged_investor':
      return 'Include appreciation stress test and rate penalty analysis.';
    case 'value_add_investor':
      return 'Include appreciation stress test with different renovation exit scenarios.';
    case 'appreciation_bettor':
      return 'Include appreciation stress test with multiple exit horizons.';
    default:
      return '';
  }
}

function StatTile({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Bed;
  label: string;
  value: string;
}) {
  return (
    <div className="bg-white/70 rounded-lg px-3 py-2.5 text-center">
      <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide flex items-center justify-center gap-0.5">
        <Icon size={10} />
        {label}
      </p>
      <p className="text-sm font-semibold text-gray-900 mt-0.5">{value}</p>
    </div>
  );
}
