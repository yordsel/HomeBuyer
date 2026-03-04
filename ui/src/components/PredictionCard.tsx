import { TrendingUp, TrendingDown, ArrowRight, History } from 'lucide-react';
import type { PredictionResult, ListingData } from '../types';
import { formatCurrency, formatPct } from '../lib/utils';

interface PredictionCardProps {
  prediction: PredictionResult;
  listing?: ListingData;
}

export function PredictionCard({ prediction, listing }: PredictionCardProps) {
  const premium = prediction.predicted_premium_pct;
  const isOverList = premium != null && premium > 0;

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-600 to-blue-700 px-6 py-5 text-white">
        <p className="text-sm font-medium text-blue-100">Predicted Sale Price</p>
        <p className="text-4xl font-bold mt-1">
          {formatCurrency(prediction.predicted_price)}
        </p>
        <p className="text-sm text-blue-200 mt-1">
          90% range: {formatCurrency(prediction.price_lower)} — {formatCurrency(prediction.price_upper)}
        </p>
      </div>

      {/* Body */}
      <div className="px-6 py-4 space-y-4">
        {/* Premium vs List */}
        {prediction.list_price && prediction.list_price > 0 && (
          <div className="flex items-center justify-between py-3 border-b border-gray-100">
            <div>
              <p className="text-sm text-gray-500">List Price</p>
              <p className="text-lg font-semibold text-gray-900">
                {formatCurrency(prediction.list_price)}
              </p>
            </div>
            <ArrowRight size={20} className="text-gray-300 mx-4" />
            <div className="text-right">
              <p className="text-sm text-gray-500">Expected Premium</p>
              <div className="flex items-center gap-2 justify-end">
                {isOverList ? (
                  <TrendingUp size={18} className="text-red-500" />
                ) : (
                  <TrendingDown size={18} className="text-green-500" />
                )}
                <p
                  className={`text-lg font-bold ${
                    isOverList ? 'text-red-600' : 'text-green-600'
                  }`}
                >
                  {formatPct(premium, true)}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Last Sale */}
        {listing?.last_sale_price && listing.last_sale_price > 0 && (
          <div className="flex items-center justify-between py-3 border-b border-gray-100">
            <div className="flex items-center gap-2">
              <History size={16} className="text-gray-400" />
              <div>
                <p className="text-sm text-gray-500">Last Sold</p>
                <p className="text-lg font-semibold text-gray-900">
                  {formatCurrency(listing.last_sale_price)}
                </p>
              </div>
            </div>
            {listing.last_sale_date && (
              <p className="text-sm text-gray-500">
                {new Date(listing.last_sale_date + 'T00:00:00').toLocaleDateString('en-US', {
                  month: 'short', day: 'numeric', year: 'numeric'
                })}
              </p>
            )}
          </div>
        )}

        {/* Property Details */}
        {listing && (
          <div>
            <p className="text-sm font-medium text-gray-700 mb-2">Property Details</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {listing.beds != null && (
                <Detail label="Beds" value={String(listing.beds)} />
              )}
              {listing.baths != null && (
                <Detail label="Baths" value={String(listing.baths)} />
              )}
              {listing.sqft != null && (
                <Detail label="Sqft" value={listing.sqft.toLocaleString()} />
              )}
              {listing.year_built != null && (
                <Detail label="Built" value={String(listing.year_built)} />
              )}
            </div>
          </div>
        )}

        {/* Neighborhood */}
        {prediction.neighborhood && (
          <p className="text-sm text-gray-500">
            Neighborhood: <span className="font-medium text-gray-700">{prediction.neighborhood}</span>
          </p>
        )}
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-50 rounded-lg px-3 py-2">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-sm font-semibold text-gray-900">{value}</p>
    </div>
  );
}
