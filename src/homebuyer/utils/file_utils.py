"""Shared file-loading utilities.

Consolidates JSON loading logic previously duplicated across
``services/glossary.py`` and ``services/berkeley_regulations.py``.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_json_data(path: Path) -> dict:
    """Load a JSON data file, filtering out ``$meta`` keys.

    The ``$meta`` key is a convention used by the data pipeline to store
    provenance information (scrape timestamps, version, sources).  Consumers
    of the data do not need these keys, so they are stripped on load.

    Args:
        path: Path to the JSON file.

    Returns:
        A dict with all top-level keys except those starting with ``$``.
    """
    with open(path) as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("$")}
