import { createContext, useContext, useState, type ReactNode } from 'react';

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
}

interface PropertyContextValue {
  /** Full active property for the chat-first UX. */
  activeProperty: PropertyContextData | null;
  setActiveProperty: (data: PropertyContextData | null) => void;
  /** Backward-compatible alias used by FaketorFAB and legacy pages. */
  lastProperty: PropertyContextData | null;
  setLastProperty: (data: PropertyContextData | null) => void;
}

const PropertyContext = createContext<PropertyContextValue>({
  activeProperty: null,
  setActiveProperty: () => {},
  lastProperty: null,
  setLastProperty: () => {},
});

export function PropertyProvider({ children }: { children: ReactNode }) {
  const [activeProperty, setActiveProperty] =
    useState<PropertyContextData | null>(null);
  const [lastProperty, setLastProperty] =
    useState<PropertyContextData | null>(null);

  return (
    <PropertyContext.Provider
      value={{
        activeProperty,
        setActiveProperty,
        lastProperty,
        setLastProperty,
      }}
    >
      {children}
    </PropertyContext.Provider>
  );
}

export function usePropertyContext() {
  return useContext(PropertyContext);
}
