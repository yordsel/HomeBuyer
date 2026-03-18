"""Eval result storage and baseline comparison."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tests.evals.metrics import (
    ExtractionMetrics,
    ExtractionScenarioResult,
    OrchestratorMetrics,
    OrchestratorScenarioResult,
)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "evals"
_RUNS_DIR = _DATA_DIR / "runs"
_BASELINES_DIR = _DATA_DIR / "baselines"


class EvalResultStore:
    """Save, load, and compare eval run results."""

    def __init__(self, base_dir: Path | None = None):
        self._data_dir = base_dir or _DATA_DIR
        self._runs_dir = self._data_dir / "runs"
        self._baselines_dir = self._data_dir / "baselines"

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")

    def _git_sha(self) -> str:
        try:
            import subprocess
            return subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            ).decode().strip()
        except Exception:
            return "unknown"

    def save_extraction_run(
        self,
        metrics: ExtractionMetrics,
        results: list[ExtractionScenarioResult],
    ) -> Path:
        """Save an extraction eval run to disk."""
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        ts = self._timestamp()
        path = self._runs_dir / f"{ts}_extraction.json"

        data = {
            "run_id": ts,
            "eval_type": "extraction",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_sha": self._git_sha(),
            "metrics": asdict(metrics),
            "per_scenario": [
                {
                    "id": r.scenario_id,
                    "turns": len(r.turn_results),
                    "latencies_ms": r.latencies_ms,
                    "signal_counts": r.signal_counts,
                    "final_profile": r.final_profile,
                    "field_results": [
                        [{"field": f.field_name, "status": f.status} for f in turn]
                        for turn in r.turn_results
                    ],
                }
                for r in results
            ],
        }
        path.write_text(json.dumps(data, indent=2, default=str))
        return path

    def save_orchestrator_run(
        self,
        metrics: OrchestratorMetrics,
        results: list[OrchestratorScenarioResult],
    ) -> Path:
        """Save an orchestrator eval run to disk."""
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        ts = self._timestamp()
        path = self._runs_dir / f"{ts}_orchestrator.json"

        data = {
            "run_id": ts,
            "eval_type": "orchestrator",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_sha": self._git_sha(),
            "metrics": asdict(metrics),
            "per_scenario": [
                {
                    "id": r.scenario_id,
                    "turns": [
                        {
                            "tools_used": t.tool_grade.tools_used,
                            "expected_hits": t.tool_grade.expected_hits,
                            "expected_misses": t.tool_grade.expected_misses,
                            "forbidden_violations": t.tool_grade.forbidden_violations,
                            "reply_length": t.reply_length,
                            "latency_ms": t.latency_ms,
                            "error": t.error,
                            "quality": {
                                "topic_coverage": t.quality_grade.topic_coverage,
                                "topic_avoidance": t.quality_grade.topic_avoidance,
                                "factual_grounding": t.quality_grade.factual_grounding,
                                "helpfulness": t.quality_grade.helpfulness,
                                "reasoning": t.quality_grade.reasoning,
                            } if t.quality_grade and not t.quality_grade.judge_error else None,
                        }
                        for t in r.turn_results
                    ],
                }
                for r in results
            ],
        }
        path.write_text(json.dumps(data, indent=2, default=str))
        return path

    def load_baseline(self, eval_type: str) -> dict[str, Any] | None:
        """Load the committed baseline for the given eval type."""
        path = self._baselines_dir / f"{eval_type}_baseline.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save_as_baseline(self, run_path: Path) -> Path:
        """Promote a run result to baseline."""
        self._baselines_dir.mkdir(parents=True, exist_ok=True)
        data = json.loads(run_path.read_text())
        eval_type = data["eval_type"]
        baseline_path = self._baselines_dir / f"{eval_type}_baseline.json"
        baseline_path.write_text(json.dumps(data, indent=2, default=str))
        return baseline_path

    def compare(
        self,
        current_metrics: dict[str, Any],
        baseline_metrics: dict[str, Any],
    ) -> dict[str, dict[str, float]]:
        """Compare current metrics against baseline. Returns deltas."""
        deltas: dict[str, dict[str, float]] = {}
        for key in current_metrics:
            curr = current_metrics.get(key)
            base = baseline_metrics.get(key)
            if isinstance(curr, (int, float)) and isinstance(base, (int, float)):
                deltas[key] = {"current": curr, "baseline": base, "delta": curr - base}
        return deltas
