import { useState, useCallback, useRef } from 'react';
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  Marker,
  Popup,
  ZoomControl,
  useMapEvents,
} from 'react-leaflet';
import L from './leafletSetup';
import { Loader2, MapPin } from 'lucide-react';
import { AddressSearch } from './AddressSearch';
import { MapFlyTo } from './MapFlyTo';
import type {
  NeighborhoodGeoJson,
  GeoJsonFeature,
  MapClickResponse,
} from '../types';

interface ClickableMapProps {
  geojson: NeighborhoodGeoJson | null;
  onLocationSelect: (lat: number, lng: number) => void;
  clickResult: MapClickResponse | null;
  isLoading: boolean;
  /** When true, stretch to fill parent height instead of fixed 500px. */
  fillHeight?: boolean;
}

/** Berkeley approximate center. */
const BERKELEY_CENTER: [number, number] = [37.8715, -122.273];
const DEFAULT_ZOOM = 14;

// ---------------------------------------------------------------------------
// Marker icons
// ---------------------------------------------------------------------------

/** Red pulsing click marker. */
const clickIcon = L.divIcon({
  className: '',
  html: `<div style="
    width: 24px; height: 24px;
    background: #ef4444;
    border-radius: 50%;
    border: 3px solid white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  "></div>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
  popupAnchor: [0, -14],
});

/** Blue "loading" marker. */
const loadingIcon = L.divIcon({
  className: '',
  html: `<div class="map-pulse-marker" style="
    width: 24px; height: 24px;
    background: #3b82f6;
    border-radius: 50%;
    border: 3px solid white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    animation: pulse 1.5s infinite;
  "></div>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
  popupAnchor: [0, -14],
});

/** Green success marker. */
const successIcon = L.divIcon({
  className: '',
  html: `<div style="
    width: 28px; height: 28px;
    background: #059669;
    border-radius: 50%;
    border: 3px solid white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    display: flex; align-items: center; justify-content: center;
  "><div style="width: 10px; height: 10px; background: white; border-radius: 50%;"></div></div>`,
  iconSize: [28, 28],
  iconAnchor: [14, 14],
  popupAnchor: [0, -16],
});

// ---------------------------------------------------------------------------
// Click handler component (hooks into Leaflet map events)
// ---------------------------------------------------------------------------

function ClickHandler({
  onClick,
}: {
  onClick: (lat: number, lng: number) => void;
}) {
  useMapEvents({
    click(e) {
      onClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ClickableMap({
  geojson,
  onLocationSelect,
  clickResult,
  isLoading,
  fillHeight = false,
}: ClickableMapProps) {
  const [clickedPos, setClickedPos] = useState<[number, number] | null>(null);
  const [flyTarget, setFlyTarget] = useState<[number, number] | null>(null);
  const geoJsonRef = useRef<L.GeoJSON | null>(null);

  // Handle map clicks
  const handleClick = useCallback(
    (lat: number, lng: number) => {
      setClickedPos([lat, lng]);
      onLocationSelect(lat, lng);
    },
    [onLocationSelect],
  );

  // Handle address search selection
  const handleAddressSelect = useCallback(
    (lat: number, lng: number, _address: string) => {
      setClickedPos([lat, lng]);
      setFlyTarget([lat, lng]);
      onLocationSelect(lat, lng);
    },
    [onLocationSelect],
  );

  // Determine which icon to show
  const markerIcon = isLoading
    ? loadingIcon
    : clickResult?.status === 'prediction'
      ? successIcon
      : clickIcon;

  // Light overlay style for neighborhood boundaries
  const overlayStyle = useCallback(
    () => ({
      fillColor: '#3b82f6',
      weight: 1.5,
      opacity: 0.5,
      color: '#93c5fd',
      fillOpacity: 0.06,
    }),
    [],
  );

  // Tooltip on each neighborhood
  const onEachFeature = useCallback(
    (feature: GeoJsonFeature, layer: L.Layer) => {
      const name = feature.properties?.name ?? 'Unknown';
      (layer as L.Path).bindTooltip(name, {
        sticky: true,
        direction: 'top',
        className: 'leaflet-tooltip-name',
      });

      // Subtle hover highlight
      layer.on({
        mouseover: (e) => {
          const target = e.target as L.Path;
          target.setStyle({
            weight: 2.5,
            color: '#60a5fa',
            fillOpacity: 0.15,
          });
          target.bringToFront();
        },
        mouseout: () => {
          geoJsonRef.current?.resetStyle();
        },
      });
    },
    [],
  );

  // Build popup content based on the click result
  const popupContent = (() => {
    if (isLoading) {
      return '<div style="text-align:center; padding: 4px 8px;"><b>Analyzing location...</b></div>';
    }
    if (!clickResult) return null;

    if (clickResult.status === 'error') {
      return `<div style="max-width: 220px; padding: 4px;">
        <div style="color: #dc2626; font-weight: 600; margin-bottom: 4px;">Not Available</div>
        <div style="font-size: 12px; color: #6b7280;">${clickResult.error}</div>
      </div>`;
    }

    if (clickResult.status === 'prediction' && clickResult.listing) {
      const listing = clickResult.listing;
      return `<div style="min-width: 180px; padding: 4px;">
        <div style="font-weight: 600;">${listing.address}</div>
        <div style="font-size: 12px; color: #6b7280; margin-top: 2px;">
          ${listing.neighborhood ?? ''} &middot; ${listing.zip_code}
        </div>
        <div style="font-size: 12px; color: #059669; font-weight: 500; margin-top: 4px;">
          Property found! Scroll down for prediction.
        </div>
      </div>`;
    }

    if (clickResult.status === 'needs_details' && clickResult.location_info) {
      const info = clickResult.location_info;
      return `<div style="min-width: 180px; padding: 4px;">
        <div style="font-weight: 600;">${info.address || 'Selected Location'}</div>
        <div style="font-size: 12px; color: #6b7280; margin-top: 2px;">
          ${info.neighborhood} &middot; ${info.zip_code}
        </div>
        <div style="font-size: 12px; color: #2563eb; font-weight: 500; margin-top: 4px;">
          Fill in property details below to predict.
        </div>
      </div>`;
    }

    return null;
  })();

  if (!geojson) {
    return (
      <div className={`flex items-center justify-center ${fillHeight ? 'h-full' : 'h-[500px]'} bg-gray-50 rounded-xl border border-gray-200`}>
        <Loader2 size={32} className="animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className={`bg-white rounded-xl border border-gray-200 overflow-hidden ${fillHeight ? 'h-full flex flex-col' : ''}`}>
      {/* Instructions bar */}
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
        <MapPin size={16} className="text-blue-500 shrink-0" />
        <p className="text-sm text-gray-600">
          Search for an address or click anywhere on the map. The model will
          check if it&apos;s in a residential zone and predict the price.
        </p>
      </div>

      <div style={fillHeight ? undefined : { height: 500 }} className={`relative ${fillHeight ? 'flex-1 min-h-0' : ''}`}>
        {/* Address search overlay */}
        <div className="absolute top-3 left-3 z-[1000]">
          <AddressSearch
            onSelect={handleAddressSelect}
            disabled={isLoading}
          />
        </div>

        <MapContainer
          center={BERKELEY_CENTER}
          zoom={DEFAULT_ZOOM}
          scrollWheelZoom
          zoomControl={false}
          style={{ height: '100%', width: '100%' }}
        >
          <ZoomControl position="bottomleft" />

          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {/* Neighborhood boundary overlay */}
          <GeoJSON
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            ref={geoJsonRef as any}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            data={geojson as any}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            style={overlayStyle as any}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            onEachFeature={onEachFeature as any}
          />

          {/* Click handler */}
          <ClickHandler onClick={handleClick} />

          {/* Fly to searched address */}
          <MapFlyTo position={flyTarget} />

          {/* Click marker */}
          {clickedPos && (
            <Marker position={clickedPos} icon={markerIcon}>
              {popupContent && (
                <Popup autoPan>
                  <div dangerouslySetInnerHTML={{ __html: popupContent }} />
                </Popup>
              )}
            </Marker>
          )}
        </MapContainer>
      </div>
    </div>
  );
}
