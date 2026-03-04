"""Classify properties into City of Berkeley zoning districts.

Uses geopandas spatial join to efficiently assign zoning classes to
properties based on their lat/long coordinates and the City of Berkeley
zoning polygon boundaries.
"""

import logging
from pathlib import Path
from typing import Optional

import geopandas as gpd
from shapely.geometry import Point

from homebuyer.config import GEO_DIR
from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)

# Default path to the zoning GeoJSON
DEFAULT_ZONING_PATH = GEO_DIR / "berkeley_zoning.geojson"


class ZoningClassifier:
    """Assigns zoning district classes to properties using point-in-polygon lookup."""

    def __init__(self, zoning_path: Optional[Path] = None) -> None:
        """Initialize with zoning boundary data.

        Args:
            zoning_path: Path to the zoning GeoJSON file.
                         Defaults to data/geo/berkeley_zoning.geojson.
        """
        path = zoning_path or DEFAULT_ZONING_PATH
        if not path.exists():
            raise FileNotFoundError(
                f"Zoning GeoJSON not found at {path}. "
                f"Download from City of Berkeley ArcGIS."
            )

        self.boundaries = gpd.read_file(path)

        # Ensure the GeoDataFrame has a 'ZONECLASS' column
        if "ZONECLASS" not in self.boundaries.columns:
            raise ValueError(
                "Zoning GeoJSON must have a 'ZONECLASS' property on each feature."
            )

        # Build spatial index for fast lookups
        self._sindex = self.boundaries.sindex
        logger.info(
            "ZoningClassifier initialized with %d zoning polygons (%d unique classes).",
            len(self.boundaries),
            self.boundaries["ZONECLASS"].nunique(),
        )

    def classify_point(self, lat: float, lon: float) -> Optional[str]:
        """Find which zoning polygon contains a given point.

        Args:
            lat: Latitude (y coordinate).
            lon: Longitude (x coordinate).

        Returns:
            The ZONECLASS string (e.g. "R-1", "R-2A", "C-W"),
            or None if the point is outside all zoning boundaries.
        """
        point = Point(lon, lat)  # shapely uses (x, y) = (lon, lat)

        # Query spatial index for candidate polygons
        candidates = list(
            self._sindex.query(point.buffer(0.001), predicate="intersects")
        )

        for idx in candidates:
            if self.boundaries.geometry.iloc[idx].contains(point):
                return self.boundaries.iloc[idx]["ZONECLASS"]

        return None

    def classify_batch(self, db: Database) -> int:
        """Classify all property_sales rows with NULL zoning_class.

        Uses geopandas spatial join for batch efficiency.

        Args:
            db: The database to read from and update.

        Returns:
            Number of properties that were assigned a zoning class.
        """
        rows = db.get_sales_missing_zoning()
        if not rows:
            logger.info("No sales need zoning classification.")
            return 0

        logger.info(
            "Classifying zoning for %d properties with missing zoning_class...",
            len(rows),
        )

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
            logger.warning("No valid coordinates found for zoning classification.")
            return 0

        points_gdf = gpd.GeoDataFrame(points_data, crs="EPSG:4326")

        # Ensure boundaries have the same CRS
        boundaries = self.boundaries.to_crs("EPSG:4326")

        # Spatial join: find which zoning polygon each point falls in
        joined = gpd.sjoin(points_gdf, boundaries, how="left", predicate="within")

        # Collect updates
        updates: list[tuple[str, int]] = []
        unresolved = 0

        for _, row in joined.iterrows():
            zoning = row.get("ZONECLASS")
            sale_id = row["id"]

            if zoning and not (isinstance(zoning, float)):
                updates.append((zoning, sale_id))
            else:
                unresolved += 1

        if updates:
            db.update_zoning_batch(updates)

        logger.info(
            "Classified %d properties with zoning districts. %d remain unresolved.",
            len(updates),
            unresolved,
        )

        return len(updates)
