import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';

interface MapFlyToProps {
  /** [lat, lng] target, or null to do nothing. */
  position: [number, number] | null;
}

/**
 * Child of <MapContainer> that smoothly flies the map to `position`
 * whenever it changes.
 */
export function MapFlyTo({ position }: MapFlyToProps) {
  const map = useMap();
  const prevRef = useRef<[number, number] | null>(null);

  useEffect(() => {
    if (!position) return;

    // Only fly if the target actually changed
    const prev = prevRef.current;
    if (prev && prev[0] === position[0] && prev[1] === position[1]) return;

    prevRef.current = position;
    map.flyTo(position, 17, { duration: 1.2 });
  }, [position, map]);

  return null;
}
