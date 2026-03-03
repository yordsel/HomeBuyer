"""Geocode properties to neighborhoods using lat/long and boundary polygons.

Uses geopandas spatial join to efficiently assign neighborhoods to
properties that have coordinates but no neighborhood label.
"""

import logging
from pathlib import Path
from typing import Optional

from homebuyer.collectors.neighborhoods import load_boundaries_geodataframe
from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


class NeighborhoodGeocoder:
    """Assigns neighborhoods to properties using point-in-polygon lookup."""

    def __init__(self, boundary_path: Optional[Path] = None) -> None:
        """Initialize with neighborhood boundary data.

        Args:
            boundary_path: Path to the GeoJSON boundary file.
                          Defaults to the project's geo directory.
        """
        self.boundaries = load_boundaries_geodataframe(boundary_path)

        # Ensure the GeoDataFrame has a 'name' column
        if "name" not in self.boundaries.columns:
            raise ValueError(
                "Boundary GeoJSON must have a 'name' property on each feature."
            )

        # Build spatial index for fast lookups
        self._sindex = self.boundaries.sindex
        logger.info(
            "Geocoder initialized with %d neighborhood boundaries.",
            len(self.boundaries),
        )

    def geocode_point(self, lat: float, lon: float) -> Optional[str]:
        """Find which neighborhood polygon contains a given point.

        Args:
            lat: Latitude (y coordinate).
            lon: Longitude (x coordinate).

        Returns:
            The neighborhood name, or None if the point is outside all boundaries.
        """
        from shapely.geometry import Point

        point = Point(lon, lat)  # shapely uses (x, y) = (lon, lat)

        # Query spatial index for candidate polygons
        candidates = list(self._sindex.query(point.buffer(0.001), predicate="intersects"))

        for idx in candidates:
            if self.boundaries.geometry.iloc[idx].contains(point):
                return self.boundaries.iloc[idx]["name"]

        return None

    def geocode_batch(self, db: Database) -> tuple[int, int]:
        """Geocode all property_sales rows with NULL neighborhood.

        Uses geopandas spatial join for batch efficiency.

        Args:
            db: The database to read from and update.

        Returns:
            (geocoded_count, unresolved_count)
        """
        import geopandas as gpd
        from shapely.geometry import Point

        rows = db.get_sales_missing_neighborhood()
        if not rows:
            logger.info("No sales need geocoding.")
            return 0, 0

        logger.info("Geocoding %d properties with missing neighborhoods...", len(rows))

        # Convert to GeoDataFrame of points
        points_data = []
        for row in rows:
            lat = row["latitude"]
            lon = row["longitude"]
            if lat and lon and lat != 0 and lon != 0:
                points_data.append(
                    {
                        "id": row["id"],
                        "geometry": Point(lon, lat),
                    }
                )

        if not points_data:
            logger.warning("No valid coordinates found for geocoding.")
            return 0, len(rows)

        points_gdf = gpd.GeoDataFrame(points_data, crs="EPSG:4326")

        # Ensure boundaries have the same CRS
        boundaries = self.boundaries.to_crs("EPSG:4326")

        # Spatial join: find which boundary polygon each point falls in
        joined = gpd.sjoin(points_gdf, boundaries, how="left", predicate="within")

        # Collect updates
        updates: list[tuple[str, int]] = []
        unresolved = 0

        for _, row in joined.iterrows():
            neighborhood = row.get("name")
            sale_id = row["id"]

            if neighborhood and not (isinstance(neighborhood, float)):
                updates.append((neighborhood, sale_id))
            else:
                unresolved += 1

        if updates:
            db.update_neighborhoods_batch(updates)

        logger.info(
            "Geocoded %d properties. %d remain unresolved.",
            len(updates),
            unresolved,
        )

        return len(updates), unresolved
