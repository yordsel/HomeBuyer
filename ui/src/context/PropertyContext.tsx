import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import type { ResponseBlock, WorkingSetMeta, WorkingSetProperty } from '../types';

export interface DevelopmentSummary {
  adu_eligible?: boolean;
  sb9_eligible?: boolean;
  effective_max_units?: number;
  middle_housing_eligible?: boolean;
}

export interface PropertyContextData {
  latitude: number;
  longitude: number;
  address: string;
  neighborhood?: string;
  zip_code?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  computed_bldg_sqft?: number;
  lot_size_sqft?: number;
  data_notes?: string;
  year_built?: number;
  property_type?: string;
  zoning_class?: string;
  last_sale_price?: number;
  last_sale_date?: string;
  /** Pre-computed predicted price from search results. */
  predicted_price?: number;
  /** Confidence score for the predicted price. */
  prediction_confidence?: number;
  /** Summary development potential from search results. */
  development_summary?: DevelopmentSummary;
  /** Granular property type: sfr, condo, duplex, etc. */
  property_category?: string;
  /** Whether this is a lot or unit record. */
  record_type?: string;
}

/** A property discussed in the conversation, with any associated analysis blocks. */
export interface TrackedProperty {
  property: PropertyContextData;
  /** Response blocks associated with this property (predictions, comps, etc.) */
  blocks: ResponseBlock[];
  /** Timestamp when first mentioned */
  addedAt: number;
  /** Timestamp of last update */
  updatedAt: number;
  /** Whether the user has drilled into this property with per-property tools. */
  isDiscussed?: boolean;
}

/** Convert a WorkingSetProperty (from server) to PropertyContextData for the sidebar. */
export function workingSetPropertyToContextData(
  wsp: WorkingSetProperty,
): PropertyContextData {
  return {
    latitude: wsp.latitude ?? 0,
    longitude: wsp.longitude ?? 0,
    address: wsp.address ?? '',
    neighborhood: wsp.neighborhood ?? undefined,
    beds: wsp.beds ?? undefined,
    baths: wsp.baths ?? undefined,
    sqft: wsp.sqft ?? undefined,
    lot_size_sqft: wsp.lot_size_sqft ?? undefined,
    year_built: wsp.year_built ?? undefined,
    property_type: wsp.property_type ?? undefined,
    zoning_class: wsp.zoning_class ?? undefined,
    last_sale_price: wsp.last_sale_price ?? undefined,
    property_category: wsp.property_category ?? undefined,
    record_type: wsp.record_type ?? undefined,
  };
}

interface PropertyContextValue {
  /** Full active property for the chat-first UX. */
  activeProperty: PropertyContextData | null;
  setActiveProperty: (data: PropertyContextData | null) => void;
  /** Property set by Predict page, consumed by Potential page for cross-page navigation. */
  lastProperty: PropertyContextData | null;
  setLastProperty: (data: PropertyContextData | null) => void;

  /** All properties discussed in the current conversation. */
  trackedProperties: TrackedProperty[];
  /** Add or update a property in the tracked list with optional blocks. */
  trackProperty: (
    property: PropertyContextData,
    blocks?: ResponseBlock[],
  ) => void;
  /** Replace sidebar contents with server-provided sample + discussed lists. */
  setTrackedFromServer: (
    sample: WorkingSetProperty[],
    discussed: WorkingSetProperty[],
  ) => void;
  /** Append blocks to an already-tracked property (matched by address). */
  addBlocksToProperty: (address: string, blocks: ResponseBlock[]) => void;
  /** Clear all analysis blocks for a specific property (for refresh). */
  clearPropertyBlocks: (address: string) => void;
  /** Clear all tracked properties (e.g., new conversation). */
  clearTrackedProperties: () => void;
  /** Send a message to the chat (registered by Chat.tsx). */
  sendChatMessage: ((message: string) => void) | null;
  setSendChatMessage: (fn: ((message: string) => void) | null) => void;
  /** Backend working set metadata (count, descriptor, session_id). */
  workingSetMeta: WorkingSetMeta | null;
  setWorkingSetMeta: (meta: WorkingSetMeta | null) => void;
}

const PropertyContext = createContext<PropertyContextValue>({
  activeProperty: null,
  setActiveProperty: () => {},
  lastProperty: null,
  setLastProperty: () => {},
  trackedProperties: [],
  trackProperty: () => {},
  setTrackedFromServer: () => {},
  addBlocksToProperty: () => {},
  clearPropertyBlocks: () => {},
  clearTrackedProperties: () => {},
  sendChatMessage: null,
  setSendChatMessage: () => {},
  workingSetMeta: null,
  setWorkingSetMeta: () => {},
});

export function PropertyProvider({ children }: { children: ReactNode }) {
  const [activeProperty, setActiveProperty] =
    useState<PropertyContextData | null>(null);
  const [lastProperty, setLastProperty] =
    useState<PropertyContextData | null>(null);
  const [trackedProperties, setTrackedProperties] = useState<
    TrackedProperty[]
  >([]);
  const [sendChatMessage, setSendChatMessageRaw] = useState<
    ((message: string) => void) | null
  >(null);
  const [workingSetMeta, setWorkingSetMeta] = useState<WorkingSetMeta | null>(
    null,
  );

  // Wrap in a stable setter that accepts the function itself (not a state updater)
  const setSendChatMessage = useCallback(
    (fn: ((message: string) => void) | null) => {
      setSendChatMessageRaw(() => fn);
    },
    [],
  );

  const trackProperty = useCallback(
    (property: PropertyContextData, blocks?: ResponseBlock[]) => {
      setTrackedProperties((prev) => {
        const existing = prev.find(
          (t) =>
            t.property.address === property.address ||
            (t.property.latitude === property.latitude &&
              t.property.longitude === property.longitude),
        );
        if (existing) {
          // Update existing entry — merge property data and append blocks
          return prev.map((t) =>
            t === existing
              ? {
                  ...t,
                  property: { ...t.property, ...property },
                  blocks: blocks
                    ? [...t.blocks, ...blocks]
                    : t.blocks,
                  updatedAt: Date.now(),
                }
              : t,
          );
        }
        // Add new tracked property
        return [
          ...prev,
          {
            property,
            blocks: blocks ?? [],
            addedAt: Date.now(),
            updatedAt: Date.now(),
          },
        ];
      });
    },
    [],
  );

  /** Replace sidebar contents with server-provided sample + discussed lists.
   *  Preserves existing blocks for properties that are already tracked.
   *  Skips entries with empty addresses (backend can emit address="" defaults).
   *  Preserves locally-tracked properties (with blocks) not in server lists. */
  const setTrackedFromServer = useCallback(
    (sample: WorkingSetProperty[], discussed: WorkingSetProperty[]) => {
      setTrackedProperties((prev) => {
        // Build a lookup of existing tracked properties by address for block preservation
        const existingByAddress = new Map<string, TrackedProperty>();
        for (const tp of prev) {
          if (tp.property.address) {
            existingByAddress.set(tp.property.address, tp);
          }
        }

        const now = Date.now();
        const seen = new Set<string>();
        const next: TrackedProperty[] = [];

        // 1. Discussed properties first (sticky, at top)
        for (const wsp of discussed) {
          const addr = wsp.address ?? '';
          // Skip entries with empty or missing addresses
          if (!addr) continue;
          if (seen.has(addr)) continue;
          seen.add(addr);

          const existing = existingByAddress.get(addr);
          next.push({
            property: existing
              ? { ...existing.property, ...workingSetPropertyToContextData(wsp) }
              : workingSetPropertyToContextData(wsp),
            blocks: existing?.blocks ?? [],
            addedAt: existing?.addedAt ?? now,
            updatedAt: now,
            isDiscussed: true,
          });
        }

        // 2. Sample properties fill the rest
        for (const wsp of sample) {
          const addr = wsp.address ?? '';
          // Skip entries with empty or missing addresses
          if (!addr) continue;
          if (seen.has(addr)) continue;
          seen.add(addr);

          const existing = existingByAddress.get(addr);
          next.push({
            property: existing
              ? { ...existing.property, ...workingSetPropertyToContextData(wsp) }
              : workingSetPropertyToContextData(wsp),
            blocks: existing?.blocks ?? [],
            addedAt: existing?.addedAt ?? now,
            updatedAt: now,
            isDiscussed: false,
          });
        }

        // 3. Preserve locally-tracked properties that have blocks but aren't
        //    in the server lists yet (e.g., just tracked via processBlocks).
        for (const tp of prev) {
          if (tp.property.address && tp.blocks.length > 0 && !seen.has(tp.property.address)) {
            seen.add(tp.property.address);
            next.push({
              ...tp,
              updatedAt: now,
              isDiscussed: true,
            });
          }
        }

        return next;
      });
    },
    [],
  );

  const addBlocksToProperty = useCallback(
    (address: string, blocks: ResponseBlock[]) => {
      setTrackedProperties((prev) =>
        prev.map((t) =>
          t.property.address === address
            ? {
                ...t,
                blocks: [...t.blocks, ...blocks],
                updatedAt: Date.now(),
              }
            : t,
        ),
      );
    },
    [],
  );

  const clearPropertyBlocks = useCallback((address: string) => {
    setTrackedProperties((prev) =>
      prev.map((t) =>
        t.property.address === address
          ? { ...t, blocks: [], updatedAt: Date.now() }
          : t,
      ),
    );
  }, []);

  const clearTrackedProperties = useCallback(() => {
    setTrackedProperties([]);
  }, []);

  return (
    <PropertyContext.Provider
      value={{
        activeProperty,
        setActiveProperty,
        lastProperty,
        setLastProperty,
        trackedProperties,
        trackProperty,
        setTrackedFromServer,
        addBlocksToProperty,
        clearPropertyBlocks,
        clearTrackedProperties,
        sendChatMessage,
        setSendChatMessage,
        workingSetMeta,
        setWorkingSetMeta,
      }}
    >
      {children}
    </PropertyContext.Provider>
  );
}

export function usePropertyContext() {
  return useContext(PropertyContext);
}
