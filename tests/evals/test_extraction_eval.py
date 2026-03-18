"""Extraction eval runner.

Tests signal extraction quality against YAML scenarios. Two modes:
- Mock (default): Tests the eval harness using pre-recorded responses.
- Live (EVAL_MODE=live): Makes real Haiku API calls and grades results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from homebuyer.services.faketor.extraction import ExtractionResult, SignalExtractor
from homebuyer.services.faketor.state.buyer import BuyerProfile

from tests.evals.conftest import EVAL_MODE, ExtractionScenario, ExtractionTurn
from tests.evals.graders import grade_extraction
from tests.evals.metrics import ExtractionMetrics, ExtractionScenarioResult, compute_extraction_metrics
from tests.evals.report import format_extraction_report
from tests.evals.results import EvalResultStore


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


@dataclass
class _MockTextBlock:
    text: str
    type: str = "text"


@dataclass
class _MockResponse:
    content: list[_MockTextBlock]


def _mock_extraction_response(expected: dict[str, Any]) -> dict[str, Any]:
    """Build a mock extraction JSON response that matches the expected values."""
    response: dict[str, Any] = {}
    for field_name in (
        "intent", "capital", "equity", "income", "current_rent",
        "owns_current_home", "is_first_time_buyer", "sophistication",
    ):
        response[field_name] = expected.get(field_name)
    response["signals"] = [
        {
            "evidence": f"Mock signal for {k}",
            "implication": f"Extracted {k}",
            "confidence": 0.8,
        }
        for k in expected
    ]
    return response


def _make_mock_client(turns: list[ExtractionTurn]) -> MagicMock:
    """Create a mock Anthropic client that returns expected values for each turn."""
    client = MagicMock()
    responses = [
        _MockResponse(content=[_MockTextBlock(text=json.dumps(_mock_extraction_response(t.expected)))])
        for t in turns
    ]
    client.messages.create.side_effect = responses
    return client


def _result_to_fields(result: ExtractionResult) -> dict[str, Any]:
    """Convert ExtractionResult to a flat dict of field values."""
    return {
        "intent": result.intent,
        "capital": result.capital,
        "equity": result.equity,
        "income": result.income,
        "current_rent": result.current_rent,
        "owns_current_home": result.owns_current_home,
        "is_first_time_buyer": result.is_first_time_buyer,
        "sophistication": result.sophistication,
    }


def _run_scenario(
    extractor: SignalExtractor,
    scenario: ExtractionScenario,
) -> ExtractionScenarioResult:
    """Run a single extraction eval scenario through all turns."""
    turn_results = []
    signal_counts = []
    latencies = []
    profile = BuyerProfile()

    for turn in scenario.turns:
        result = extractor.extract(turn.message, current_profile=profile)

        # Grade this turn
        fields = _result_to_fields(result)
        grades = grade_extraction(fields, turn.expected, turn.expected_null)
        turn_results.append(grades)
        signal_counts.append(len(result.signals))
        latencies.append(result.extraction_time_ms)

        # Apply extraction to profile for next turn (multi-turn accumulation)
        extractions = result.to_extractions()
        if extractions:
            profile.apply_extraction(extractions)

    # Build final profile snapshot
    final_profile = {
        "intent": profile.intent,
        "capital": profile.capital,
        "equity": profile.equity,
        "income": profile.income,
        "current_rent": profile.current_rent,
        "owns_current_home": profile.owns_current_home,
        "is_first_time_buyer": profile.is_first_time_buyer,
    }

    return ExtractionScenarioResult(
        scenario_id=scenario.id,
        turn_results=turn_results,
        signal_counts=signal_counts,
        latencies_ms=latencies,
        final_profile=final_profile,
    )


# ---------------------------------------------------------------------------
# Mock mode tests (fast, no API calls)
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestExtractionEvalMock:
    """Test the extraction eval harness using mock responses."""

    def test_scenarios_load(self, extraction_scenarios, request):
        """Verify scenarios load from YAML."""
        if request.config.getoption("--scenario", default=None):
            pytest.skip("Filtered by --scenario")
        assert len(extraction_scenarios) > 0, "No extraction scenarios found"

    def test_all_scenarios_have_turns(self, extraction_scenarios):
        """Every scenario must have at least one turn."""
        for s in extraction_scenarios:
            assert len(s.turns) > 0, f"Scenario {s.id} has no turns"

    def test_mock_grading_pipeline(self, extraction_scenarios):
        """Run all scenarios in mock mode and verify grading works."""
        if not extraction_scenarios:
            pytest.skip("No matching scenarios")
        results = []
        for scenario in extraction_scenarios:
            client = _make_mock_client(scenario.turns)
            extractor = SignalExtractor(client)
            result = _run_scenario(extractor, scenario)
            results.append(result)

        metrics = compute_extraction_metrics(results)
        assert metrics.total_scenarios == len(extraction_scenarios)
        assert metrics.total_turns > 0
        # In mock mode, responses match expected exactly, so F1 should be high
        assert metrics.macro_f1 >= 0.9, f"Mock F1 unexpectedly low: {metrics.macro_f1}"

    def test_multi_turn_accumulation(self, extraction_scenarios):
        """Multi-turn scenarios correctly accumulate profile data."""
        multi_turn = [s for s in extraction_scenarios if len(s.turns) > 1]
        if not multi_turn:
            pytest.skip("No multi-turn scenarios in current filter")

        for scenario in multi_turn:
            client = _make_mock_client(scenario.turns)
            extractor = SignalExtractor(client)
            result = _run_scenario(extractor, scenario)

            if scenario.final_expected:
                for field_name, expected_val in scenario.final_expected.items():
                    actual = result.final_profile.get(field_name)
                    assert actual is not None, (
                        f"{scenario.id}: field '{field_name}' not in final profile"
                    )


# ---------------------------------------------------------------------------
# Live mode tests (real API calls)
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestExtractionEvalLive:
    """Run extraction evals with real Haiku API calls."""

    @pytest.fixture(autouse=True)
    def _skip_if_mock(self):
        if EVAL_MODE != "live":
            pytest.skip("Live mode not enabled (set EVAL_MODE=live)")

    @pytest.fixture
    def anthropic_client(self):
        import anthropic
        return anthropic.Anthropic()

    def test_all_scenarios(self, extraction_scenarios, anthropic_client, tmp_path):
        """Run all extraction scenarios against real Haiku API."""
        extractor = SignalExtractor(anthropic_client)
        results = []

        for scenario in extraction_scenarios:
            result = _run_scenario(extractor, scenario)
            results.append(result)

        metrics = compute_extraction_metrics(results)

        # Print report
        report = format_extraction_report(metrics, results)
        print("\n" + report)

        # Save results
        store = EvalResultStore()
        store.save_extraction_run(metrics, results)

        # Assert minimum quality bar
        assert metrics.macro_f1 >= 0.50, (
            f"Extraction macro F1 ({metrics.macro_f1}) below minimum threshold (0.50)"
        )
