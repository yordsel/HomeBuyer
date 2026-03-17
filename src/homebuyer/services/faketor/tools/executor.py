"""Typed ToolExecutor wrapper for Faketor tool execution.

Wraps the existing raw string-based tool executor with a structured
ToolResult output that carries parsed data, facts, block info, and
metadata about working set / property state changes.

This is the boundary between the raw tool execution layer (api.py's
_faketor_tool_executor + session wrapping) and the new orchestrator
pipeline that needs structured, typed outputs.

Phase E-5 (#49) of Epic #23.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from homebuyer.services.faketor.facts import compute_facts_for_tool
from homebuyer.services.faketor.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Type alias: raw tool executor from api.py
# Signature: (tool_name: str, tool_input: dict) -> str (JSON)
RawToolExecutorFn = Callable[[str, dict[str, Any]], str]


@dataclass
class ToolResult:
    """Structured result from a single tool execution.

    Replaces the raw JSON string that previously flowed through the
    system with a typed container that carries all the metadata the
    orchestrator needs.
    """

    tool_name: str
    tool_input: dict[str, Any]

    # Raw JSON string (for Anthropic message API compatibility)
    result_str: str = ""

    # Parsed result data (dict or list), None if parse failed
    result_data: Any = None

    # Computed facts for prompt enrichment (from compute_facts_for_tool)
    facts: dict | None = None

    # Frontend block info
    block_type: str | None = None
    block_data: Any = None

    # Error info
    is_error: bool = False
    error_message: str | None = None

    # Metadata: property discussed (for tracking)
    discussed_property_id: int | None = None
    discussed_address: str | None = None

    @property
    def has_facts(self) -> bool:
        return self.facts is not None and bool(self.facts)

    @property
    def has_block(self) -> bool:
        return self.block_type is not None and self.block_data is not None

    def to_anthropic_result(self, tool_use_id: str) -> dict:
        """Format as an Anthropic tool_result message content block."""
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": self.result_str,
        }

    def to_block(self) -> dict | None:
        """Format as a frontend block dict, or None if no block."""
        if not self.has_block:
            return None
        return {
            "type": self.block_type,
            "tool_name": self.tool_name,
            "data": self.block_data,
        }


class ToolExecutor:
    """Typed wrapper around the raw tool executor.

    Produces ToolResult objects with parsed data, facts, blocks, and
    error handling — everything the TurnOrchestrator needs without
    duplicating the parsing/enrichment logic that was previously
    scattered across the chat/chat_stream methods.

    Usage::

        executor = ToolExecutor(raw_executor_fn, registry)
        result = executor.execute("get_price_prediction", {"address": "..."})
        if result.has_facts:
            accumulator.record(result.tool_name, result.tool_input, result.facts)
    """

    def __init__(
        self,
        raw_executor: RawToolExecutorFn,
        registry: ToolRegistry,
    ) -> None:
        self._raw_executor = raw_executor
        self._registry = registry

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> ToolResult:
        """Execute a tool and return a structured ToolResult.

        This method:
        1. Calls the raw executor (which handles session state, working set, etc.)
        2. Parses the JSON result
        3. Checks for error responses
        4. Computes facts for prompt enrichment
        5. Builds frontend block data
        6. Extracts discussed property info
        """
        result = ToolResult(tool_name=tool_name, tool_input=tool_input)

        # Execute the raw tool
        try:
            result.result_str = self._raw_executor(tool_name, tool_input)
        except Exception as e:
            logger.warning("Tool %s failed: %s", tool_name, e)
            result.result_str = json.dumps({"error": str(e)})
            result.is_error = True
            result.error_message = str(e)
            return result

        # Parse JSON result
        try:
            result.result_data = json.loads(result.result_str)
        except (json.JSONDecodeError, TypeError):
            # Non-JSON result — return as-is without enrichment
            return result

        # Check for error responses
        if isinstance(result.result_data, dict) and result.result_data.get("error"):
            result.is_error = True
            result.error_message = str(result.result_data["error"])
            return result

        # Compute facts for prompt enrichment
        if isinstance(result.result_data, (dict, list)):
            facts = compute_facts_for_tool(tool_name, result.result_data)
            if facts:
                result.facts = facts
                # Inject _facts into result for Claude's context
                if isinstance(result.result_data, dict):
                    enriched = {**result.result_data, "_facts": facts}
                    result.result_str = _safe_json_dumps(enriched)

        # Build frontend block
        block_type = self._registry.get_block_type(tool_name)
        if block_type and result.result_data is not None and not result.is_error:
            result.block_type = block_type
            if isinstance(result.result_data, dict):
                result.block_data = {
                    k: v for k, v in result.result_data.items() if k != "_facts"
                }
            else:
                result.block_data = result.result_data

        # Extract discussed property info
        _extract_discussed_property(result)

        return result


# Per-property tools that reference a specific property
_PER_PROPERTY_TOOLS = frozenset({
    "lookup_property",
    "get_price_prediction",
    "get_comparable_sales",
    "get_development_potential",
    "estimate_rental_income",
    "lookup_permits",
    "analyze_investment_scenarios",
})


def _extract_discussed_property(result: ToolResult) -> None:
    """Extract property ID and address from per-property tool results."""
    if result.tool_name not in _PER_PROPERTY_TOOLS:
        return
    if not isinstance(result.result_data, dict) or result.is_error:
        return

    # Try to extract property_id
    prop_id = result.result_data.get("property_id")
    if prop_id is not None:
        try:
            result.discussed_property_id = int(prop_id)
        except (ValueError, TypeError):
            pass

    # Try to extract address
    address = result.result_data.get("address")
    if address and isinstance(address, str):
        result.discussed_address = address


def _safe_json_dumps(data: Any) -> str:
    """JSON serialize with fallback for non-serializable types."""
    try:
        return json.dumps(data, default=str)
    except (TypeError, ValueError):
        return json.dumps({"error": "Serialization failed"})
