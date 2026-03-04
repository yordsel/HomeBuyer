import { useState } from 'react';
import { Loader2, Home } from 'lucide-react';
import type { MapClickLocationInfo, ManualPredictPayload } from '../types';

interface PropertyDetailsFormProps {
  locationInfo: MapClickLocationInfo;
  onSubmit: (payload: ManualPredictPayload) => void;
  isLoading: boolean;
}

export function PropertyDetailsForm({
  locationInfo,
  onSubmit,
  isLoading,
}: PropertyDetailsFormProps) {
  const prefill = locationInfo.attom_prefill;
  const [beds, setBeds] = useState<string>(prefill?.beds?.toString() ?? '');
  const [baths, setBaths] = useState<string>(prefill?.baths?.toString() ?? '');
  const [sqft, setSqft] = useState<string>(prefill?.sqft?.toString() ?? '');
  const [yearBuilt, setYearBuilt] = useState<string>(prefill?.year_built?.toString() ?? '');
  const [lotSize, setLotSize] = useState<string>(prefill?.lot_size_sqft?.toString() ?? '');
  const [propertyType, setPropertyType] = useState(
    prefill?.property_type || 'Single Family Residential',
  );
  const [listPrice, setListPrice] = useState<string>('');

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const payload: ManualPredictPayload = {
      neighborhood: locationInfo.neighborhood,
      zip_code: locationInfo.zip_code,
      latitude: locationInfo.latitude,
      longitude: locationInfo.longitude,
      property_type: propertyType,
    };

    if (beds) payload.beds = parseFloat(beds);
    if (baths) payload.baths = parseFloat(baths);
    if (sqft) payload.sqft = parseInt(sqft, 10);
    if (yearBuilt) payload.year_built = parseInt(yearBuilt, 10);
    if (lotSize) payload.lot_size_sqft = parseInt(lotSize, 10);
    if (listPrice) payload.list_price = parseInt(listPrice, 10);

    onSubmit(payload);
  }

  const inputClass =
    'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm ' +
    'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent ' +
    'disabled:opacity-50 disabled:bg-gray-50';

  const labelClass = 'block text-xs font-medium text-gray-600 mb-1';

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-5">
        <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center">
          <Home size={18} className="text-blue-600" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-gray-900">
            Property Details
          </h3>
          <p className="text-xs text-gray-500">
            Fill in what you know to get a price prediction.
          </p>
          {prefill && Object.keys(prefill).length > 0 && (
            <p className="text-xs text-green-600 mt-0.5">
              Some fields auto-filled from property records.
            </p>
          )}
        </div>
      </div>

      {/* Location info badges */}
      <div className="flex flex-wrap gap-2 mb-5">
        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-700">
          {locationInfo.neighborhood}
        </span>
        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
          {locationInfo.zip_code}
        </span>
        {locationInfo.zoning_class && (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-50 text-green-700">
            Zone: {locationInfo.zoning_class}
          </span>
        )}
        {locationInfo.address && (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-purple-50 text-purple-700">
            {locationInfo.address}
          </span>
        )}
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Row 1: Beds, Baths, Sqft */}
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelClass}>Beds</label>
            <input
              type="number"
              value={beds}
              onChange={(e) => setBeds(e.target.value)}
              placeholder="3"
              min={0}
              step={1}
              className={inputClass}
              disabled={isLoading}
            />
          </div>
          <div>
            <label className={labelClass}>Baths</label>
            <input
              type="number"
              value={baths}
              onChange={(e) => setBaths(e.target.value)}
              placeholder="2"
              min={0}
              step={0.5}
              className={inputClass}
              disabled={isLoading}
            />
          </div>
          <div>
            <label className={labelClass}>Sqft</label>
            <input
              type="number"
              value={sqft}
              onChange={(e) => setSqft(e.target.value)}
              placeholder="1500"
              min={0}
              className={inputClass}
              disabled={isLoading}
            />
          </div>
        </div>

        {/* Row 2: Year Built, Lot Size, Property Type */}
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelClass}>Year Built</label>
            <input
              type="number"
              value={yearBuilt}
              onChange={(e) => setYearBuilt(e.target.value)}
              placeholder="1940"
              min={1800}
              max={2030}
              className={inputClass}
              disabled={isLoading}
            />
          </div>
          <div>
            <label className={labelClass}>Lot Size (sqft)</label>
            <input
              type="number"
              value={lotSize}
              onChange={(e) => setLotSize(e.target.value)}
              placeholder="5000"
              min={0}
              className={inputClass}
              disabled={isLoading}
            />
          </div>
          <div>
            <label className={labelClass}>Property Type</label>
            <select
              value={propertyType}
              onChange={(e) => setPropertyType(e.target.value)}
              className={inputClass}
              disabled={isLoading}
            >
              <option value="Single Family Residential">Single Family</option>
              <option value="Condo/Co-op">Condo/Co-op</option>
              <option value="Townhouse">Townhouse</option>
              <option value="Multi-Family (2-4 Unit)">Multi-Family</option>
            </select>
          </div>
        </div>

        {/* Row 3: List Price (optional) */}
        <div className="max-w-xs">
          <label className={labelClass}>List Price (optional)</label>
          <input
            type="number"
            value={listPrice}
            onChange={(e) => setListPrice(e.target.value)}
            placeholder="1,200,000"
            min={0}
            className={inputClass}
            disabled={isLoading}
          />
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={isLoading}
          className="px-5 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium
                     hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
                     flex items-center gap-2 transition-colors"
        >
          {isLoading ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Predicting...
            </>
          ) : (
            'Predict Price'
          )}
        </button>
      </form>
    </div>
  );
}
