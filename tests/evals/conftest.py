"""Eval framework shared fixtures and configuration.

Provides scenario loaders, mode selection (mock vs live), and shared helpers.
Evals are excluded from default pytest runs via the ``eval`` marker.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------

EVAL_MODE = os.getenv("EVAL_MODE", "mock")  # "mock" or "live"

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


# ---------------------------------------------------------------------------
# Scenario data classes
# ---------------------------------------------------------------------------


@dataclass
class ExtractionTurn:
    """A single turn in an extraction eval scenario."""

    message: str
    expected: dict[str, Any]
    expected_null: list[str] = field(default_factory=list)
    min_signals: int = 0


@dataclass
class ExtractionScenario:
    """An extraction eval scenario (single- or multi-turn)."""

    id: str
    turns: list[ExtractionTurn]
    description: str = ""
    final_expected: dict[str, Any] | None = None


@dataclass
class OrchestratorTurn:
    """A single turn in an orchestrator eval scenario."""

    message: str
    expected_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    expected_topics: list[str] = field(default_factory=list)
    forbidden_topics: list[str] = field(default_factory=list)


@dataclass
class OrchestratorScenario:
    """An orchestrator eval scenario (single- or multi-turn)."""

    id: str
    segment: str
    turns: list[OrchestratorTurn]
    description: str = ""


# ---------------------------------------------------------------------------
# YAML loaders
# ---------------------------------------------------------------------------


def _load_yaml_scenarios(subdir: str) -> list[dict[str, Any]]:
    """Load all scenario YAML files from a subdirectory."""
    path = SCENARIOS_DIR / subdir
    scenarios: list[dict[str, Any]] = []
    if not path.exists():
        return scenarios
    for f in sorted(path.glob("*.yaml")):
        data = yaml.safe_load(f.read_text())
        if data and "scenarios" in data:
            scenarios.extend(data["scenarios"])
    return scenarios


def load_extraction_scenarios() -> list[ExtractionScenario]:
    """Load all extraction eval scenarios from YAML."""
    raw = _load_yaml_scenarios("extraction")
    result: list[ExtractionScenario] = []
    for s in raw:
        turns = [
            ExtractionTurn(
                message=t["message"],
                expected=t.get("expected", {}),
                expected_null=t.get("expected_null", []),
                min_signals=t.get("min_signals", 0),
            )
            for t in s.get("turns", [])
        ]
        result.append(
            ExtractionScenario(
                id=s["id"],
                turns=turns,
                description=s.get("description", ""),
                final_expected=s.get("final_expected"),
            )
        )
    return result


def load_orchestrator_scenarios() -> list[OrchestratorScenario]:
    """Load all orchestrator eval scenarios from YAML."""
    raw = _load_yaml_scenarios("orchestrator")
    result: list[OrchestratorScenario] = []
    for s in raw:
        turns = [
            OrchestratorTurn(
                message=t["message"],
                expected_tools=t.get("expected_tools", []),
                forbidden_tools=t.get("forbidden_tools", []),
                expected_topics=t.get("expected_topics", []),
                forbidden_topics=t.get("forbidden_topics", []),
            )
            for t in s.get("turns", [])
        ]
        result.append(
            OrchestratorScenario(
                id=s["id"],
                segment=s.get("segment", ""),
                turns=turns,
                description=s.get("description", ""),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def eval_mode() -> str:
    return EVAL_MODE


@pytest.fixture
def extraction_scenarios() -> list[ExtractionScenario]:
    return load_extraction_scenarios()


@pytest.fixture
def orchestrator_scenarios() -> list[OrchestratorScenario]:
    return load_orchestrator_scenarios()
