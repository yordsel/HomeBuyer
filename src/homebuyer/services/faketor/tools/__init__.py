"""Faketor tool registry — singleton instance.

Import this module to get the populated registry::

    from homebuyer.services.faketor.tools import registry
"""

from homebuyer.services.faketor.tools.registry import ToolRegistry

registry = ToolRegistry()

# Import definitions and register all 18 built-in tools.
from homebuyer.services.faketor.tools.definitions import (  # noqa: E402
    _TOOL_DEFINITIONS,
)

registry.register_many(_TOOL_DEFINITIONS)
