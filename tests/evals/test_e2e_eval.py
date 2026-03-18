"""End-to-end pipeline eval runner.

Asserts intermediate state at every pipeline stage (extraction,
classification, pre-execution, response) for a single scenario run.
Identifies *where* the pipeline breaks rather than just whether the
final response is good.

Run with:
    EVAL_MODE=live pytest tests/evals/test_e2e_eval.py -m eval -v -s
    EVAL_MODE=live pytest tests/evals/test_e2e_eval.py -m eval -v -s --scenario e2e_03

GitHub issue: #83
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.evals.conftest import EVAL_MODE, E2EPipelineExpectation, E2EScenario


# ---------------------------------------------------------------------------
# Stage result tracking
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    """Result of asserting a single pipeline stage."""

    name: str
    passed: bool
    details: str = ""
    skipped: bool = False


@dataclass
class PipelineReport:
    """Full pipeline assertion report for one scenario turn."""

    scenario_id: str
    stages: list[StageResult] = field(default_factory=list)

    @property
    def first_failure(self) -> str | None:
        for s in self.stages:
            if not s.passed and not s.skipped:
                return s.name
        return None

    @property
    def all_passed(self) -> bool:
        return all(s.passed or s.skipped for s in self.stages)

    def format(self) -> str:
        lines = [
            f"E2E PIPELINE REPORT -- {self.scenario_id}",
            "=" * 60,
        ]
        for s in self.stages:
            if s.skipped:
                status = "SKIP"
            elif s.passed:
                status = "PASS"
            else:
                status = "FAIL"
            lines.append(f"  Stage -- {s.name:20s}: {status}  {s.details}")
        lines.append("=" * 60)
        if self.first_failure:
            lines.append(f"PIPELINE BREAK: {self.first_failure}")
        else:
            lines.append("ALL STAGES PASSED")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage assertion helpers
# ---------------------------------------------------------------------------


def _assert_extraction(
    trace_dict: dict[str, Any],
    expected: dict[str, Any],
) -> StageResult:
    """Check extraction output against expected values."""
    extraction = trace_dict.get("extraction", {})
    issues = []

    for key, expected_val in expected.items():
        actual = extraction.get(key)
        if expected_val is not None and actual != expected_val:
            # Allow approximate match for numeric values (within 20%)
            if isinstance(expected_val, (int, float)) and isinstance(actual, (int, float)):
                if actual is not None and abs(actual - expected_val) / max(expected_val, 1) < 0.2:
                    continue
            issues.append(f"{key}: expected={expected_val}, got={actual}")

    if issues:
        return StageResult(
            name="Extraction",
            passed=False,
            details="; ".join(issues),
        )
    return StageResult(name="Extraction", passed=True, details="all fields match")


def _assert_classification(
    trace_dict: dict[str, Any],
    expected: dict[str, Any],
) -> StageResult:
    """Check classification output against expected values."""
    classification = trace_dict.get("classification", {})
    issues = []

    # Check segment is in acceptable set
    segment_in = expected.get("segment_in", [])
    actual_segment = classification.get("segment_id")
    if segment_in and actual_segment not in segment_in:
        issues.append(
            f"segment={actual_segment}, expected one of {segment_in}"
        )

    # Check minimum confidence
    confidence_min = expected.get("confidence_min")
    actual_confidence = classification.get("confidence", 0)
    if confidence_min is not None and actual_confidence < confidence_min:
        issues.append(
            f"confidence={actual_confidence:.2f}, min={confidence_min}"
        )

    if issues:
        # Include candidates for debugging
        candidates = classification.get("candidates", [])[:3]
        cand_str = ", ".join(
            f"{c['segment_id']}({c['confidence']:.2f})"
            for c in candidates
        )
        return StageResult(
            name="Classification",
            passed=False,
            details="; ".join(issues) + f" [candidates: {cand_str}]",
        )
    return StageResult(
        name="Classification",
        passed=True,
        details=f"segment={actual_segment} ({actual_confidence:.2f})",
    )


def _assert_pre_execution(
    trace_dict: dict[str, Any],
    expected: dict[str, Any],
) -> StageResult:
    """Check pre-execution output against expected values."""
    pre_exec = trace_dict.get("pre_execution", {})
    actual_tools = set(pre_exec.get("tools", []))
    issues = []

    tools_include = expected.get("tools_include", [])
    for tool in tools_include:
        if tool not in actual_tools:
            issues.append(f"missing pre-executed tool: {tool}")

    if issues:
        return StageResult(
            name="Pre-execution",
            passed=False,
            details="; ".join(issues) + f" [actual: {sorted(actual_tools)}]",
        )
    return StageResult(
        name="Pre-execution",
        passed=True,
        details=f"tools={sorted(actual_tools)}",
    )


def _assert_response(
    trace_dict: dict[str, Any],
    expected: dict[str, Any],
    quality_grade: dict[str, Any] | None = None,
) -> StageResult:
    """Check response output against expected values."""
    response = trace_dict.get("response", {})
    issues = []

    # Check helpfulness minimum (from quality grade)
    helpfulness_min = expected.get("helpfulness_min")
    if helpfulness_min is not None and quality_grade:
        actual_help = quality_grade.get("helpfulness", 0)
        if actual_help < helpfulness_min:
            issues.append(
                f"helpfulness={actual_help}, min={helpfulness_min}"
            )

    # Check reply is non-empty
    reply_length = response.get("reply_length", 0)
    if reply_length == 0:
        issues.append("empty reply")

    if issues:
        return StageResult(
            name="Response",
            passed=False,
            details="; ".join(issues),
        )
    return StageResult(
        name="Response",
        passed=True,
        details=f"reply_length={reply_length}, tools={response.get('tools_used', [])}",
    )


# ---------------------------------------------------------------------------
# Live mode tests
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestE2EPipelineEvalLive:
    """Run e2e pipeline evals with real API calls, asserting at every stage."""

    @pytest.fixture(autouse=True)
    def _skip_if_mock(self):
        if EVAL_MODE != "live":
            pytest.skip("Live mode not enabled (set EVAL_MODE=live)")

    @pytest.fixture
    def app_state(self):
        """Initialize AppState with real DB + ML model."""
        import homebuyer.api as api_module
        from homebuyer.api import AppState

        state = AppState()
        api_module._state = state
        yield state
        state.close()
        api_module._state = None

    @pytest.fixture
    def anthropic_client(self):
        import anthropic
        return anthropic.Anthropic()

    @pytest.mark.asyncio
    async def test_all_scenarios(
        self, e2e_scenarios, app_state, anthropic_client,
    ):
        """Run all e2e scenarios and assert at every pipeline stage."""
        if not e2e_scenarios:
            pytest.skip("No matching e2e scenarios")

        orch = app_state.turn_orchestrator
        assert orch is not None, "TurnOrchestrator not initialized"

        reports: list[PipelineReport] = []
        any_failure = False

        for scenario in e2e_scenarios:
            user_id = f"e2e-eval-{scenario.id}"
            history: list[dict] = []

            for turn in scenario.turns:
                # Run with trace=True to capture intermediate state
                result = await orch.run(
                    message=turn.message,
                    user_id=user_id,
                    history=history,
                    trace=True,
                )

                assert result.trace is not None, (
                    "PipelineTrace not populated -- run() was not called with trace=True"
                )
                trace_dict = result.trace.to_dict()

                # Build history for multi-turn
                history.append({"role": "user", "content": turn.message})
                history.append({"role": "assistant", "content": result.reply})

                exp = turn.expectations
                report = PipelineReport(scenario_id=scenario.id)

                # Stage 1: Extraction
                if exp.expected_extraction:
                    report.stages.append(
                        _assert_extraction(trace_dict, exp.expected_extraction)
                    )
                else:
                    report.stages.append(
                        StageResult(name="Extraction", passed=True, skipped=True)
                    )

                # Stage 2: Classification (skip if extraction failed)
                upstream_ok = all(
                    s.passed or s.skipped for s in report.stages
                )
                if exp.expected_classification and upstream_ok:
                    report.stages.append(
                        _assert_classification(
                            trace_dict, exp.expected_classification
                        )
                    )
                elif not upstream_ok:
                    report.stages.append(
                        StageResult(
                            name="Classification",
                            passed=False,
                            skipped=True,
                            details="skipped (upstream failure)",
                        )
                    )
                else:
                    report.stages.append(
                        StageResult(
                            name="Classification",
                            passed=True,
                            skipped=True,
                        )
                    )

                # Stage 3: Pre-execution (skip if classification failed)
                upstream_ok = all(
                    s.passed or s.skipped for s in report.stages
                )
                if exp.expected_pre_execution and upstream_ok:
                    report.stages.append(
                        _assert_pre_execution(
                            trace_dict, exp.expected_pre_execution
                        )
                    )
                elif not upstream_ok:
                    report.stages.append(
                        StageResult(
                            name="Pre-execution",
                            passed=False,
                            skipped=True,
                            details="skipped (upstream failure)",
                        )
                    )
                else:
                    report.stages.append(
                        StageResult(
                            name="Pre-execution",
                            passed=True,
                            skipped=True,
                        )
                    )

                # Stage 4: Response (run LLM judge for helpfulness)
                quality_grade = None
                if exp.expected_response.get("helpfulness_min"):
                    from tests.evals.graders import grade_response_quality
                    tool_results_for_judge = [
                        {"tool": tc["name"], "result": b.get("data", {})}
                        for tc, b in zip(result.tool_calls, result.blocks)
                    ] if result.blocks else [
                        {"tool": tc["name"], "result": "(not captured)"}
                        for tc in result.tool_calls
                    ]
                    grade = grade_response_quality(
                        anthropic_client,
                        result.reply,
                        turn.message,
                        scenario.segment,
                        exp.expected_response.get("topics_include", []),
                        [],
                        tool_results=tool_results_for_judge,
                    )
                    quality_grade = {
                        "helpfulness": grade.helpfulness if grade else 0,
                    }

                upstream_ok = all(
                    s.passed or s.skipped for s in report.stages
                )
                if exp.expected_response and upstream_ok:
                    report.stages.append(
                        _assert_response(
                            trace_dict, exp.expected_response, quality_grade
                        )
                    )
                elif not upstream_ok:
                    report.stages.append(
                        StageResult(
                            name="Response",
                            passed=False,
                            skipped=True,
                            details="skipped (upstream failure)",
                        )
                    )
                else:
                    report.stages.append(
                        StageResult(name="Response", passed=True, skipped=True)
                    )

                reports.append(report)
                if not report.all_passed:
                    any_failure = True

        # Print all reports
        for r in reports:
            print("\n" + r.format())

        # Summary
        passed = sum(1 for r in reports if r.all_passed)
        failed = sum(1 for r in reports if not r.all_passed)
        print(f"\n--- E2E SUMMARY: {passed} passed, {failed} failed ---")

        if any_failure:
            failures = [r for r in reports if not r.all_passed]
            fail_details = "; ".join(
                f"{r.scenario_id} broke at {r.first_failure}"
                for r in failures
            )
            pytest.fail(f"Pipeline failures: {fail_details}")
