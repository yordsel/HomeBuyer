"""Integration tests for the full TurnOrchestrator pipeline with mocked LLM.

Tests end-to-end flows through all 9 steps using mock components:
- Stretcher conversation
- Competitive Bidder conversation
- Segment transition mid-conversation
- Pre-execution with proactive analyses
- Context persistence across turns

Phase E-9 (#53) of Epic #23.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from homebuyer.services.faketor.classification import (
    COMPETITIVE_BIDDER,
    FIRST_TIME_BUYER,
    STRETCHER,
    SegmentClassifier,
    SegmentResult,
)
from homebuyer.services.faketor.extraction import (
    SignalExtractor,
)
from homebuyer.services.faketor.orchestrator import TurnOrchestrator
from homebuyer.services.faketor.state.buyer import BuyerProfile
from homebuyer.services.faketor.state.context import ResearchContext, ResearchContextStore
from homebuyer.services.faketor.state.market import BerkeleyWideMetrics, MarketSnapshot
from homebuyer.services.faketor.state.property import FocusProperty, PropertyState
from homebuyer.services.faketor.tools.executor import ToolExecutor
from homebuyer.services.faketor.tools.preexecution import PreExecutionResult, PreExecutor
from homebuyer.services.faketor.tools.registry import ToolDefinition, ToolRegistry


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


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


def _make_claude_response(text: str = "Here is my analysis.", tools: list = None):
    content = []
    if text:
        content.append(MockTextBlock(text=text))
    if tools:
        content.extend(tools)
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = "end_turn"
    return resp


def _make_client(responses: list = None):
    client = MagicMock()
    if responses:
        client.messages.create.side_effect = responses
    else:
        client.messages.create.return_value = _make_claude_response()
    return client


def _make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_many([
        ToolDefinition(
            name="lookup_property",
            description="Look up property",
            input_schema={"type": "object", "properties": {}},
            block_type="property_card",
        ),
        ToolDefinition(
            name="get_price_prediction",
            description="Predict price",
            input_schema={"type": "object", "properties": {}},
            block_type="prediction_card",
        ),
        ToolDefinition(
            name="get_comparable_sales",
            description="Get comp sales",
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="get_market_summary",
            description="Market summary",
            input_schema={"type": "object", "properties": {}},
        ),
    ])
    return registry


def _make_tool_executor(registry: ToolRegistry = None) -> ToolExecutor:
    """Create a ToolExecutor with a mock raw executor."""
    import json
    reg = registry or _make_registry()

    def raw_executor(name: str, inp: dict) -> str:
        return json.dumps({"result": "ok", "tool": name})

    return ToolExecutor(raw_executor, reg)


def _make_pre_executor() -> PreExecutor:
    """Create a mock PreExecutor."""
    pre = MagicMock(spec=PreExecutor)
    pre.execute.return_value = PreExecutionResult()
    return pre


def _make_pre_executor_with_facts() -> PreExecutor:
    """Create a PreExecutor that returns pre-computed facts."""
    pre = MagicMock(spec=PreExecutor)
    pre.execute.return_value = PreExecutionResult(
        facts={
            "get_price_prediction": {
                "predicted_price": "$1,200,000",
                "confidence": "medium",
            },
            "get_comparable_sales": {
                "comp_count": 5,
                "median_comp_price": "$1,150,000",
            },
        },
        raw_results={
            "get_price_prediction": {"predicted_price": 1_200_000},
            "get_comparable_sales": {"comp_count": 5},
        },
    )
    return pre


def _make_context(
    user_id: str = "test-user",
    segment_id: str | None = STRETCHER,
    confidence: float = 0.75,
    with_property: bool = False,
) -> ResearchContext:
    ctx = ResearchContext(user_id=user_id)
    ctx.market = MarketSnapshot(
        mortgage_rate_30yr=6.5,
        berkeley_wide=BerkeleyWideMetrics(
            median_sale_price=1_300_000,
            median_list_price=1_250_000,
            median_ppsf=850,
            median_dom=18,
        ),
    )
    ctx.buyer.profile = BuyerProfile(
        intent="occupy",
        capital=100_000,
        income=150_000,
        current_rent=2_800,
    )
    if segment_id:
        ctx.buyer.segment_id = segment_id
        ctx.buyer.segment_confidence = confidence
    if with_property:
        ctx.property = PropertyState()
        ctx.property.focus_property = FocusProperty(
            property_id=123,
            address="1234 Cedar St",
            property_context={"price": 1_200_000, "neighborhood": "North Berkeley"},
        )
    return ctx


def _make_store(context: ResearchContext = None) -> ResearchContextStore:
    ctx = context or _make_context()
    store = MagicMock(spec=ResearchContextStore)
    store.load_or_create = AsyncMock(return_value=ctx)
    store.save = AsyncMock()
    return store


def _make_extractor(
    segment_id: str | None = None,
) -> SignalExtractor:
    extractor = MagicMock(spec=SignalExtractor)
    extractor.extract.return_value = None
    extractor.extract_from_output.return_value = None
    return extractor


def _make_classifier(
    segment_id: str = STRETCHER,
    confidence: float = 0.75,
) -> SegmentClassifier:
    classifier = MagicMock(spec=SegmentClassifier)
    classifier.classify.return_value = SegmentResult(
        segment_id=segment_id,
        confidence=confidence,
        reasoning="test",
        factor_coverage=0.5,
    )
    return classifier


def _make_orchestrator(**overrides) -> TurnOrchestrator:
    registry = overrides.pop("registry", _make_registry())
    defaults = {
        "client": _make_client(),
        "context_store": _make_store(),
        "signal_extractor": _make_extractor(),
        "segment_classifier": _make_classifier(),
        "tool_executor": _make_tool_executor(registry),
        "pre_executor": _make_pre_executor(),
        "registry": registry,
    }
    defaults.update(overrides)
    return TurnOrchestrator(**defaults)


# ---------------------------------------------------------------------------
# Integration: Stretcher conversation
# ---------------------------------------------------------------------------


class TestStretcherConversation:
    """End-to-end turn for a Stretcher buyer."""

    @pytest.mark.asyncio
    async def test_stretcher_turn(self):
        """Full pipeline: extract, classify, resolve, assemble, LLM, post-process."""
        client = _make_client([
            _make_claude_response(
                "Based on your situation, this property at 1234 Cedar St "
                "would cost approximately $7,200/mo including taxes and insurance, "
                "compared to your current rent of $2,800. That's a significant "
                "jump. Let me break it down..."
            ),
        ])
        store = _make_store(_make_context(segment_id=STRETCHER, with_property=True))
        classifier = _make_classifier(STRETCHER, 0.75)

        orch = _make_orchestrator(
            client=client,
            context_store=store,
            segment_classifier=classifier,
        )

        result = await orch.run(
            user_id="test-user",
            message="Should I buy this house?",
            history=[],
            property_context={"address": "1234 Cedar St", "price": 1_200_000},
        )

        assert result.error is None
        assert len(result.reply) > 50
        assert "Cedar St" in result.reply or "7,200" in result.reply
        assert result.metrics.total_ms > 0

        # Context should have been saved
        store.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_stretcher_with_tool_use(self):
        """Stretcher turn with tool use — lookup_property then analysis."""
        tool_block = MockToolUseBlock(
            name="lookup_property",
            input={"address": "1234 Cedar St"},
        )
        response1 = _make_claude_response(text="", tools=[tool_block])
        response1.stop_reason = "tool_use"
        response2 = _make_claude_response(
            "This property is listed at $1.2M. Based on comps..."
        )

        client = _make_client([response1, response2])
        orch = _make_orchestrator(client=client)

        result = await orch.run(
            user_id="test-user",
            message="Tell me about 1234 Cedar St",
            history=[],
        )

        assert result.error is None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "lookup_property"


# ---------------------------------------------------------------------------
# Integration: Competitive Bidder conversation
# ---------------------------------------------------------------------------


class TestCompetitiveBidderConversation:
    @pytest.mark.asyncio
    async def test_competitive_bidder_turn(self):
        """Competitive Bidder gets bid calibration framing."""
        context = _make_context(
            segment_id=COMPETITIVE_BIDDER,
            confidence=0.85,
            with_property=True,
        )
        context.buyer.profile.capital = 400_000
        context.buyer.profile.income = 250_000

        store = _make_store(context)
        classifier = _make_classifier(COMPETITIVE_BIDDER, 0.85)
        client = _make_client([
            _make_claude_response(
                "Based on the comps, a rational bid range for this property "
                "would be $1.15M-$1.25M. The sale-to-list ratio in this "
                "neighborhood is 1.05, so expect competition."
            ),
        ])

        orch = _make_orchestrator(
            client=client,
            context_store=store,
            segment_classifier=classifier,
        )

        result = await orch.run(
            user_id="test-user",
            message="What should I bid on 1234 Cedar St?",
            history=[],
            property_context={"address": "1234 Cedar St", "price": 1_200_000},
        )

        assert result.error is None
        assert "bid" in result.reply.lower() or "comp" in result.reply.lower()
        store.save.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: Segment transition
# ---------------------------------------------------------------------------


class TestSegmentTransition:
    @pytest.mark.asyncio
    async def test_segment_changes_between_turns(self):
        """Two turns — first classified as STRETCHER, then as FIRST_TIME_BUYER."""
        context = _make_context(segment_id=None, confidence=0.0)

        # Track classification calls
        classify_calls = [0]

        def classify_side_effect(profile, market_or_rate):
            classify_calls[0] += 1
            if classify_calls[0] <= 2:
                # First turn (step 3 + step 8 reclassify): STRETCHER
                return SegmentResult(
                    segment_id=STRETCHER,
                    confidence=0.6,
                    reasoning="first turn",
                    factor_coverage=0.3,
                )
            else:
                # Second turn: FIRST_TIME_BUYER
                return SegmentResult(
                    segment_id=FIRST_TIME_BUYER,
                    confidence=0.8,
                    reasoning="second turn",
                    factor_coverage=0.5,
                )

        classifier = MagicMock(spec=SegmentClassifier)
        classifier.classify.side_effect = classify_side_effect

        store = _make_store(context)
        client = _make_client()  # Default response for both turns

        orch = _make_orchestrator(
            client=client,
            context_store=store,
            segment_classifier=classifier,
        )

        # Turn 1
        result1 = await orch.run(
            user_id="test-user",
            message="I'm looking to buy my first home",
            history=[],
        )
        assert result1.error is None

        # Turn 2 — classifier will return FIRST_TIME_BUYER
        result2 = await orch.run(
            user_id="test-user",
            message="I have $100k saved and make $150k/year",
            history=[{"role": "user", "content": "I'm looking to buy my first home"}],
        )
        assert result2.error is None
        # Classifier should have been called multiple times
        assert classifier.classify.call_count >= 4  # 2 per turn (classify + postprocess)


# ---------------------------------------------------------------------------
# Integration: Pre-execution with facts
# ---------------------------------------------------------------------------


class TestPreExecutionIntegration:
    @pytest.mark.asyncio
    async def test_pre_executed_facts_in_prompt(self):
        """Pre-executed facts should appear in the system prompt."""
        pre_executor = _make_pre_executor_with_facts()
        captured_system_prompts = []

        def capture_create(**kwargs):
            captured_system_prompts.append(kwargs.get("system", ""))
            return _make_claude_response("Analysis with pre-executed data.")

        client = MagicMock()
        client.messages.create.side_effect = capture_create

        orch = _make_orchestrator(
            client=client,
            pre_executor=pre_executor,
        )

        result = await orch.run(
            user_id="test-user",
            message="Analyze 1234 Cedar St",
            history=[],
            property_context={"address": "1234 Cedar St"},
        )

        assert result.error is None
        assert len(captured_system_prompts) > 0
        system_prompt = captured_system_prompts[0]
        assert "PRE-EXECUTED ANALYSIS RESULTS" in system_prompt
        assert "$1,200,000" in system_prompt

    @pytest.mark.asyncio
    async def test_pre_executor_receives_property_context(self):
        """PreExecutor.execute() receives the property context."""
        pre_executor = _make_pre_executor()
        orch = _make_orchestrator(pre_executor=pre_executor)

        await orch.run(
            user_id="test-user",
            message="What's this property worth?",
            history=[],
            property_context={"address": "1234 Cedar St", "price": 1_200_000},
        )

        pre_executor.execute.assert_called_once()
        call_args = pre_executor.execute.call_args
        assert call_args[1].get("property_context") or call_args[0][1]


# ---------------------------------------------------------------------------
# Integration: Context persistence
# ---------------------------------------------------------------------------


class TestContextPersistence:
    @pytest.mark.asyncio
    async def test_context_loaded_and_saved(self):
        """Context is loaded at start and saved at end of each turn."""
        store = _make_store()
        orch = _make_orchestrator(context_store=store)

        await orch.run("user-123", "Hello", [])

        store.load_or_create.assert_called_once_with("user-123")
        store.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_saved_even_on_error(self):
        """Context is persisted even if the LLM call fails."""
        client = MagicMock()
        client.messages.create.side_effect = Exception("API down")
        store = _make_store()
        orch = _make_orchestrator(client=client, context_store=store)

        result = await orch.run("user-123", "Hello", [])

        assert result.error is not None
        # Context should still be saved
        store.save.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: Streaming
# ---------------------------------------------------------------------------


class TestStreamingIntegration:
    @pytest.mark.asyncio
    async def test_stream_complete_flow(self):
        """Stream produces tool and done events in a full flow."""
        tool_block = MockToolUseBlock()
        response1 = _make_claude_response(text="", tools=[tool_block])
        response1.stop_reason = "tool_use"
        response2 = _make_claude_response("Final analysis.")

        # Mock streaming context manager
        client = MagicMock()
        call_count = [0]

        def stream_side_effect(**kwargs):
            call_count[0] += 1
            stream_mock = MagicMock()
            stream_mock.__enter__ = MagicMock(return_value=stream_mock)
            stream_mock.__exit__ = MagicMock(return_value=False)
            if call_count[0] == 1:
                stream_mock.get_final_message.return_value = response1
            else:
                stream_mock.get_final_message.return_value = response2
            return stream_mock

        client.messages.stream.side_effect = stream_side_effect

        orch = _make_orchestrator(client=client)

        events = []
        async for event in orch.run_stream("user-1", "Look up 123 Main", []):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "tool_start" in event_types
        assert "tool_end" in event_types
        assert "tool_result" in event_types
        assert "done" in event_types
