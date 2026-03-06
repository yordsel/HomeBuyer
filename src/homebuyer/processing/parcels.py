"""Spatial enrichment for the properties table.

Assigns zoning districts and neighborhoods to parcels in the ``properties``
table using geopandas spatial joins against the City of Berkeley boundary
polygon GeoJSON files.

Reuses the existing ``ZoningClassifier`` and ``NeighborhoodGeocoder`` with
a batch spatial-join approach for efficiency.
"""

import logging

import geopandas as gpd
from shapely.geometry import Point

from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


def enrich_parcels_spatial(db: Database) -> tuple[int, int]:
    """Assign zoning and neighborhood to properties via spatial join.

    Processes all properties that are missing either zoning_class or
    neighborhood using geopandas spatial join against the boundary
    polygon GeoJSON files.

    Args:
        db: The database containing the properties table.

    Returns:
        (zoning_count, neighborhood_count) — number of properties
        updated for each attribute.
    """
    zoning_count = _enrich_zoning(db)
    neighborhood_count = _enrich_neighborhoods(db)
    return zoning_count, neighborhood_count


def _enrich_zoning(db: Database) -> int:
    """Batch-assign zoning classes to properties missing zoning_class.

    Uses geopandas spatial join against the berkeley_zoning.geojson
    boundary file.

    Returns:
        Number of properties updated with zoning information.
    """
    from homebuyer.processing.zoning import ZoningClassifier

    rows = db.get_properties_missing_zoning()
    if not rows:
        logger.info("No properties need zoning classification.")
        return 0

    logger.info(
        "Classifying zoning for %d properties...", len(rows),
    )

    try:
        classifier = ZoningClassifier()
    except FileNotFoundError as e:
        logger.warning("Skipping zoning enrichment: %s", e)
        return 0

    # Build GeoDataFrame of property points
    points_data = []
    for row in rows:
        lat = row.get("latitude")
        lon = row.get("longitude")
        if lat and lon and lat != 0 and lon != 0:
            points_data.append({
                "id": row["id"],
                "geometry": Point(lon, lat),
            })

    if not points_data:
        logger.warning("No valid coordinates found for zoning classification.")
        return 0

    points_gdf = gpd.GeoDataFrame(points_data, crs="EPSG:4326")

    # Ensure boundaries have the same CRS
    boundaries = classifier.boundaries.to_crs("EPSG:4326")

    # Spatial join: find which zoning polygon each point falls in
    joined = gpd.sjoin(points_gdf, boundaries, how="left", predicate="within")

    # Collect updates: (zoning_class, property_id)
    updates: list[tuple[str, int]] = []
    unresolved = 0

    for _, row in joined.iterrows():
        zoning = row.get("ZONECLASS")
        prop_id = row["id"]

        if zoning and not isinstance(zoning, float):
            updates.append((zoning, prop_id))
        else:
            unresolved += 1

    if updates:
        count = db.update_properties_zoning_batch(updates)
        logger.info(
            "Assigned zoning to %d properties. %d remain unresolved.",
            count, unresolved,
        )
        return count

    return 0


def _enrich_neighborhoods(db: Database) -> int:
    """Batch-assign neighborhoods to properties missing neighborhood.

    Uses geopandas spatial join against the neighborhood boundary
    GeoJSON file.

    Returns:
        Number of properties updated with neighborhood information.
    """
    from homebuyer.processing.geocode import NeighborhoodGeocoder

    rows = db.get_properties_missing_neighborhood()
    if not rows:
        logger.info("No properties need neighborhood assignment.")
        return 0

    logger.info(
        "Assigning neighborhoods for %d properties...", len(rows),
    )

    try:
        geocoder = NeighborhoodGeocoder()
    except FileNotFoundError as e:
        logger.warning("Skipping neighborhood enrichment: %s", e)
        return 0

    # Build GeoDataFrame of property points
    points_data = []
    for row in rows:
        lat = row.get("latitude")
        lon = row.get("longitude")
        if lat and lon and lat != 0 and lon != 0:
            points_data.append({
                "id": row["id"],
                "geometry": Point(lon, lat),
            })

    if not points_data:
        logger.warning("No valid coordinates found for neighborhood assignment.")
        return 0

    points_gdf = gpd.GeoDataFrame(points_data, crs="EPSG:4326")

    # Ensure boundaries have the same CRS
    boundaries = geocoder.boundaries.to_crs("EPSG:4326")

    # Spatial join: find which neighborhood polygon each point falls in
    joined = gpd.sjoin(points_gdf, boundaries, how="left", predicate="within")

    # Collect updates: (neighborhood_name, property_id)
    updates: list[tuple[str, int]] = []
    unresolved = 0

    for _, row in joined.iterrows():
        neighborhood = row.get("name")
        prop_id = row["id"]

        if neighborhood and not isinstance(neighborhood, float):
            updates.append((neighborhood, prop_id))
        else:
            unresolved += 1

    if updates:
        count = db.update_properties_neighborhood_batch(updates)
        logger.info(
            "Assigned neighborhoods to %d properties. %d remain unresolved.",
            count, unresolved,
        )
        return count

    return 0
