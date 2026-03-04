import { useRef, useEffect, useCallback, useMemo } from 'react';
import { MapContainer, TileLayer, GeoJSON, useMap } from 'react-leaflet';
import L from './leafletSetup';
import { Loader2 } from 'lucide-react';
import { formatCurrency } from '../lib/utils';
import type { NeighborhoodStats, NeighborhoodGeoJson, GeoJsonFeature } from '../types';

interface NeighborhoodMapProps {
  neighborhoods: NeighborhoodStats[];
  geojson: NeighborhoodGeoJson | null;
}

/** Berkeley approximate center. */
const BERKELEY_CENTER: [number, number] = [37.8715, -122.273];
const DEFAULT_ZOOM = 13;

// ---------------------------------------------------------------------------
// Color scale — green (low price) → yellow → orange → red (high price)
// ---------------------------------------------------------------------------

function getColor(price: number | null | undefined, min: number, max: number): string {
  if (price == null) return '#d1d5db'; // gray-300
  const ratio = Math.max(0, Math.min(1, (price - min) / (max - min)));
  // Hue: 120 (green) → 0 (red)
  const hue = (1 - ratio) * 120;
  return `hsl(${hue}, 75%, 48%)`;
}

// ---------------------------------------------------------------------------
// Legend control
// ---------------------------------------------------------------------------

function Legend({ min, max }: { min: number; max: number }) {
  const map = useMap();

  useEffect(() => {
    const legend = new L.Control({ position: 'bottomright' });

    legend.onAdd = () => {
      const div = L.DomUtil.create('div', '');
      div.style.cssText =
        'background: white; padding: 8px 12px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.2); font-size: 11px; line-height: 1.5;';

      const steps = 5;
      let html = '<div style="font-weight:600; margin-bottom:4px;">Median Price</div>';
      for (let i = 0; i <= steps; i++) {
        const price = min + ((max - min) * i) / steps;
        const color = getColor(price, min, max);
        html += `<div style="display:flex;align-items:center;gap:6px;">
          <span style="display:inline-block;width:14px;height:14px;background:${color};border-radius:2px;"></span>
          ${formatCurrency(price)}
        </div>`;
      }
      div.innerHTML = html;
      return div;
    };

    legend.addTo(map);
    return () => {
      legend.remove();
    };
  }, [map, min, max]);

  return null;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function NeighborhoodMap({ neighborhoods, geojson }: NeighborhoodMapProps) {
  const geoJsonRef = useRef<L.GeoJSON | null>(null);

  // Build a lookup of neighborhood name → stats
  const statsMap = useMemo(() => {
    const m = new Map<string, NeighborhoodStats>();
    neighborhoods.forEach((n) => m.set(n.name, n));
    return m;
  }, [neighborhoods]);

  // Compute price range across all neighborhoods for color scale
  const { priceMin, priceMax } = useMemo(() => {
    const prices = neighborhoods
      .map((n) => n.median_price)
      .filter((p): p is number => p != null);
    if (prices.length === 0) return { priceMin: 800_000, priceMax: 2_500_000 };
    return { priceMin: Math.min(...prices), priceMax: Math.max(...prices) };
  }, [neighborhoods]);

  // Style each GeoJSON feature based on its stats
  const style = useCallback(
    (feature: GeoJsonFeature | undefined) => {
      const name = feature?.properties?.name;
      const stats = name ? statsMap.get(name) : undefined;
      return {
        fillColor: getColor(stats?.median_price ?? null, priceMin, priceMax),
        weight: 1.5,
        opacity: 0.8,
        color: 'white',
        fillOpacity: 0.55,
      };
    },
    [statsMap, priceMin, priceMax],
  );

  // Bind hover/click interactions to each feature
  const onEachFeature = useCallback(
    (feature: GeoJsonFeature, layer: L.Layer) => {
      const name = feature.properties?.name ?? 'Unknown';
      const stats = statsMap.get(name);

      // Popup
      const popupHtml = stats
        ? `<div style="min-width:180px;font-size:13px;">
             <strong>${name}</strong>
             <div style="margin-top:4px; line-height:1.7;">
               Median: <b>${formatCurrency(stats.median_price)}</b><br/>
               Sales: ${stats.sale_count}<br/>
               ${stats.median_ppsf != null ? `$/sqft: $${Math.round(stats.median_ppsf)}<br/>` : ''}
               ${stats.yoy_price_change_pct != null ? `YoY: <span style="color:${stats.yoy_price_change_pct >= 0 ? '#059669' : '#dc2626'}">${stats.yoy_price_change_pct >= 0 ? '+' : ''}${stats.yoy_price_change_pct.toFixed(1)}%</span>` : ''}
             </div>
           </div>`
        : `<strong>${name}</strong><br/><span style="color:#999;">No sales data</span>`;

      (layer as L.Path).bindPopup(popupHtml);

      // Tooltip on hover (shows neighborhood name)
      (layer as L.Path).bindTooltip(name, {
        sticky: true,
        direction: 'top',
        className: 'leaflet-tooltip-name',
      });

      // Hover highlight
      layer.on({
        mouseover: (e) => {
          const target = e.target as L.Path;
          target.setStyle({
            weight: 3,
            color: '#1e40af',
            fillOpacity: 0.75,
          });
          target.bringToFront();
        },
        mouseout: () => {
          geoJsonRef.current?.resetStyle();
        },
      });
    },
    [statsMap],
  );

  if (!geojson) {
    return (
      <div className="flex items-center justify-center h-[600px] bg-gray-50 rounded-xl border border-gray-200">
        <Loader2 size={32} className="animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" style={{ height: 600 }}>
      <MapContainer
        center={BERKELEY_CENTER}
        zoom={DEFAULT_ZOOM}
        scrollWheelZoom
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <GeoJSON
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ref={geoJsonRef as any}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          data={geojson as any}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          style={style as any}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onEachFeature={onEachFeature as any}
        />
        <Legend min={priceMin} max={priceMax} />
      </MapContainer>
    </div>
  );
}
