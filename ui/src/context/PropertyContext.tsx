import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import type { ResponseBlock, WorkingSetMeta } from '../types';

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
  lot_size_sqft?: number;
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
}

interface PropertyContextValue {
  /** Full active property for the chat-first UX. */
  activeProperty: PropertyContextData | null;
  setActiveProperty: (data: PropertyContextData | null) => void;
  /** Backward-compatible alias used by FaketorFAB and legacy pages. */
  lastProperty: PropertyContextData | null;
  setLastProperty: (data: PropertyContextData | null) => void;

  /** All properties discussed in the current conversation. */
  trackedProperties: TrackedProperty[];
  /** Add or update a property in the tracked list with optional blocks. */
  trackProperty: (
    property: PropertyContextData,
    blocks?: ResponseBlock[],
  ) => void;
  /** Add or update multiple properties in a single state update. */
  trackProperties: (properties: PropertyContextData[]) => void;
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
  trackProperties: () => {},
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

  /** Batch-track multiple properties in a single state update (e.g., from search results). */
  const trackProperties = useCallback(
    (properties: PropertyContextData[]) => {
      setTrackedProperties((prev) => {
        let next = [...prev];
        const now = Date.now();
        for (const property of properties) {
          const idx = next.findIndex(
            (t) =>
              t.property.address === property.address ||
              (t.property.latitude === property.latitude &&
                t.property.longitude === property.longitude),
          );
          if (idx >= 0) {
            // Update existing — merge property data, keep existing blocks
            next[idx] = {
              ...next[idx],
              property: { ...next[idx].property, ...property },
              updatedAt: now,
            };
          } else {
            // Add new
            next = [
              ...next,
              {
                property,
                blocks: [],
                addedAt: now,
                updatedAt: now,
              },
            ];
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
        trackProperties,
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
