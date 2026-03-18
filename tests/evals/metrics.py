"""Metric computation and aggregation for eval results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.evals.graders import (
    FieldResult,
    ResponseQualityGrade,
    ToolSelectionGrade,
)


# ---------------------------------------------------------------------------
# Extraction metrics
# ---------------------------------------------------------------------------


@dataclass
class ExtractionScenarioResult:
    """Result of running one extraction eval scenario."""

    scenario_id: str
    turn_results: list[list[FieldResult]]
    signal_counts: list[int]
    latencies_ms: list[float]
    final_profile: dict[str, Any] | None = None


@dataclass
class ExtractionMetrics:
    """Aggregate metrics across all extraction eval scenarios."""

    field_precision: float = 0.0
    field_recall: float = 0.0
    false_positive_rate: float = 0.0
    per_field_f1: dict[str, float] = field(default_factory=dict)
    macro_f1: float = 0.0
    avg_latency_ms: float = 0.0
    total_scenarios: int = 0
    total_turns: int = 0


def compute_extraction_metrics(
    results: list[ExtractionScenarioResult],
) -> ExtractionMetrics:
    """Compute aggregate extraction metrics from individual scenario results."""
    if not results:
        return ExtractionMetrics()

    # Flatten all field results across all scenarios and turns
    all_fields: list[FieldResult] = []
    all_latencies: list[float] = []
    total_turns = 0

    for r in results:
        for turn_fields in r.turn_results:
            all_fields.extend(turn_fields)
        all_latencies.extend(r.latencies_ms)
        total_turns += len(r.turn_results)

    # Overall precision/recall
    correct = sum(1 for f in all_fields if f.status == "correct")
    missed = sum(1 for f in all_fields if f.status == "missed")
    incorrect = sum(1 for f in all_fields if f.status == "incorrect")
    false_pos = sum(1 for f in all_fields if f.status == "false_positive")

    total_expected = correct + missed + incorrect  # Fields that should have values
    total_extracted = correct + incorrect + false_pos  # Fields that have values

    precision = correct / total_extracted if total_extracted else 1.0
    recall = correct / total_expected if total_expected else 1.0
    fp_rate = false_pos / (false_pos + (correct + missed)) if (false_pos + correct + missed) else 0.0

    # Per-field F1
    field_names = {f.field_name for f in all_fields}
    per_field_f1: dict[str, float] = {}
    for name in sorted(field_names):
        field_items = [f for f in all_fields if f.field_name == name]
        fc = sum(1 for f in field_items if f.status == "correct")
        fm = sum(1 for f in field_items if f.status == "missed")
        fi = sum(1 for f in field_items if f.status == "incorrect")
        ffp = sum(1 for f in field_items if f.status == "false_positive")

        f_expected = fc + fm + fi
        f_extracted = fc + fi + ffp
        f_prec = fc / f_extracted if f_extracted else 1.0
        f_rec = fc / f_expected if f_expected else 1.0
        f1 = 2 * f_prec * f_rec / (f_prec + f_rec) if (f_prec + f_rec) else 0.0
        per_field_f1[name] = round(f1, 3)

    macro_f1 = sum(per_field_f1.values()) / len(per_field_f1) if per_field_f1 else 0.0

    return ExtractionMetrics(
        field_precision=round(precision, 3),
        field_recall=round(recall, 3),
        false_positive_rate=round(fp_rate, 3),
        per_field_f1=per_field_f1,
        macro_f1=round(macro_f1, 3),
        avg_latency_ms=round(sum(all_latencies) / len(all_latencies), 1) if all_latencies else 0.0,
        total_scenarios=len(results),
        total_turns=total_turns,
    )


# ---------------------------------------------------------------------------
# Orchestrator metrics
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorTurnResult:
    """Result of running one orchestrator eval turn."""

    tool_grade: ToolSelectionGrade
    quality_grade: ResponseQualityGrade | None = None
    reply_length: int = 0
    latency_ms: float = 0.0
    iterations: int = 0
    error: str | None = None


@dataclass
class OrchestratorScenarioResult:
    """Result of running one orchestrator eval scenario."""

    scenario_id: str
    turn_results: list[OrchestratorTurnResult]


@dataclass
class OrchestratorMetrics:
    """Aggregate metrics across all orchestrator eval scenarios."""

    tool_precision: float = 0.0
    tool_recall: float = 0.0
    forbidden_violations: int = 0
    avg_reply_length: float = 0.0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    total_scenarios: int = 0
    total_turns: int = 0
    # LLM-judged (only populated in live mode)
    avg_topic_coverage: float | None = None
    avg_topic_avoidance: float | None = None
    avg_factual_grounding: float | None = None
    avg_helpfulness: float | None = None


def compute_orchestrator_metrics(
    results: list[OrchestratorScenarioResult],
) -> OrchestratorMetrics:
    """Compute aggregate orchestrator metrics from individual scenario results."""
    if not results:
        return OrchestratorMetrics()

    all_turns: list[OrchestratorTurnResult] = []
    for r in results:
        all_turns.extend(r.turn_results)

    if not all_turns:
        return OrchestratorMetrics(total_scenarios=len(results))

    # Tool metrics
    precisions = [t.tool_grade.precision for t in all_turns]
    recalls = [t.tool_grade.recall for t in all_turns]
    violations = sum(len(t.tool_grade.forbidden_violations) for t in all_turns)

    # Reply metrics
    lengths = [t.reply_length for t in all_turns]
    latencies = [t.latency_ms for t in all_turns if t.latency_ms > 0]
    errors = sum(1 for t in all_turns if t.error)

    metrics = OrchestratorMetrics(
        tool_precision=round(sum(precisions) / len(precisions), 3),
        tool_recall=round(sum(recalls) / len(recalls), 3),
        forbidden_violations=violations,
        avg_reply_length=round(sum(lengths) / len(lengths), 0) if lengths else 0.0,
        avg_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        error_rate=round(errors / len(all_turns), 3),
        total_scenarios=len(results),
        total_turns=len(all_turns),
    )

    # LLM-judged metrics (only if any grades exist)
    quality_turns = [t for t in all_turns if t.quality_grade and not t.quality_grade.judge_error]
    if quality_turns:
        metrics.avg_topic_coverage = round(
            sum(t.quality_grade.topic_coverage for t in quality_turns) / len(quality_turns), 2
        )
        metrics.avg_topic_avoidance = round(
            sum(t.quality_grade.topic_avoidance for t in quality_turns) / len(quality_turns), 2
        )
        metrics.avg_factual_grounding = round(
            sum(t.quality_grade.factual_grounding for t in quality_turns) / len(quality_turns), 2
        )
        metrics.avg_helpfulness = round(
            sum(t.quality_grade.helpfulness for t in quality_turns) / len(quality_turns), 2
        )

    return metrics
