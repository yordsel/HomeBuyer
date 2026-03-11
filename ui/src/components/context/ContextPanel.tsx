/**
 * Right-side context panel — dual-mode:
 *
 * 1. **Single property** (1 tracked) — property detail header + analysis blocks inline
 * 2. **Multi property** (2+ tracked) — summary header (clickable → table modal)
 *    + scrollable list of 25 most recent cards. Click card → single-property view.
 *
 * Collapsible to icon rail. Only rendered on the Chat page.
 */
import { useState, useEffect, useMemo } from 'react';
import {
  Layers,
  ChevronsRight,
  ChevronsLeft,
} from 'lucide-react';
import { usePropertyContext } from '../../context/PropertyContext';
import { SinglePropertyView } from './SinglePropertyView';
import { MultiPropertyView } from './MultiPropertyView';
import { AllPropertiesModal } from './AllPropertiesModal';
import type { TrackedProperty } from '../../context/PropertyContext';
import {
  getMultiPropertySummaryLines,
  getSinglePropertySummaryLine,
} from './contextSummary';

/**
 * Parse the backend working-set descriptor into a title and detail lines.
 *
 * Descriptor format (from SessionWorkingSet.get_descriptor()):
 *   PROPERTY WORKING SET: 247 properties
 *     Neighborhoods: North Berkeley (82), Elmwood (41), ...
 *     Types: Single Family Residential (180), ...
 *     Lot size: 3,200 - 18,000 sqft (median 5,600)
 *     Last sale: $450,000 - $3,200,000 (median $1,250,000)
 *     Zoning: R-1 (120), R-1A (56), ...
 */
function parseWorkingSetDescriptor(descriptor: string): {
  title: string;
  lines: string[];
} {
  const rawLines = descriptor.split('\n').map((l) => l.trim()).filter(Boolean);
  if (rawLines.length === 0) return { title: 'Working Set', lines: [] };

  // First line: "PROPERTY WORKING SET: 247 properties" → "247 Properties"
  const firstLine = rawLines[0];
  const countMatch = firstLine.match(/(\d[\d,]*)\s*properties?/i);
  const title = countMatch
    ? `${countMatch[1]} Properties`
    : firstLine.replace(/^PROPERTY WORKING SET:\s*/i, '').trim() || 'Working Set';

  // Remaining lines — prioritise the most informative ones (up to 4).
  // The backend may return: Filters applied, Filter depth, Neighborhoods,
  // Types, Categories, Record types, Lot size, Last sale, Zoning.
  // We pick the most useful subset for the compact header.
  const detailLines = rawLines.slice(1);

  // Priority order: Neighborhoods, Types, Lot size, Zoning, Filters applied
  const priority = ['Neighborhoods', 'Types', 'Lot size', 'Zoning', 'Filters applied'];
  const sorted = detailLines.sort((a, b) => {
    const ai = priority.findIndex((p) => a.startsWith(p));
    const bi = priority.findIndex((p) => b.startsWith(p));
    // Known labels sort by priority; unknown ones go last
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  return { title, lines: sorted.slice(0, 4) };
}

export function ContextPanel() {
  const {
    activeProperty,
    trackedProperties,
    workingSetMeta,
  } = usePropertyContext();

  const [collapsed, setCollapsed] = useState(false);
  const [showAll, setShowAll] = useState(false);
  // In multi-property mode, user can drill into a single property
  const [selectedProperty, setSelectedProperty] = useState<TrackedProperty | null>(null);

  const count = trackedProperties.length;
  const isSingleMode = count === 1;
  const isMultiMode = count > 1;

  // When we're viewing a specific property, keep it fresh from trackedProperties
  const liveSelected = selectedProperty
    ? trackedProperties.find(
        (t) => t.property.address === selectedProperty.property.address,
      ) ?? selectedProperty
    : null;

  // In single mode, always show the one property
  const singleProperty = isSingleMode ? trackedProperties[0] : null;

  // Compute rich header summary.
  // - Title: server working-set count when available, else client-side count.
  // - Detail lines: backend descriptor lines when available, else frontend-computed.
  // - Always includes client sidebar count when it differs from the title count.
  const headerSummary = useMemo(() => {
    if (count === 0) {
      return { title: 'Context', lines: ['No properties yet'] };
    }
    if (count === 1 && !(workingSetMeta && workingSetMeta.count > 1)) {
      const tracked = trackedProperties[0];
      return {
        title: tracked.property.address,
        lines: [getSinglePropertySummaryLine(tracked)].filter(Boolean),
      };
    }

    // Multi-property mode — prefer backend working-set count for title
    const serverCount = workingSetMeta?.count ?? 0;
    const titleCount = serverCount > 0 ? serverCount : count;
    const title = `${titleCount.toLocaleString()} Properties`;

    // Detail lines from backend descriptor or frontend fallback
    let detailLines: string[];
    if (workingSetMeta && workingSetMeta.count > 0 && workingSetMeta.descriptor) {
      const parsed = parseWorkingSetDescriptor(workingSetMeta.descriptor);
      detailLines = parsed.lines;
    } else {
      detailLines = getMultiPropertySummaryLines(trackedProperties);
    }

    // Prepend sidebar count when server has more properties than the sidebar
    if (serverCount > 0 && serverCount > count) {
      detailLines = [`${count} shown in sidebar`, ...detailLines];
    }

    return { title, lines: detailLines.slice(0, 4) };
  }, [trackedProperties, count, workingSetMeta]);

  // Reset drill-in when property count drops to 0 or 1
  useEffect(() => {
    if (count <= 1) setSelectedProperty(null);
  }, [count]);

  return (
    <>
      <aside
        className={`bg-white border-l border-gray-200 flex flex-col h-full transition-all duration-200 shrink-0 ${
          collapsed ? 'w-[44px]' : 'w-96'
        }`}
      >
        {/* Header */}
        <div className="px-3 py-4 border-b border-gray-200 flex items-center justify-between min-h-[72px]">
          {!collapsed && (
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-50 text-indigo-600 shrink-0">
                <Layers size={16} />
              </div>
              <div className="min-w-0">
                <h2 className="text-sm font-bold text-gray-900 truncate">
                  {headerSummary.title}
                </h2>
                {headerSummary.lines.map((line, i) => (
                  <p
                    key={i}
                    className="text-[10px] text-gray-500 truncate leading-tight"
                  >
                    {line}
                  </p>
                ))}
              </div>
            </div>
          )}
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors shrink-0"
            title={collapsed ? 'Expand context panel' : 'Collapse context panel'}
          >
            {collapsed ? (
              <ChevronsLeft size={16} />
            ) : (
              <ChevronsRight size={16} />
            )}
          </button>
        </div>

        {/* Content — only if expanded */}
        {!collapsed && (
          <div className="flex-1 overflow-hidden flex flex-col">
            {count === 0 && <EmptyState />}

            {/* Single property mode */}
            {isSingleMode && singleProperty && (
              <SinglePropertyView tracked={singleProperty} />
            )}

            {/* Multi property mode — list or drilled-in */}
            {isMultiMode && !liveSelected && (
              <MultiPropertyView
                properties={trackedProperties}
                activeAddress={activeProperty?.address}
                onSelectProperty={(t) => setSelectedProperty(t)}
                onViewAll={() => setShowAll(true)}
                totalWorkingSetCount={workingSetMeta?.count ?? undefined}
                filterDepth={workingSetMeta?.filter_depth ?? 0}
              />
            )}

            {/* Multi mode — drilled into a single property */}
            {isMultiMode && liveSelected && (
              <SinglePropertyView
                tracked={liveSelected}
                onBack={() => setSelectedProperty(null)}
              />
            )}
          </div>
        )}

        {/* Collapsed icon list */}
        {collapsed && count > 0 && (
          <div className="flex-1 overflow-y-auto py-3 flex flex-col items-center gap-2">
            {trackedProperties.slice(0, 8).map((tracked) => (
              <button
                key={tracked.property.address}
                onClick={() => {
                  setCollapsed(false);
                  if (count > 1) setSelectedProperty(tracked);
                }}
                title={tracked.property.address}
                className={`w-8 h-8 rounded-lg flex items-center justify-center text-[10px] font-bold transition-colors ${
                  activeProperty?.address === tracked.property.address
                    ? 'bg-indigo-100 text-indigo-700'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                {getAddressInitials(tracked.property.address)}
              </button>
            ))}
            {count > 8 && (
              <span className="text-[10px] text-gray-400">
                +{count - 8}
              </span>
            )}
          </div>
        )}
      </aside>

      {/* All-properties table modal */}
      <AllPropertiesModal
        open={showAll}
        onClose={() => setShowAll(false)}
        properties={trackedProperties}
        sessionId={workingSetMeta?.session_id ?? null}
        workingSetCount={workingSetMeta?.count ?? 0}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center py-8 px-4">
      <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center mb-3">
        <Layers size={20} className="text-gray-300" />
      </div>
      <p className="text-sm font-medium text-gray-500 mb-1">No properties yet</p>
      <p className="text-xs text-gray-400 leading-relaxed">
        Search for an address or ask Faketor about a property — it will appear here automatically.
      </p>
    </div>
  );
}

function getAddressInitials(address: string): string {
  const num = address.match(/^\d+/);
  if (num) return num[0].slice(0, 3);
  return address.slice(0, 2).toUpperCase();
}
