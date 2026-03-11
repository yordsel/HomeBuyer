import { useState, useEffect, useCallback } from 'react';
import { Search, Loader2, AlertCircle, Map, Link } from 'lucide-react';
import { toast } from 'sonner';
import * as api from '../lib/api';
import { PredictionCard } from '../components/PredictionCard';
import { PriceBreakdown } from '../components/PriceBreakdown';
import { CompsTable } from '../components/CompsTable';
import { PredictMap } from '../components/PredictMap';
import { ClickableMap } from '../components/ClickableMap';
import { PropertyDetailsForm } from '../components/PropertyDetailsForm';
import { PotentialSummaryCard } from '../components/PotentialSummaryCard';
import { usePropertyContext } from '../context/PropertyContext';
import type {
  ListingPredictionResponse,
  PredictMode,
  MapClickResponse,
  ManualPredictPayload,
  NeighborhoodGeoJson,
  PageId,
} from '../types';

interface PredictPageProps {
  onNavigate: (page: PageId) => void;
}

export function PredictPage({ onNavigate }: PredictPageProps) {
  const { setLastProperty } = usePropertyContext();
  // Shared state
  const [mode, setMode] = useState<PredictMode>('map');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ListingPredictionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // URL mode state
  const [url, setUrl] = useState('');

  // Map mode state
  const [geojson, setGeojson] = useState<NeighborhoodGeoJson | null>(null);
  const [mapClickResult, setMapClickResult] = useState<MapClickResponse | null>(
    null,
  );

  // Load GeoJSON once for the map
  useEffect(() => {
    api.getNeighborhoodGeoJson().then(setGeojson).catch(() => {});
  }, []);

  // ----- URL mode handler -----

  async function handleUrlPredict() {
    const trimmed = url.trim();
    if (!trimmed) {
      toast.error('Please enter a Redfin listing URL');
      return;
    }
    if (!trimmed.includes('redfin.com')) {
      toast.error('Please enter a valid Redfin URL');
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    setLastProperty(null);

    try {
      const data = await api.predictListing(trimmed);
      setResult(data);
      setLastProperty({
        latitude: data.listing.latitude,
        longitude: data.listing.longitude,
        address: data.listing.address,
      });
      toast.success('Prediction complete');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      toast.error('Prediction failed');
    } finally {
      setLoading(false);
    }
  }

  // ----- Map click handler -----

  const handleMapClick = useCallback(async (lat: number, lng: number) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setLastProperty(null);
    setMapClickResult(null);

    try {
      const data = await api.predictMapClick(lat, lng);
      setMapClickResult(data);

      if (data.status === 'prediction') {
        setResult({
          listing: data.listing!,
          prediction: data.prediction!,
          comparables: data.comparables!,
        });
        setLastProperty({
          latitude: data.listing!.latitude,
          longitude: data.listing!.longitude,
          address: data.listing!.address,
        });
        toast.success('Prediction complete');
      } else if (data.status === 'needs_details') {
        toast.info('Location verified! Fill in property details below.');
      }
      // 'error' status is handled by the map popup
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      toast.error('Map click failed');
    } finally {
      setLoading(false);
    }
  }, []);

  // ----- Manual form submit handler (after needs_details) -----

  const handleManualPredict = useCallback(
    async (payload: ManualPredictPayload) => {
      setLoading(true);
      setError(null);

      try {
        const data = await api.predictManual(payload);

        // Fetch comps for the neighborhood
        const comps = await api.getComparables({
          neighborhood: payload.neighborhood,
          beds: payload.beds,
          baths: payload.baths,
          sqft: payload.sqft,
          year_built: payload.year_built,
        });

        const locationInfo = mapClickResult?.location_info;
        const manualListing = {
          address: locationInfo?.address || 'Selected Location',
          city: 'Berkeley',
          state: 'CA',
          zip_code: payload.zip_code || '',
          latitude: payload.latitude || locationInfo?.latitude || 0,
          longitude: payload.longitude || locationInfo?.longitude || 0,
          beds: payload.beds ?? null,
          baths: payload.baths ?? null,
          sqft: payload.sqft ?? null,
          year_built: payload.year_built ?? null,
          lot_size_sqft: payload.lot_size_sqft ?? null,
          property_type:
            payload.property_type || 'Single Family Residential',
          list_price: payload.list_price ?? null,
          neighborhood: payload.neighborhood,
          redfin_url: '',
          property_id: null,
          sale_date: null,
          hoa_per_month: payload.hoa_per_month ?? null,
          garage_spaces: null,
          last_sale_price: null,
          last_sale_date: null,
        };
        setResult({
          listing: manualListing,
          prediction: data.prediction,
          comparables: comps,
        });
        setLastProperty({
          latitude: manualListing.latitude,
          longitude: manualListing.longitude,
          address: manualListing.address,
        });
        toast.success('Prediction complete');
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        toast.error('Prediction failed');
      } finally {
        setLoading(false);
      }
    },
    [mapClickResult],
  );

  // ----- Mode switch -----

  function switchMode(newMode: PredictMode) {
    if (newMode === mode) return;
    setMode(newMode);
    setResult(null);
    setLastProperty(null);
    setError(null);
    setMapClickResult(null);
  }

  // Shared results panel (used by both map and URL modes)
  const resultsPanel = (
    <>
      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle size={18} className="text-red-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-800">
              Prediction failed
            </p>
            <p className="text-sm text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Listing address */}
          <div>
            <h3 className="text-base font-semibold text-gray-900">
              {result.listing.address}
            </h3>
            <p className="text-xs text-gray-500">
              {result.listing.city}, {result.listing.state}{' '}
              {result.listing.zip_code}
            </p>
          </div>

          {/* Prediction Card */}
          <PredictionCard
            prediction={result.prediction}
            listing={result.listing}
          />

          {/* Development Potential Summary */}
          <PotentialSummaryCard
            listing={result.listing}
            onViewDetails={() => onNavigate('potential')}
          />

          {/* Price Breakdown */}
          {result.prediction.feature_contributions &&
            result.prediction.base_value != null && (
              <PriceBreakdown
                baseValue={result.prediction.base_value}
                contributions={result.prediction.feature_contributions}
                predictedPrice={result.prediction.predicted_price}
              />
            )}

          {/* Comparable Sales */}
          <CompsTable comps={result.comparables} />
        </div>
      )}
    </>
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">
            Price Prediction
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {mode === 'map'
              ? 'Search for an address or click the map to predict what it will sell for.'
              : 'Paste a Redfin listing URL to predict what it will sell for.'}
          </p>
        </div>

        {/* Mode toggle */}
        <div className="flex rounded-lg border border-gray-200 bg-gray-50 p-0.5">
          <button
            onClick={() => switchMode('map')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              mode === 'map'
                ? 'bg-white text-blue-700 shadow-sm border border-gray-200'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Map size={14} />
            Map
          </button>
          <button
            onClick={() => switchMode('url')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              mode === 'url'
                ? 'bg-white text-blue-700 shadow-sm border border-gray-200'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Link size={14} />
            URL
          </button>
        </div>
      </div>

      {/* ===== MAP MODE — side-by-side layout ===== */}
      {mode === 'map' && (
        <div className="flex gap-4 items-start" style={{ height: 'calc(100vh - 140px)' }}>
          {/* Left: Map */}
          <div className="flex-1 min-w-0 h-full flex flex-col gap-4">
            <div className="flex-1 min-h-0">
              <ClickableMap
                geojson={geojson}
                onLocationSelect={handleMapClick}
                clickResult={mapClickResult}
                isLoading={loading}
                fillHeight
              />
            </div>

            {/* Property details form (when needs_details and no result yet) */}
            {!result &&
              mapClickResult?.status === 'needs_details' &&
              mapClickResult.location_info && (
                <div className="shrink-0">
                  <PropertyDetailsForm
                    locationInfo={mapClickResult.location_info}
                    onSubmit={handleManualPredict}
                    isLoading={loading}
                  />
                </div>
              )}
          </div>

          {/* Right: Prediction results panel (40% width) */}
          {(result || error) && (
            <div
              className="w-2/5 shrink-0 overflow-y-auto rounded-xl"
              style={{ maxHeight: '100%' }}
            >
              {resultsPanel}
            </div>
          )}
        </div>
      )}

      {/* ===== URL MODE — vertical layout ===== */}
      {mode === 'url' && (
        <div className="max-w-4xl space-y-6">
          {/* Search Bar */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex gap-3">
              <div className="flex-1 relative">
                <Search
                  size={18}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
                />
                <input
                  type="text"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleUrlPredict()}
                  placeholder="https://www.redfin.com/CA/Berkeley/..."
                  className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg text-sm
                             focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  disabled={loading}
                />
              </div>
              <button
                onClick={handleUrlPredict}
                disabled={loading}
                className="px-5 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium
                           hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
                           flex items-center gap-2 transition-colors"
              >
                {loading ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Predicting...
                  </>
                ) : (
                  'Predict'
                )}
              </button>
            </div>
          </div>

          {/* URL mode empty state */}
          {!result && !loading && !error && (
            <div className="text-center py-16">
              <Search size={48} className="mx-auto text-gray-300" />
              <p className="text-gray-500 mt-4">
                Enter a Redfin listing URL above to get started.
              </p>
              <p className="text-xs text-gray-400 mt-2">
                The model predicts what a Berkeley property will actually sell
                for, including a 90% confidence interval.
              </p>
            </div>
          )}

          {/* URL mode results */}
          {resultsPanel}

          {/* Comps map for URL mode */}
          {result && (
            <PredictMap
              listing={result.listing}
              prediction={result.prediction}
              comparables={result.comparables}
            />
          )}
        </div>
      )}
    </div>
  );
}
