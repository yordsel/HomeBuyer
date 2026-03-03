"""Neighborhood boundary file loader.

Loads Berkeley neighborhood boundaries from a GeoJSON file shipped with the
project. These boundaries are used for geocoding properties with missing
neighborhood labels.

Berkeley neighborhoods are informal/historical (not formally defined by the
city), so we maintain a hand-curated GeoJSON file with commonly accepted
boundaries.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from homebuyer.config import GEO_DIR

logger = logging.getLogger(__name__)

# Default path to the boundary file
BOUNDARY_FILE = GEO_DIR / "berkeley_neighborhoods.geojson"


def load_boundaries_geojson(path: Optional[Path] = None) -> dict:
    """Load the neighborhood boundary GeoJSON as a Python dict.

    Args:
        path: Path to the GeoJSON file. Defaults to BOUNDARY_FILE.

    Returns:
        The parsed GeoJSON dict.

    Raises:
        FileNotFoundError: If the boundary file does not exist.
    """
    path = path or BOUNDARY_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Neighborhood boundary file not found: {path}\n"
            f"Run 'homebuyer init' to set up the project, or place a GeoJSON file at {path}"
        )

    with open(path, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    feature_count = len(geojson.get("features", []))
    logger.info("Loaded %d neighborhood boundaries from %s", feature_count, path)
    return geojson


def load_boundaries_geodataframe(path: Optional[Path] = None):
    """Load the neighborhood boundary file as a GeoDataFrame.

    Requires geopandas (imported here to avoid import-time dependency
    for modules that don't need spatial operations).

    Args:
        path: Path to the GeoJSON file. Defaults to BOUNDARY_FILE.

    Returns:
        A geopandas GeoDataFrame with columns: name, geometry.
    """
    import geopandas as gpd

    path = path or BOUNDARY_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Neighborhood boundary file not found: {path}\n"
            f"Run 'homebuyer init' to set up the project, or place a GeoJSON file at {path}"
        )

    gdf = gpd.read_file(path)
    logger.info(
        "Loaded %d neighborhood boundaries as GeoDataFrame from %s",
        len(gdf), path,
    )
    return gdf


def get_neighborhood_names(path: Optional[Path] = None) -> list[str]:
    """Return a sorted list of canonical neighborhood names from the boundary file."""
    geojson = load_boundaries_geojson(path)
    names = []
    for feature in geojson.get("features", []):
        name = feature.get("properties", {}).get("name", "")
        if name:
            names.append(name)
    return sorted(names)
