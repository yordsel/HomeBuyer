"""Tests for typed ToolExecutor wrapper.

Phase E-5 (#49) of Epic #23.
"""

import json

from homebuyer.services.faketor.tools.executor import (
    ToolExecutor,
    ToolResult,
    _extract_discussed_property,
    _safe_json_dumps,
)
from homebuyer.services.faketor.tools.registry import ToolDefinition, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(tools: list[ToolDefinition] | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    if tools:
        registry.register_many(tools)
    return registry


def _make_raw_executor(responses: dict[str, str | dict] | None = None):
    """Create a mock raw executor returning canned responses."""
    responses = responses or {}

    def executor(tool_name: str, tool_input: dict) -> str:
        resp = responses.get(tool_name, json.dumps({"result": "ok"}))
        if isinstance(resp, dict):
            return json.dumps(resp)
        return resp

    return executor


def _make_failing_executor(error_msg: str = "boom"):
    def executor(tool_name: str, tool_input: dict) -> str:
        raise RuntimeError(error_msg)
    return executor


# ---------------------------------------------------------------------------
# ToolResult tests
# ---------------------------------------------------------------------------


class TestToolResult:
    def test_has_facts_false(self):
        r = ToolResult(tool_name="t", tool_input={})
        assert r.has_facts is False

    def test_has_facts_true(self):
        r = ToolResult(tool_name="t", tool_input={}, facts={"key": "val"})
        assert r.has_facts is True

    def test_has_facts_empty_dict(self):
        r = ToolResult(tool_name="t", tool_input={}, facts={})
        assert r.has_facts is False

    def test_has_block_false(self):
        r = ToolResult(tool_name="t", tool_input={})
        assert r.has_block is False

    def test_has_block_true(self):
        r = ToolResult(
            tool_name="t",
            tool_input={},
            block_type="card",
            block_data={"a": 1},
        )
        assert r.has_block is True

    def test_to_anthropic_result(self):
        r = ToolResult(tool_name="t", tool_input={}, result_str='{"x":1}')
        anthropic = r.to_anthropic_result("use_123")
        assert anthropic["type"] == "tool_result"
        assert anthropic["tool_use_id"] == "use_123"
        assert anthropic["content"] == '{"x":1}'

    def test_to_block_none(self):
        r = ToolResult(tool_name="t", tool_input={})
        assert r.to_block() is None

    def test_to_block_with_data(self):
        r = ToolResult(
            tool_name="lookup_property",
            tool_input={},
            block_type="property_card",
            block_data={"price": 1_000_000},
        )
        block = r.to_block()
        assert block is not None
        assert block["type"] == "property_card"
        assert block["tool_name"] == "lookup_property"
        assert block["data"]["price"] == 1_000_000


# ---------------------------------------------------------------------------
# ToolExecutor tests
# ---------------------------------------------------------------------------


class TestToolExecutor:
    def test_basic_execution(self):
        raw = _make_raw_executor({"test_tool": {"value": 42}})
        executor = ToolExecutor(raw, _make_registry())
        result = executor.execute("test_tool", {"arg": "val"})
        assert result.tool_name == "test_tool"
        assert result.tool_input == {"arg": "val"}
        assert result.result_data == {"value": 42}
        assert not result.is_error

    def test_exception_handling(self):
        executor = ToolExecutor(_make_failing_executor("tool broke"), _make_registry())
        result = executor.execute("test_tool", {})
        assert result.is_error is True
        assert result.error_message == "tool broke"
        assert "error" in result.result_str

    def test_error_response_detected(self):
        raw = _make_raw_executor({"test_tool": {"error": "Not found"}})
        executor = ToolExecutor(raw, _make_registry())
        result = executor.execute("test_tool", {})
        assert result.is_error is True
        assert result.error_message == "Not found"

    def test_non_json_response(self):
        raw = _make_raw_executor({"test_tool": "not json {{{"})
        executor = ToolExecutor(raw, _make_registry())
        result = executor.execute("test_tool", {})
        assert result.result_data is None
        assert not result.is_error

    def test_block_created_for_registered_tool(self):
        registry = _make_registry([
            ToolDefinition(
                name="lookup_property",
                description="Look up a property",
                input_schema={"type": "object"},
                block_type="property_card",
            )
        ])
        raw = _make_raw_executor({
            "lookup_property": {"address": "123 Main St", "price": 1_000_000}
        })
        executor = ToolExecutor(raw, registry)
        result = executor.execute("lookup_property", {"address": "123 Main St"})
        assert result.block_type == "property_card"
        assert result.block_data is not None
        assert result.block_data["price"] == 1_000_000

    def test_no_block_for_unregistered_tool(self):
        executor = ToolExecutor(
            _make_raw_executor({"unknown": {"data": 1}}),
            _make_registry(),
        )
        result = executor.execute("unknown", {})
        assert result.block_type is None

    def test_no_block_for_error_response(self):
        registry = _make_registry([
            ToolDefinition(
                name="test_tool",
                description="t",
                input_schema={"type": "object"},
                block_type="card",
            )
        ])
        raw = _make_raw_executor({"test_tool": {"error": "fail"}})
        executor = ToolExecutor(raw, registry)
        result = executor.execute("test_tool", {})
        assert result.block_type is None

    def test_facts_stripped_from_block_data(self):
        """_facts should not appear in block data sent to frontend."""
        registry = _make_registry([
            ToolDefinition(
                name="get_price_prediction",
                description="predict price",
                input_schema={"type": "object"},
                block_type="prediction_card",
            )
        ])
        # The tool result won't have _facts initially — the executor adds them.
        # But even if the raw result somehow has _facts, block_data excludes it.
        raw = _make_raw_executor({
            "get_price_prediction": {
                "predicted_price": 1_200_000,
                "_facts": {"should_not_appear": True},
            }
        })
        executor = ToolExecutor(raw, registry)
        result = executor.execute("get_price_prediction", {})
        if result.block_data:
            assert "_facts" not in result.block_data


# ---------------------------------------------------------------------------
# _extract_discussed_property tests
# ---------------------------------------------------------------------------


class TestExtractDiscussedProperty:
    def test_extracts_property_id(self):
        result = ToolResult(
            tool_name="lookup_property",
            tool_input={},
            result_data={"property_id": 123, "address": "456 Elm St"},
        )
        _extract_discussed_property(result)
        assert result.discussed_property_id == 123
        assert result.discussed_address == "456 Elm St"

    def test_ignores_non_property_tools(self):
        result = ToolResult(
            tool_name="get_market_summary",
            tool_input={},
            result_data={"property_id": 123},
        )
        _extract_discussed_property(result)
        assert result.discussed_property_id is None

    def test_ignores_error_results(self):
        result = ToolResult(
            tool_name="lookup_property",
            tool_input={},
            result_data={"error": "not found"},
            is_error=True,
        )
        _extract_discussed_property(result)
        assert result.discussed_property_id is None

    def test_handles_string_property_id(self):
        result = ToolResult(
            tool_name="lookup_property",
            tool_input={},
            result_data={"property_id": "42"},
        )
        _extract_discussed_property(result)
        assert result.discussed_property_id == 42

    def test_handles_non_dict_result(self):
        result = ToolResult(
            tool_name="lookup_property",
            tool_input={},
            result_data=[1, 2, 3],
        )
        _extract_discussed_property(result)
        assert result.discussed_property_id is None


# ---------------------------------------------------------------------------
# _safe_json_dumps tests
# ---------------------------------------------------------------------------


class TestSafeJsonDumps:
    def test_normal_dict(self):
        result = _safe_json_dumps({"a": 1})
        assert json.loads(result) == {"a": 1}

    def test_non_serializable_uses_str(self):
        from datetime import datetime
        result = _safe_json_dumps({"ts": datetime(2025, 1, 1)})
        parsed = json.loads(result)
        assert "2025" in parsed["ts"]
