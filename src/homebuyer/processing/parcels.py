"""Spatial enrichment for the properties and property_sales tables.

Assigns zoning districts and neighborhoods to parcels in the ``properties``
and ``property_sales`` tables using geopandas spatial joins against the
City of Berkeley boundary polygon GeoJSON files.

Reuses the existing ``ZoningClassifier`` and ``NeighborhoodGeocoder`` with
a batch spatial-join approach for efficiency.
"""

import logging
from typing import Callable

import geopandas as gpd
from shapely.geometry import Point

from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic spatial enrichment helper
# ---------------------------------------------------------------------------


def _enrich_spatial(
    db: Database,
    missing_fn: Callable,
    update_fn: Callable,
    boundaries: gpd.GeoDataFrame,
    join_col: str,
    label: str,
) -> int:
    """Batch-assign a spatial attribute to rows missing it.

    Args:
        db: Database instance (unused directly, but ``missing_fn`` /
            ``update_fn`` are bound methods on it).
        missing_fn: Callable returning list of dicts with ``id``, ``latitude``,
            ``longitude`` for rows that need enrichment.
        update_fn: Callable accepting list of ``(value, id)`` tuples to write
            back to the DB.
        boundaries: GeoDataFrame of polygons to join against.
        join_col: Column name in ``boundaries`` to extract (e.g. ``ZONECLASS``
            or ``name``).
        label: Human-readable label for log messages.

    Returns:
        Number of rows updated.
    """
    rows = missing_fn()
    if not rows:
        logger.info("No rows need %s assignment.", label)
        return 0

    logger.info("Assigning %s for %d rows...", label, len(rows))

    # Build GeoDataFrame of points
    points_data = [
        {"id": row["id"], "geometry": Point(row["longitude"], row["latitude"])}
        for row in rows
        if row.get("latitude") and row.get("longitude")
        and row["latitude"] != 0 and row["longitude"] != 0
    ]
    if not points_data:
        logger.warning("No valid coordinates found for %s assignment.", label)
        return 0

    points_gdf = gpd.GeoDataFrame(points_data, crs="EPSG:4326")
    bounds = boundaries.to_crs("EPSG:4326")
    joined = gpd.sjoin(points_gdf, bounds, how="left", predicate="within")

    # Collect updates: (value, row_id)
    updates: list[tuple[str, int]] = []
    unresolved = 0
    for _, row in joined.iterrows():
        value = row.get(join_col)
        row_id = row["id"]
        if value and not isinstance(value, float):
            updates.append((value, row_id))
        else:
            unresolved += 1

    if updates:
        count = update_fn(updates)
        logger.info(
            "Assigned %s to %d rows. %d remain unresolved.",
            label, count, unresolved,
        )
        return count

    return 0


# ---------------------------------------------------------------------------
# Properties table enrichment
# ---------------------------------------------------------------------------


def enrich_parcels_spatial(db: Database) -> tuple[int, int]:
    """Assign zoning and neighborhood to properties via spatial join.

    Processes all properties that are missing either zoning_class or
    neighborhood using geopandas spatial join against the boundary
    polygon GeoJSON files.

    Returns:
        (zoning_count, neighborhood_count) — number of properties
        updated for each attribute.
    """
    zoning_count = _enrich_properties_zoning(db)
    neighborhood_count = _enrich_properties_neighborhoods(db)
    return zoning_count, neighborhood_count


def _enrich_properties_zoning(db: Database) -> int:
    from homebuyer.processing.zoning import ZoningClassifier
    try:
        classifier = ZoningClassifier()
    except FileNotFoundError as e:
        logger.warning("Skipping zoning enrichment: %s", e)
        return 0
    return _enrich_spatial(
        db, db.get_properties_missing_zoning, db.update_properties_zoning_batch,
        classifier.boundaries, "ZONECLASS", "zoning",
    )


def _enrich_properties_neighborhoods(db: Database) -> int:
    from homebuyer.processing.geocode import NeighborhoodGeocoder
    try:
        geocoder = NeighborhoodGeocoder()
    except FileNotFoundError as e:
        logger.warning("Skipping neighborhood enrichment: %s", e)
        return 0
    return _enrich_spatial(
        db, db.get_properties_missing_neighborhood, db.update_properties_neighborhood_batch,
        geocoder.boundaries, "name", "neighborhood",
    )


# ---------------------------------------------------------------------------
# Property sales table enrichment
# ---------------------------------------------------------------------------


def enrich_sales_spatial(db: Database) -> tuple[int, int]:
    """Assign zoning and neighborhood to property_sales via spatial join.

    Same approach as ``enrich_parcels_spatial`` but targets the
    ``property_sales`` table so that sales records from RentCast
    (and other sources) get the spatial attributes needed for ML training.

    Returns:
        (zoning_count, neighborhood_count) — number of sales updated.
    """
    zoning_count = _enrich_sales_zoning(db)
    neighborhood_count = _enrich_sales_neighborhoods(db)
    return zoning_count, neighborhood_count


def _enrich_sales_zoning(db: Database) -> int:
    from homebuyer.processing.zoning import ZoningClassifier
    try:
        classifier = ZoningClassifier()
    except FileNotFoundError as e:
        logger.warning("Skipping sales zoning enrichment: %s", e)
        return 0
    return _enrich_spatial(
        db, db.get_sales_missing_zoning, db.update_sales_zoning_batch,
        classifier.boundaries, "ZONECLASS", "sales zoning",
    )


def _enrich_sales_neighborhoods(db: Database) -> int:
    from homebuyer.processing.geocode import NeighborhoodGeocoder
    try:
        geocoder = NeighborhoodGeocoder()
    except FileNotFoundError as e:
        logger.warning("Skipping sales neighborhood enrichment: %s", e)
        return 0
    return _enrich_spatial(
        db, db.get_sales_missing_neighborhood, db.update_sales_neighborhood_batch,
        geocoder.boundaries, "name", "sales neighborhood",
    )
