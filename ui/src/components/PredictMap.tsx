import { useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from './leafletSetup';
import { formatCurrency } from '../lib/utils';
import type { ListingData, PredictionResult, ComparableProperty } from '../types';

interface PredictMapProps {
  listing: ListingData;
  prediction: PredictionResult;
  comparables: ComparableProperty[];
}

/** Large blue marker for the target listing. */
const targetIcon = L.divIcon({
  className: '',
  html: `<div style="
    width: 32px; height: 32px;
    background: #2563eb;
    border-radius: 50%;
    border: 3px solid white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    display: flex; align-items: center; justify-content: center;
  "><div style="width: 10px; height: 10px; background: white; border-radius: 50%;"></div></div>`,
  iconSize: [32, 32],
  iconAnchor: [16, 16],
  popupAnchor: [0, -18],
});

/** Small green marker for comparable properties. */
const compIcon = L.divIcon({
  className: '',
  html: `<div style="
    width: 20px; height: 20px;
    background: #059669;
    border-radius: 50%;
    border: 2px solid white;
    box-shadow: 0 1px 4px rgba(0,0,0,0.25);
  "></div>`,
  iconSize: [20, 20],
  iconAnchor: [10, 10],
  popupAnchor: [0, -12],
});

export function PredictMap({ listing, prediction, comparables }: PredictMapProps) {
  const center: [number, number] = [listing.latitude, listing.longitude];

  // Filter comps that have valid coordinates
  const mappedComps = useMemo(
    () =>
      comparables.filter(
        (c) => c.latitude != null && c.longitude != null && c.latitude !== 0,
      ),
    [comparables],
  );

  // Compute bounds to fit all markers
  const bounds = useMemo(() => {
    const points: [number, number][] = [center];
    mappedComps.forEach((c) => {
      points.push([c.latitude!, c.longitude!]);
    });
    if (points.length <= 1) return undefined;
    return L.latLngBounds(points.map(([lat, lng]) => L.latLng(lat, lng))).pad(0.15);
  }, [center, mappedComps]);

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-900">Property & Comparables Map</h3>
        <p className="text-xs text-gray-500 mt-0.5">
          Blue pin = this listing &middot; Green pins = comparable sales
        </p>
      </div>
      <div style={{ height: 400 }}>
        <MapContainer
          center={center}
          zoom={15}
          bounds={bounds}
          scrollWheelZoom
          style={{ height: '100%', width: '100%' }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {/* Target listing */}
          <Marker position={center} icon={targetIcon}>
            <Popup>
              <div className="text-sm" style={{ minWidth: 200 }}>
                <p className="font-semibold text-gray-900">{listing.address}</p>
                <p className="text-gray-500 text-xs">
                  {listing.city}, {listing.state} {listing.zip_code}
                </p>
                <div className="mt-2 space-y-1 text-xs">
                  {listing.list_price != null && (
                    <p>
                      List Price: <span className="font-medium">{formatCurrency(listing.list_price)}</span>
                    </p>
                  )}
                  <p>
                    Predicted: <span className="font-medium text-blue-700">{formatCurrency(prediction.predicted_price)}</span>
                  </p>
                  <p className="text-gray-500">
                    {listing.beds ?? '—'} bd &middot; {listing.baths ?? '—'} ba &middot; {listing.sqft ?? '—'} sqft
                    {listing.year_built ? ` &middot; Built ${listing.year_built}` : ''}
                  </p>
                </div>
              </div>
            </Popup>
          </Marker>

          {/* Comparable sales */}
          {mappedComps.map((comp, idx) => (
            <Marker
              key={`${comp.address}-${idx}`}
              position={[comp.latitude!, comp.longitude!]}
              icon={compIcon}
            >
              <Popup>
                <div className="text-sm" style={{ minWidth: 180 }}>
                  <p className="font-semibold text-gray-900">{comp.address}</p>
                  <div className="mt-1 space-y-0.5 text-xs">
                    <p>
                      Sold: <span className="font-medium text-emerald-700">{formatCurrency(comp.sale_price)}</span>
                    </p>
                    <p className="text-gray-500">Date: {comp.sale_date}</p>
                    <p className="text-gray-500">
                      {comp.beds ?? '—'} bd &middot; {comp.baths ?? '—'} ba &middot; {comp.sqft ?? '—'} sqft
                    </p>
                    {comp.price_per_sqft != null && (
                      <p className="text-gray-500">${Math.round(comp.price_per_sqft)}/sqft</p>
                    )}
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>
    </div>
  );
}
