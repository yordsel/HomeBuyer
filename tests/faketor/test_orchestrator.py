"""Tests for TurnOrchestrator — the 9-step pipeline.

Phase E-6 (#50) of Epic #23.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from homebuyer.services.faketor.classification import (
    STRETCHER,
    SegmentClassifier,
    SegmentResult,
)
from homebuyer.services.faketor.extraction import SignalExtractor
from homebuyer.services.faketor.orchestrator import (
    TurnMetrics,
    TurnOrchestrator,
    TurnResult,
)
from homebuyer.services.faketor.state.buyer import BuyerProfile
from homebuyer.services.faketor.state.context import ResearchContext, ResearchContextStore
from homebuyer.services.faketor.state.market import BerkeleyWideMetrics, MarketSnapshot
from homebuyer.services.faketor.tools.executor import ToolExecutor, ToolResult as ExecToolResult
from homebuyer.services.faketor.tools.preexecution import PreExecutionResult, PreExecutor
from homebuyer.services.faketor.tools.registry import ToolDefinition, ToolRegistry


# ---------------------------------------------------------------------------
# Mocks / Fixtures
# ---------------------------------------------------------------------------


def _make_context(user_id: str = "test-user") -> ResearchContext:
    ctx = ResearchContext(user_id=user_id)
    ctx.market = MarketSnapshot(
        mortgage_rate_30yr=6.5,
        berkeley_wide=BerkeleyWideMetrics(median_sale_price=1_300_000),
    )
    ctx.buyer.profile = BuyerProfile(intent="occupy", capital=100_000)
    return ctx


def _make_context_store(context: ResearchContext | None = None) -> ResearchContextStore:
    ctx = context or _make_context()
    store = MagicMock(spec=ResearchContextStore)
    store.load_or_create = AsyncMock(return_value=ctx)
    store.save = AsyncMock()
    return store


def _make_extractor() -> SignalExtractor:
    extractor = MagicMock(spec=SignalExtractor)
    extractor.extract.return_value = None  # No signals extracted
    extractor.extract_from_output.return_value = None
    return extractor


def _make_classifier() -> SegmentClassifier:
    classifier = MagicMock(spec=SegmentClassifier)
    classifier.classify.return_value = SegmentResult(
        segment_id=STRETCHER,
        confidence=0.75,
        reasoning="test",
        factor_coverage=0.5,
    )
    return classifier


def _make_tool_executor() -> ToolExecutor:
    executor = MagicMock(spec=ToolExecutor)
    executor.execute.return_value = ExecToolResult(
        tool_name="test_tool",
        tool_input={},
        result_str='{"result": "ok"}',
        result_data={"result": "ok"},
    )
    return executor


def _make_pre_executor() -> PreExecutor:
    pre = MagicMock(spec=PreExecutor)
    pre.execute.return_value = PreExecutionResult()
    return pre


def _make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_many([
        ToolDefinition(
            name="lookup_property",
            description="Look up property",
            input_schema={"type": "object", "properties": {}},
        ),
    ])
    return registry


@dataclass
class MockTextBlock:
    type: str = "text"
    text: str = "Here is my analysis."


@dataclass
class MockToolUseBlock:
    type: str = "tool_use"
    id: str = "tool_use_1"
    name: str = "lookup_property"
    input: dict = None

    def __post_init__(self):
        if self.input is None:
            self.input = {"address": "123 Main St"}


def _make_claude_response(text: str = "Here is my analysis.", tools: list | None = None):
    """Create a mock Claude API response."""
    content = []
    if text:
        content.append(MockTextBlock(text=text))
    if tools:
        content.extend(tools)
    response = MagicMock()
    response.content = content
    response.stop_reason = "end_turn"
    return response


def _make_client(responses: list | None = None):
    """Create a mock Anthropic client."""
    client = MagicMock()
    if responses:
        client.messages.create.side_effect = responses
    else:
        client.messages.create.return_value = _make_claude_response()
    return client


def _make_orchestrator(**overrides) -> TurnOrchestrator:
    defaults = {
        "client": _make_client(),
        "context_store": _make_context_store(),
        "signal_extractor": _make_extractor(),
        "segment_classifier": _make_classifier(),
        "tool_executor": _make_tool_executor(),
        "pre_executor": _make_pre_executor(),
        "registry": _make_registry(),
    }
    defaults.update(overrides)
    return TurnOrchestrator(**defaults)


# ---------------------------------------------------------------------------
# TurnMetrics tests
# ---------------------------------------------------------------------------


class TestTurnMetrics:
    def test_to_dict(self):
        m = TurnMetrics(extraction_ms=1.23, total_ms=100.456, tools_used=["a"])
        d = m.to_dict()
        assert d["extraction_ms"] == 1.2
        assert d["total_ms"] == 100.5
        assert d["tools_used"] == ["a"]


class TestTurnResult:
    def test_to_dict_success(self):
        r = TurnResult(reply="Hello", tool_calls=[{"name": "t"}], blocks=[])
        d = r.to_dict()
        assert d["reply"] == "Hello"
        assert len(d["tool_calls"]) == 1

    def test_to_dict_error(self):
        r = TurnResult(error="something broke")
        d = r.to_dict()
        assert d == {"error": "something broke"}


# ---------------------------------------------------------------------------
# TurnOrchestrator non-streaming tests
# ---------------------------------------------------------------------------


class TestTurnOrchestratorRun:
    @pytest.fixture
    def orchestrator(self):
        return _make_orchestrator()

    @pytest.mark.asyncio
    async def test_basic_run(self, orchestrator):
        result = await orchestrator.run("user1", "Hello", [])
        assert result.reply == "Here is my analysis."
        assert result.error is None

    @pytest.mark.asyncio
    async def test_loads_context(self):
        store = _make_context_store()
        orch = _make_orchestrator(context_store=store)
        await orch.run("user1", "Hello", [])
        store.load_or_create.assert_called_once_with("user1")

    @pytest.mark.asyncio
    async def test_persists_context(self):
        store = _make_context_store()
        orch = _make_orchestrator(context_store=store)
        await orch.run("user1", "Hello", [])
        store.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_extracts_signals(self):
        extractor = _make_extractor()
        orch = _make_orchestrator(signal_extractor=extractor)
        await orch.run("user1", "I have $200k for a down payment", [])
        extractor.extract.assert_called_once_with("I have $200k for a down payment")

    @pytest.mark.asyncio
    async def test_classifies_segment(self):
        classifier = _make_classifier()
        orch = _make_orchestrator(segment_classifier=classifier)
        await orch.run("user1", "Hello", [])
        classifier.classify.assert_called()

    @pytest.mark.asyncio
    async def test_pre_executes(self):
        pre = _make_pre_executor()
        orch = _make_orchestrator(pre_executor=pre)
        await orch.run("user1", "Hello", [])
        pre.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_tool_use(self):
        """Orchestrator handles tool use blocks from Claude."""
        tool_block = MockToolUseBlock()
        response1 = _make_claude_response(text="", tools=[tool_block])
        response1.stop_reason = "tool_use"
        response2 = _make_claude_response(text="Done with analysis.")

        client = _make_client([response1, response2])
        tool_executor = _make_tool_executor()
        orch = _make_orchestrator(client=client, tool_executor=tool_executor)

        result = await orch.run("user1", "Look up 123 Main St", [])
        assert result.reply == "Done with analysis."
        tool_executor.execute.assert_called_once()
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "lookup_property"

    @pytest.mark.asyncio
    async def test_api_error_handled(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("API down")
        orch = _make_orchestrator(client=client)

        result = await orch.run("user1", "Hello", [])
        assert result.error is not None
        assert "API" in result.error

    @pytest.mark.asyncio
    async def test_metrics_populated(self, orchestrator):
        result = await orchestrator.run("user1", "Hello", [])
        m = result.metrics
        assert m.total_ms > 0
        assert m.llm_iterations >= 1

    @pytest.mark.asyncio
    async def test_extraction_failure_nonfatal(self):
        """Extraction failure doesn't prevent the turn from completing."""
        extractor = _make_extractor()
        extractor.extract.side_effect = RuntimeError("extraction broke")
        orch = _make_orchestrator(signal_extractor=extractor)
        result = await orch.run("user1", "Hello", [])
        assert result.error is None
        assert result.reply == "Here is my analysis."

    @pytest.mark.asyncio
    async def test_classification_failure_nonfatal(self):
        classifier = _make_classifier()
        classifier.classify.side_effect = RuntimeError("classification broke")
        orch = _make_orchestrator(segment_classifier=classifier)
        result = await orch.run("user1", "Hello", [])
        assert result.error is None

    @pytest.mark.asyncio
    async def test_post_process_extracts_from_output(self):
        extractor = _make_extractor()
        orch = _make_orchestrator(signal_extractor=extractor)
        await orch.run("user1", "Hello", [])
        extractor.extract_from_output.assert_called_once()

    @pytest.mark.asyncio
    async def test_discussed_properties_tracked(self):
        tool_block = MockToolUseBlock()
        response1 = _make_claude_response(text="", tools=[tool_block])
        response1.stop_reason = "tool_use"
        response2 = _make_claude_response(text="Done.")

        client = _make_client([response1, response2])

        tool_executor = _make_tool_executor()
        tool_executor.execute.return_value = ExecToolResult(
            tool_name="lookup_property",
            tool_input={},
            result_str='{}',
            result_data={"property_id": 42, "address": "123 Main"},
            discussed_property_id=42,
            discussed_address="123 Main",
        )
        orch = _make_orchestrator(client=client, tool_executor=tool_executor)
        result = await orch.run("user1", "Look up 123 Main", [])
        assert 42 in result.discussed_properties


# ---------------------------------------------------------------------------
# TurnOrchestrator streaming tests
# ---------------------------------------------------------------------------


class TestTurnOrchestratorStream:
    @pytest.mark.asyncio
    async def test_stream_yields_done(self):
        """Stream always ends with a done event."""
        # Use mock that supports stream context manager
        client = MagicMock()
        stream_mock = MagicMock()
        stream_mock.__enter__ = MagicMock(return_value=stream_mock)
        stream_mock.__exit__ = MagicMock(return_value=False)
        stream_mock.get_final_message.return_value = _make_claude_response()
        client.messages.stream.return_value = stream_mock

        orch = _make_orchestrator(client=client)
        events = []
        async for event in orch.run_stream("user1", "Hello", []):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "done" in event_types
        done_event = next(e for e in events if e["event"] == "done")
        assert "reply" in done_event["data"]

    @pytest.mark.asyncio
    async def test_stream_error_event(self):
        """API error yields error event."""
        client = MagicMock()
        stream_mock = MagicMock()
        stream_mock.__enter__ = MagicMock(side_effect=Exception("Stream broke"))
        stream_mock.__exit__ = MagicMock(return_value=False)
        client.messages.stream.return_value = stream_mock

        orch = _make_orchestrator(client=client)
        events = []
        async for event in orch.run_stream("user1", "Hello", []):
            events.append(event)

        assert any(e["event"] == "error" for e in events)
