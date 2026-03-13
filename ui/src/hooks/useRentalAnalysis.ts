/**
 * Shared hook for fetching rental analysis data.
 *
 * Deduplicates the identical useEffect + fetch + loading/error state
 * management previously copied between RentalIncomeCard and
 * InvestmentScenarioCard.
 */
import { useState, useEffect, useCallback } from 'react';
import * as api from '../lib/api';
import type { RentalAnalysisResponse } from '../types';

export interface RentalAnalysisParams {
  latitude: number;
  longitude: number;
  address?: string;
  neighborhood?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  lot_size_sqft?: number;
  year_built?: number;
  list_price?: number;
  /** Pre-fetched data. When provided, the hook skips its own fetch. */
  rentalData?: RentalAnalysisResponse;
}

export interface RentalAnalysisState {
  data: RentalAnalysisResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useRentalAnalysis(params: RentalAnalysisParams): RentalAnalysisState {
  const [internalData, setInternalData] = useState<RentalAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveData = params.rentalData ?? internalData;

  const fetchAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getRentalAnalysis({
        latitude: params.latitude,
        longitude: params.longitude,
        address: params.address,
        neighborhood: params.neighborhood,
        beds: params.beds,
        baths: params.baths,
        sqft: params.sqft,
        lot_size_sqft: params.lot_size_sqft,
        year_built: params.year_built,
        list_price: params.list_price,
      });
      setInternalData(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [
    params.latitude,
    params.longitude,
    params.address,
    params.neighborhood,
    params.beds,
    params.baths,
    params.sqft,
    params.lot_size_sqft,
    params.year_built,
    params.list_price,
  ]);

  useEffect(() => {
    // Skip fetch when the parent already provides the data.
    if (params.rentalData) return;
    fetchAnalysis();
  }, [params.rentalData, fetchAnalysis]);

  return {
    data: effectiveData,
    loading,
    error,
    refetch: fetchAnalysis,
  };
}
