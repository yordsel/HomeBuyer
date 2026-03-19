/**
 * Single-property detail view shown inline in the sidebar.
 * Displays property header with stats, followed by stacked analysis block cards.
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
  ArrowLeft,
  Sparkles,
  RefreshCw,
} from 'lucide-react';
import { BlockRenderer } from '../chat/BlockRenderer';
import type { TrackedProperty } from '../../context/PropertyContext';
import { usePropertyContext } from '../../context/PropertyContext';
import { useBuyerContext } from '../../context/BuyerContext';
import { formatCurrency, formatNumber } from '../../lib/utils';

interface SinglePropertyViewProps {
  tracked: TrackedProperty;
  /** If in multi-property mode, show a back button to return to the list */
  onBack?: () => void;
}

export function SinglePropertyView({
  tracked,
  onBack,
}: SinglePropertyViewProps) {
  const { property, blocks } = tracked;
  const analysisBlocks = blocks.filter((b) => b.type !== 'property_detail');
  const { sendChatMessage, clearPropertyBlocks } = usePropertyContext();
  const { segment } = useBuyerContext();
  const hasAnalysis = analysisBlocks.length > 0;

  function handleRunAnalysis() {
    if (!sendChatMessage) return;
    if (hasAnalysis) {
      // Refresh: clear existing blocks, then re-run
      clearPropertyBlocks(property.address);
    }
    let prompt = `Give me a full analysis of ${property.address}.`;
    // Enrich prompt with segment-specific analysis hints
    if (segment === 'stretcher') {
      prompt += ' Include true monthly cost breakdown and rent-vs-buy comparison.';
    } else if (segment === 'first_time_buyer') {
      prompt += ' Include true monthly cost breakdown and PMI analysis.';
    } else if (segment === 'down_payment_constrained') {
      prompt += ' Include PMI cost modeling and true monthly cost breakdown.';
    } else if (segment === 'equity_trapped_upgrader') {
      prompt += ' Include rate lock penalty analysis for my existing mortgage.';
    } else if (segment === 'competitive_bidder') {
      prompt += ' Include competition assessment for this neighborhood.';
    } else if (segment === 'equity_leveraging_investor') {
      prompt += ' Include dual property strategy analysis using my existing equity.';
    } else if (segment === 'leveraged_investor') {
      prompt += ' Include appreciation stress test and rate penalty analysis.';
    } else if (segment === 'value_add_investor' || segment === 'appreciation_bettor') {
      prompt += ' Include appreciation stress test scenarios.';
    } else if (segment === 'cash_buyer') {
      prompt += ' Include appreciation stress test scenarios.';
    }
    sendChatMessage(prompt);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Back button (only in multi-property mode) */}
      {onBack && (
        <button
          onClick={onBack}
          className="flex items-center gap-1 px-3 py-2 text-[11px] font-medium text-indigo-600
                     hover:text-indigo-700 hover:bg-indigo-50/50 transition-colors border-b border-gray-100"
        >
          <ArrowLeft size={12} />
          All Properties
        </button>
      )}

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto">
        {/* Property header */}
        <div className="px-3.5 py-3.5 bg-gradient-to-b from-blue-50/80 to-transparent border-b border-gray-100">
          <div className="flex items-center gap-2">
            <Home size={14} className="text-indigo-600 shrink-0" />
            <h3 className="text-[13px] font-bold text-gray-900 leading-tight">
              {property.address}
            </h3>
          </div>
          {property.neighborhood && (
            <div className="flex items-center gap-1 mt-1 ml-[22px]">
              <MapPin size={10} className="text-gray-400 shrink-0" />
              <span className="text-[11px] text-gray-500">
                {property.neighborhood}
                {property.zip_code ? ` · ${property.zip_code}` : ''}
                {property.zoning_class ? ` · ${property.zoning_class}` : ''}
              </span>
            </div>
          )}

          {/* Stats grid */}
          <div className="grid grid-cols-3 gap-1.5 mt-3">
            {property.beds != null && (
              <MiniStat icon={Bed} label="Beds" value={String(property.beds)} />
            )}
            {property.baths != null && (
              <MiniStat icon={Bath} label="Baths" value={String(property.baths)} />
            )}
            {(property.computed_bldg_sqft != null || property.sqft != null) && (
              <MiniStat icon={Ruler} label="Sqft" value={formatNumber(property.computed_bldg_sqft ?? property.sqft)} />
            )}
            {property.lot_size_sqft != null && (
              <MiniStat icon={LayoutGrid} label="Lot" value={formatNumber(property.lot_size_sqft)} />
            )}
            {property.year_built != null && (
              <MiniStat icon={Calendar} label="Built" value={String(property.year_built)} />
            )}
            {property.last_sale_price != null && (
              <MiniStat icon={DollarSign} label="Last Sale" value={formatCurrency(property.last_sale_price)} />
            )}
          </div>

          {/* Property type */}
          {property.property_type && (
            <div className="mt-2.5 ml-[22px] flex items-center gap-1 text-[10px] text-gray-400">
              <Tag size={9} />
              {property.property_type}
              {property.last_sale_date ? ` · Sold ${property.last_sale_date}` : ''}
            </div>
          )}
        </div>

        {/* Analysis blocks + run/refresh button */}
        <div className="px-3 py-3 space-y-2.5">
          {hasAnalysis && (
            <>
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-0.5">
                Analysis ({analysisBlocks.length})
              </p>
              {analysisBlocks.map((block, i) => (
                <div key={`${block.type}-${i}`} className="[&>*]:!my-0">
                  <BlockRenderer block={block} />
                </div>
              ))}
            </>
          )}

          {/* Single action button: Run or Refresh */}
          <button
            onClick={handleRunAnalysis}
            disabled={!sendChatMessage}
            className={`w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg
                       text-[12px] font-medium transition-colors
                       disabled:opacity-40 disabled:cursor-not-allowed
                       ${
                         hasAnalysis
                           ? 'border border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300'
                           : 'bg-indigo-600 text-white hover:bg-indigo-700'
                       }`}
          >
            {hasAnalysis ? (
              <>
                <RefreshCw size={12} />
                Refresh Analysis
              </>
            ) : (
              <>
                <Sparkles size={12} />
                Run Analysis
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function MiniStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Bed;
  label: string;
  value: string;
}) {
  return (
    <div className="bg-white/80 rounded-lg px-2 py-1.5 text-center border border-gray-100">
      <p className="text-[9px] font-medium text-gray-400 uppercase tracking-wide flex items-center justify-center gap-0.5">
        <Icon size={8} />
        {label}
      </p>
      <p className="text-[12px] font-semibold text-gray-900 mt-0.5 leading-tight">
        {value}
      </p>
    </div>
  );
}
