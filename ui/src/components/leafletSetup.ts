/**
 * Shared Leaflet configuration.
 *
 * Importing this module loads the Leaflet CSS (required for proper rendering).
 * We use custom divIcon markers instead of the default image-based icons,
 * so no icon path fix is needed.
 */

import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

export default L;
