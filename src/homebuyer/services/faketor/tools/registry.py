"""ToolRegistry: unified store for tool schemas, fact computers, and block types.

A single ToolDefinition entry replaces the three parallel structures that
previously lived across faketor.py (FAKETOR_TOOLS, TOOL_TO_BLOCK_TYPE) and
facts.py (_FACT_COMPUTERS).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypedDict

logger = logging.getLogger(__name__)

# Anthropic tool input_schema dict — kept untyped to match the API's
# own JSON Schema pass-through.
InputSchema = dict[str, Any]


class ToolSchema(TypedDict):
    """Matches the Anthropic tool dict format exactly."""

    name: str
    description: str
    input_schema: InputSchema


# Callable that transforms a raw tool result into verified facts.
# Signature: (result_data: dict | list) -> dict
FactComputer = Callable[[dict | list], dict]


class _ToolDefinitionRequired(TypedDict):
    """Required fields for a tool definition."""

    name: str
    description: str
    input_schema: InputSchema


class ToolDefinition(_ToolDefinitionRequired, total=False):
    """Complete per-tool record owned by the registry."""

    block_type: str | None  # None = no frontend block rendered
    fact_computer: FactComputer | None  # None = no fact enrichment


class ToolRegistry:
    """Central store for all Faketor tool metadata.

    Usage — bulk registration (existing tools)::

        registry.register_many([ToolDefinition(...), ...])

    Usage — decorator registration (Phase F gap tools)::

        @registry.register(
            name="rent_vs_buy",
            description="...",
            input_schema={...},
            block_type="rent_vs_buy_card",
        )
        def compute_rent_vs_buy_facts(data: dict) -> dict:
            ...

    Consumers::

        registry.get_tool_schemas()      -> list[ToolSchema]  (Anthropic API)
        registry.get_block_type(name)    -> str | None         (frontend)
        registry.get_fact_computer(name) -> FactComputer|None  (enrichment)
        registry.names                   -> frozenset[str]
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register_many(self, tools: list[ToolDefinition]) -> None:
        """Bulk-register tool definitions (used by definitions.py)."""
        for defn in tools:
            name = defn["name"]
            if name in self._tools:
                logger.warning(
                    "ToolRegistry: duplicate registration for %r — overwriting", name
                )
            self._tools[name] = defn

    def register(
        self,
        *,
        name: str,
        description: str,
        input_schema: InputSchema,
        block_type: str | None = None,
    ) -> Callable[[FactComputer], FactComputer]:
        """Decorator that registers a fact-computer function as a tool.

        Example::

            @registry.register(
                name="rent_vs_buy",
                description="Compare renting vs buying...",
                input_schema={"type": "object", "properties": {...}},
                block_type="rent_vs_buy_card",
            )
            def _compute_rent_vs_buy_facts(data: dict) -> dict:
                return {...}
        """

        def decorator(fn: FactComputer) -> FactComputer:
            self._tools[name] = ToolDefinition(
                name=name,
                description=description,
                input_schema=input_schema,
                block_type=block_type,
                fact_computer=fn,
            )
            return fn

        return decorator

    # ------------------------------------------------------------------
    # Consumer API
    # ------------------------------------------------------------------

    def get_tool_schemas(self) -> list[ToolSchema]:
        """Return the list of tool dicts for the Anthropic API."""
        return [
            ToolSchema(
                name=d["name"],
                description=d["description"],
                input_schema=d["input_schema"],
            )
            for d in self._tools.values()
        ]

    def get_block_type(self, tool_name: str) -> str | None:
        """Return the frontend block type for a tool, or None."""
        defn = self._tools.get(tool_name)
        return defn.get("block_type") if defn else None

    def get_fact_computer(self, tool_name: str) -> FactComputer | None:
        """Return the fact-computer callable for a tool, or None."""
        defn = self._tools.get(tool_name)
        return defn.get("fact_computer") if defn else None

    @property
    def names(self) -> frozenset[str]:
        """Return the set of all registered tool names."""
        return frozenset(self._tools)

    def __len__(self) -> int:
        return len(self._tools)
