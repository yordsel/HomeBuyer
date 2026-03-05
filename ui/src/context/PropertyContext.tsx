import { createContext, useContext, useState, type ReactNode } from 'react';

interface PropertyContextData {
  latitude: number;
  longitude: number;
  address: string;
}

interface PropertyContextValue {
  lastProperty: PropertyContextData | null;
  setLastProperty: (data: PropertyContextData | null) => void;
}

const PropertyContext = createContext<PropertyContextValue>({
  lastProperty: null,
  setLastProperty: () => {},
});

export function PropertyProvider({ children }: { children: ReactNode }) {
  const [lastProperty, setLastProperty] =
    useState<PropertyContextData | null>(null);

  return (
    <PropertyContext.Provider value={{ lastProperty, setLastProperty }}>
      {children}
    </PropertyContext.Provider>
  );
}

export function usePropertyContext() {
  return useContext(PropertyContext);
}
