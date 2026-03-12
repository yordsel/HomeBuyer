"""Custom JSON serialization utilities.

Provides a ``SafeEncoder`` that converts non-standard Python types
(numpy scalars, Decimal, datetime, dataclasses) to JSON-native types
instead of falling back to ``str``.

This prevents the frontend from receiving string-encoded numbers like
``"1.3"`` instead of ``1.3``, which causes runtime errors such as
``e.toFixed is not a function``.

Usage::

    import json
    from homebuyer.utils.serialization import safe_json_dumps

    json_str = safe_json_dumps(data)
"""

from __future__ import annotations

import dataclasses
import datetime
import json
from decimal import Decimal
from typing import Any


class SafeEncoder(json.JSONEncoder):
    """JSON encoder that converts non-standard types to JSON-native types.

    Handles:
    - ``decimal.Decimal`` → ``int`` or ``float``
    - ``numpy`` scalars (float64, int64, bool_) → Python float/int/bool
    - ``numpy.ndarray`` → list
    - ``datetime.datetime`` → ISO 8601 string
    - ``datetime.date`` → ISO 8601 string
    - ``dataclasses`` → dict via ``dataclasses.asdict()``
    - ``set`` / ``frozenset`` → list
    - Anything else → ``str(obj)`` as a last resort
    """

    def default(self, obj: Any) -> Any:  # noqa: C901
        # --- Decimal → int or float ---
        if isinstance(obj, Decimal):
            # Preserve integer values as int (e.g., Decimal("100") → 100)
            if obj == obj.to_integral_value():
                return int(obj)
            return float(obj)

        # --- numpy types ---
        # Import lazily so numpy is not a hard dependency
        try:
            import numpy as np

            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass

        # --- datetime / date ---
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, datetime.date):
            return obj.isoformat()

        # --- dataclasses ---
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)

        # --- set / frozenset ---
        if isinstance(obj, (set, frozenset)):
            return list(obj)

        # --- Last resort: str() (same behaviour as default=str, but after
        #     handling the known numeric types above) ---
        return str(obj)


def safe_json_dumps(obj: Any, **kwargs: Any) -> str:
    """Serialize ``obj`` to a JSON string using :class:`SafeEncoder`.

    Drop-in replacement for ``json.dumps(obj, default=str)`` that preserves
    numeric types instead of converting them to strings.

    Any extra keyword arguments are forwarded to ``json.dumps``.
    """
    kwargs.setdefault("cls", SafeEncoder)
    return json.dumps(obj, **kwargs)
