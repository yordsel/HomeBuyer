"""Orchestrator eval runner.

Tests orchestrator response quality against YAML scenarios. Two modes:
- Mock (default): Tests the eval harness using mocked orchestrator components.
- Live (EVAL_MODE=live): Runs real orchestrator with real API calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homebuyer.services.faketor.classification import (
    SegmentClassifier,
    SegmentResult,
)
from homebuyer.services.faketor.extraction import SignalExtractor
from homebuyer.services.faketor.orchestrator import TurnOrchestrator
from homebuyer.services.faketor.state.buyer import BuyerProfile
from homebuyer.services.faketor.state.context import ResearchContext, ResearchContextStore
from homebuyer.services.faketor.state.market import BerkeleyWideMetrics, MarketSnapshot
from homebuyer.services.faketor.tools.executor import ToolExecutor, ToolResult as ExecToolResult
from homebuyer.services.faketor.tools.preexecution import PreExecutionResult, PreExecutor
from homebuyer.services.faketor.tools.registry import ToolDefinition, ToolRegistry

from tests.evals.conftest import EVAL_MODE, OrchestratorScenario
from tests.evals.graders import (
    ResponseQualityGrade,
    grade_response_quality,
    grade_tool_selection,
)
from tests.evals.metrics import (
    OrchestratorMetrics,
    OrchestratorScenarioResult,
    OrchestratorTurnResult,
    compute_orchestrator_metrics,
)
from tests.evals.report import format_orchestrator_report
from tests.evals.results import EvalResultStore


# ---------------------------------------------------------------------------
# Mock helpers (reused from test_orchestrator.py patterns)
# ---------------------------------------------------------------------------


class _MockTextBlock:
    def __init__(self, text: str = "Here is my analysis."):
        self.type = "text"
        self.text = text


class _MockToolUseBlock:
    def __init__(self, name: str = "get_market_summary", input: dict | None = None):
        self.type = "tool_use"
        self.id = f"tool_use_{name}"
        self.name = name
        self.input = input or {}


def _make_mock_context(segment: str = "first_time_buyer") -> ResearchContext:
    ctx = ResearchContext(user_id="eval-test-user")
    ctx.market = MarketSnapshot(
        mortgage_rate_30yr=6.5,
        berkeley_wide=BerkeleyWideMetrics(median_sale_price=1_300_000),
    )
    ctx.buyer.profile = BuyerProfile(intent="occupy", capital=100_000)
    if segment:
        ctx.buyer.segment_id = segment
        ctx.buyer.segment_confidence = 0.75
    return ctx


def _make_mock_orchestrator(
    response_text: str = "Here is my analysis based on the data.",
    tools_called: list[str] | None = None,
) -> TurnOrchestrator:
    """Create a mock orchestrator that returns predictable responses."""
    # Build response content
    content = []
    tool_blocks = []
    if tools_called:
        for name in tools_called:
            tool_blocks.append(_MockToolUseBlock(name=name))
    content.append(_MockTextBlock(text=response_text))

    # Client mock
    client = MagicMock()
    if tool_blocks:
        # First response: tool calls, second: text
        tool_response = MagicMock()
        tool_response.content = list(tool_blocks)
        tool_response.stop_reason = "tool_use"

        text_response = MagicMock()
        text_response.content = [_MockTextBlock(text=response_text)]
        text_response.stop_reason = "end_turn"

        client.messages.create.side_effect = [tool_response, text_response]
    else:
        response = MagicMock()
        response.content = content
        response.stop_reason = "end_turn"
        client.messages.create.return_value = response

    # Context store
    ctx_store = MagicMock(spec=ResearchContextStore)
    ctx_store.load_or_create = AsyncMock(return_value=_make_mock_context())
    ctx_store.persist = AsyncMock()

    # Signal extractor
    extractor = MagicMock(spec=SignalExtractor)
    extractor.extract.return_value = None
    extractor.extract_from_output.return_value = None

    # Classifier
    classifier = MagicMock(spec=SegmentClassifier)
    classifier.classify.return_value = SegmentResult(
        segment_id="first_time_buyer", confidence=0.75,
        reasoning="test", factor_coverage=0.5,
    )

    # Tool executor
    tool_executor = MagicMock(spec=ToolExecutor)
    tool_executor.execute.return_value = ExecToolResult(
        tool_name="mock_tool", tool_input={},
        result_str='{"result": "ok"}', result_data={"result": "ok"},
    )

    # Pre-executor
    pre_executor = MagicMock(spec=PreExecutor)
    pre_executor.execute.return_value = PreExecutionResult()

    # Registry
    registry = ToolRegistry()
    registry.register_many([
        ToolDefinition(
            name="get_market_summary", description="Get market summary",
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="lookup_property", description="Look up property",
            input_schema={"type": "object", "properties": {}},
        ),
    ])

    return TurnOrchestrator(
        client=client,
        context_store=ctx_store,
        signal_extractor=extractor,
        segment_classifier=classifier,
        tool_executor=tool_executor,
        pre_executor=pre_executor,
        registry=registry,
    )


# ---------------------------------------------------------------------------
# Mock mode tests
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestOrchestratorEvalMock:
    """Test the orchestrator eval harness using mocked components."""

    def test_scenarios_load(self, orchestrator_scenarios):
        """Verify scenarios load from YAML."""
        assert len(orchestrator_scenarios) > 0, "No orchestrator scenarios found"

    def test_all_scenarios_have_turns(self, orchestrator_scenarios):
        """Every scenario must have at least one turn."""
        for s in orchestrator_scenarios:
            assert len(s.turns) > 0, f"Scenario {s.id} has no turns"

    @pytest.mark.asyncio
    async def test_mock_grading_pipeline(self, orchestrator_scenarios):
        """Run all scenarios in mock mode and verify grading works."""
        results = []

        for scenario in orchestrator_scenarios:
            turn_results = []
            for turn in scenario.turns:
                # Use mock orchestrator with expected tools
                orch = _make_mock_orchestrator(
                    tools_called=turn.expected_tools[:1] if turn.expected_tools else None,
                )
                result = await orch.run(
                    message=turn.message,
                    user_id="eval-test-user",
                    history=[],
                )

                tools_used = [tc["name"] for tc in result.tool_calls]
                tool_grade = grade_tool_selection(
                    tools_used, turn.expected_tools, turn.forbidden_tools,
                )

                turn_results.append(OrchestratorTurnResult(
                    tool_grade=tool_grade,
                    reply_length=len(result.reply),
                    error=result.error,
                ))

            results.append(OrchestratorScenarioResult(
                scenario_id=scenario.id, turn_results=turn_results,
            ))

        metrics = compute_orchestrator_metrics(results)
        assert metrics.total_scenarios == len(orchestrator_scenarios)
        assert metrics.error_rate == 0.0


# ---------------------------------------------------------------------------
# Live mode tests
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestOrchestratorEvalLive:
    """Run orchestrator evals with real Sonnet API calls."""

    @pytest.fixture(autouse=True)
    def _skip_if_mock(self):
        if EVAL_MODE != "live":
            pytest.skip("Live mode not enabled (set EVAL_MODE=live)")

    @pytest.fixture
    def anthropic_client(self):
        import anthropic
        return anthropic.Anthropic()

    @pytest.mark.asyncio
    async def test_all_scenarios(self, orchestrator_scenarios, anthropic_client, tmp_path):
        """Run all orchestrator scenarios against real Sonnet API."""
        from homebuyer.services.faketor.classification import SegmentClassifier
        from homebuyer.services.faketor.extraction import SignalExtractor
        from homebuyer.services.faketor.tools import registry as global_registry

        # Build real components with real client
        extractor = SignalExtractor(anthropic_client)
        classifier = SegmentClassifier()

        # Use in-memory context store (no DB needed)
        ctx_store = MagicMock(spec=ResearchContextStore)
        ctx_store.persist = AsyncMock()

        results = []
        for scenario in orchestrator_scenarios:
            context = _make_mock_context(scenario.segment)
            ctx_store.load_or_create = AsyncMock(return_value=context)

            # Tool executor returns realistic Berkeley data per tool name
            from tests.evals.fixtures import TOOL_RESULTS, realistic_tool_result

            def _realistic_executor(tool_name, tool_input):
                import json
                result_str = realistic_tool_result(tool_name, tool_input)
                return ExecToolResult(
                    tool_name=tool_name,
                    tool_input=tool_input or {},
                    result_str=result_str,
                    result_data=json.loads(result_str),
                )

            tool_executor = MagicMock(spec=ToolExecutor)
            tool_executor.execute.side_effect = _realistic_executor
            pre_executor = MagicMock(spec=PreExecutor)
            pre_executor.execute.return_value = PreExecutionResult()

            orch = TurnOrchestrator(
                client=anthropic_client,
                context_store=ctx_store,
                signal_extractor=extractor,
                segment_classifier=classifier,
                tool_executor=tool_executor,
                pre_executor=pre_executor,
                registry=global_registry,
            )

            import time
            turn_results = []
            for turn in scenario.turns:
                t0 = time.time()
                result = await orch.run(
                    message=turn.message,
                    user_id="eval-live-user",
                    history=[],
                )
                elapsed = (time.time() - t0) * 1000

                tools_used = [tc["name"] for tc in result.tool_calls]
                tool_grade = grade_tool_selection(
                    tools_used, turn.expected_tools, turn.forbidden_tools,
                )

                quality_grade = grade_response_quality(
                    anthropic_client,
                    result.reply,
                    turn.message,
                    scenario.segment,
                    turn.expected_topics,
                    turn.forbidden_topics,
                )

                turn_results.append(OrchestratorTurnResult(
                    tool_grade=tool_grade,
                    quality_grade=quality_grade,
                    reply_length=len(result.reply),
                    latency_ms=elapsed,
                    iterations=result.metrics.llm_iterations if result.metrics else 0,
                    error=result.error,
                ))

            results.append(OrchestratorScenarioResult(
                scenario_id=scenario.id, turn_results=turn_results,
            ))

        metrics = compute_orchestrator_metrics(results)

        # Print report
        report = format_orchestrator_report(metrics, results)
        print("\n" + report)

        # Save results
        store = EvalResultStore()
        store.save_orchestrator_run(metrics, results)

        # Assert minimum quality bar
        assert metrics.error_rate <= 0.1, (
            f"Error rate ({metrics.error_rate:.1%}) above threshold (10%)"
        )
