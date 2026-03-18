"""Human-readable report generation for eval results."""

from __future__ import annotations

from tests.evals.metrics import (
    ExtractionMetrics,
    ExtractionScenarioResult,
    OrchestratorMetrics,
    OrchestratorScenarioResult,
)


def format_extraction_report(
    metrics: ExtractionMetrics,
    results: list[ExtractionScenarioResult] | None = None,
) -> str:
    """Format extraction eval metrics as a readable report."""
    lines = [
        "=" * 60,
        "EXTRACTION EVAL REPORT",
        "=" * 60,
        f"Scenarios: {metrics.total_scenarios}  |  Turns: {metrics.total_turns}",
        "",
        "--- Aggregate Metrics ---",
        f"  Precision:         {metrics.field_precision:.1%}",
        f"  Recall:            {metrics.field_recall:.1%}",
        f"  Macro F1:          {metrics.macro_f1:.1%}",
        f"  False Positive Rate: {metrics.false_positive_rate:.1%}",
        f"  Avg Latency:       {metrics.avg_latency_ms:.0f} ms",
        "",
        "--- Per-Field F1 ---",
    ]

    for field_name, f1 in sorted(metrics.per_field_f1.items()):
        bar = "#" * int(f1 * 20)
        lines.append(f"  {field_name:25s} {f1:.3f}  {bar}")

    # Per-scenario breakdown
    if results:
        lines.append("")
        lines.append("--- Per-Scenario ---")
        for r in results:
            total_fields = sum(len(turn) for turn in r.turn_results)
            correct = sum(
                1 for turn in r.turn_results for f in turn if f.status == "correct"
            )
            status = "PASS" if total_fields > 0 and correct == total_fields else "FAIL"
            turns_str = f"{len(r.turn_results)} turn{'s' if len(r.turn_results) > 1 else ''}"
            lines.append(
                f"  [{status}] {r.scenario_id:40s} {turns_str:8s} "
                f"{correct}/{total_fields} fields correct"
            )

    lines.append("=" * 60)
    return "\n".join(lines)


def format_orchestrator_report(
    metrics: OrchestratorMetrics,
    results: list[OrchestratorScenarioResult] | None = None,
) -> str:
    """Format orchestrator eval metrics as a readable report."""
    lines = [
        "=" * 60,
        "ORCHESTRATOR EVAL REPORT",
        "=" * 60,
        f"Scenarios: {metrics.total_scenarios}  |  Turns: {metrics.total_turns}",
        "",
        "--- Tool Selection ---",
        f"  Precision:         {metrics.tool_precision:.1%}",
        f"  Recall:            {metrics.tool_recall:.1%}",
        f"  Forbidden Violations: {metrics.forbidden_violations}",
        "",
        "--- Response Quality ---",
        f"  Avg Reply Length:  {metrics.avg_reply_length:.0f} chars",
        f"  Avg Latency:       {metrics.avg_latency_ms:.0f} ms",
        f"  Error Rate:        {metrics.error_rate:.1%}",
    ]

    if metrics.avg_helpfulness is not None:
        lines.extend([
            "",
            "--- LLM Judge Scores (0-5) ---",
            f"  Topic Coverage:    {metrics.avg_topic_coverage:.2f}",
            f"  Topic Avoidance:   {metrics.avg_topic_avoidance:.2f}",
            f"  Factual Grounding: {metrics.avg_factual_grounding:.2f}",
            f"  Helpfulness:       {metrics.avg_helpfulness:.2f}",
        ])

    # Per-scenario breakdown
    if results:
        lines.append("")
        lines.append("--- Per-Scenario ---")
        for r in results:
            violations = sum(len(t.tool_grade.forbidden_violations) for t in r.turn_results)
            errors = sum(1 for t in r.turn_results if t.error)
            status = "PASS" if violations == 0 and errors == 0 else "FAIL"
            tools = set()
            quality_scores = []
            for t in r.turn_results:
                tools.update(t.tool_grade.tools_used)
                if t.quality_grade and not t.quality_grade.judge_error:
                    quality_scores.append(t.quality_grade.helpfulness)
            help_str = f"help={sum(quality_scores)/len(quality_scores):.1f}" if quality_scores else ""
            lines.append(
                f"  [{status}] {r.scenario_id:40s} "
                f"tools={len(tools):2d}  {help_str:8s}  violations={violations}"
            )

        # Show lowest-scoring scenarios with judge reasoning
        all_scored = []
        for r in results:
            for t in r.turn_results:
                if t.quality_grade and not t.quality_grade.judge_error:
                    all_scored.append((r.scenario_id, t.quality_grade))
        if all_scored:
            all_scored.sort(key=lambda x: x[1].helpfulness)
            lines.append("")
            lines.append("--- Lowest Helpfulness (bottom 5) ---")
            for scenario_id, qg in all_scored[:5]:
                lines.append(
                    f"  {scenario_id:40s} help={qg.helpfulness:.1f}  "
                    f"fact={qg.factual_grounding:.1f}  topic={qg.topic_coverage:.1f}"
                )
                if qg.reasoning:
                    # Truncate reasoning to one line
                    reason = qg.reasoning.replace("\n", " ")[:120]
                    lines.append(f"    -> {reason}")

    lines.append("=" * 60)
    return "\n".join(lines)


def format_comparison_report(
    deltas: dict[str, dict[str, float]],
    eval_type: str,
) -> str:
    """Format a baseline comparison as a readable report."""
    lines = [
        "=" * 60,
        f"{eval_type.upper()} BASELINE COMPARISON",
        "=" * 60,
        f"{'Metric':30s} {'Baseline':>10s} {'Current':>10s} {'Delta':>10s}",
        "-" * 60,
    ]

    regressions = []
    for key, vals in sorted(deltas.items()):
        baseline = vals["baseline"]
        current = vals["current"]
        delta = vals["delta"]
        marker = ""
        if delta < -0.05:
            marker = " <-- REGRESSION"
            regressions.append(key)
        lines.append(
            f"  {key:28s} {baseline:10.3f} {current:10.3f} {delta:+10.3f}{marker}"
        )

    lines.append("-" * 60)
    if regressions:
        lines.append(f"REGRESSIONS DETECTED: {', '.join(regressions)}")
    else:
        lines.append("No regressions detected.")
    lines.append("=" * 60)
    return "\n".join(lines)
