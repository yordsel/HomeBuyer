"""Grading logic for eval scenarios.

Deterministic graders compare structured outputs against expected values.
LLM-as-judge grader uses Haiku for subjective quality scoring (live mode only).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction grading
# ---------------------------------------------------------------------------

_NUMERIC_FIELDS = {"capital", "equity", "income", "current_rent"}
_BOOL_FIELDS = {"owns_current_home", "is_first_time_buyer"}
_ENUM_FIELDS = {"intent", "sophistication"}


@dataclass
class FieldResult:
    """Result of grading a single extraction field."""

    field_name: str
    expected: Any
    actual: Any
    status: Literal["correct", "incorrect", "false_positive", "missed"]


def _values_match(field_name: str, expected: Any, actual: Any, tolerance: float) -> bool:
    """Check if expected and actual values match with type-appropriate comparison."""
    if field_name in _NUMERIC_FIELDS:
        if expected == 0:
            return actual == 0
        return abs(actual - expected) / abs(expected) <= tolerance
    return actual == expected


def grade_extraction(
    result_fields: dict[str, Any],
    expected: dict[str, Any],
    expected_null: list[str],
    numeric_tolerance: float = 0.10,
) -> list[FieldResult]:
    """Grade an extraction result against expected values.

    Args:
        result_fields: Dict of field_name -> extracted value (None if not extracted).
        expected: Dict of field_name -> expected value for fields that should be present.
        expected_null: List of field names that should NOT be extracted (should be None).
        numeric_tolerance: Fractional tolerance for numeric comparisons (default 10%).

    Returns:
        List of FieldResult for each graded field.
    """
    results: list[FieldResult] = []

    # Check fields that should have been extracted
    for field_name, exp_value in expected.items():
        actual = result_fields.get(field_name)
        if actual is None:
            results.append(FieldResult(field_name, exp_value, None, "missed"))
        elif _values_match(field_name, exp_value, actual, numeric_tolerance):
            results.append(FieldResult(field_name, exp_value, actual, "correct"))
        else:
            results.append(FieldResult(field_name, exp_value, actual, "incorrect"))

    # Check fields that should NOT have been extracted
    for field_name in expected_null:
        actual = result_fields.get(field_name)
        if actual is not None:
            results.append(FieldResult(field_name, None, actual, "false_positive"))
        else:
            results.append(FieldResult(field_name, None, None, "correct"))

    return results


# ---------------------------------------------------------------------------
# Tool selection grading
# ---------------------------------------------------------------------------


@dataclass
class ToolSelectionGrade:
    """Result of grading tool selection."""

    tools_used: list[str]
    expected_hits: list[str]
    expected_misses: list[str]
    forbidden_violations: list[str]
    precision: float
    recall: float


def grade_tool_selection(
    tools_used: list[str],
    expected_tools: list[str],
    forbidden_tools: list[str],
) -> ToolSelectionGrade:
    """Grade which tools were selected vs expectations.

    Args:
        tools_used: List of tool names actually called.
        expected_tools: Tools that SHOULD have been called.
        forbidden_tools: Tools that should NOT have been called.

    Returns:
        ToolSelectionGrade with precision, recall, and violations.
    """
    used_set = set(tools_used)
    expected_set = set(expected_tools)
    forbidden_set = set(forbidden_tools)

    hits = list(used_set & expected_set)
    misses = list(expected_set - used_set)
    violations = list(used_set & forbidden_set)

    recall = len(hits) / len(expected_set) if expected_set else 1.0
    # Precision: fraction of used tools that are in expected or at least not forbidden
    acceptable = used_set - forbidden_set
    precision = len(acceptable) / len(used_set) if used_set else 1.0

    return ToolSelectionGrade(
        tools_used=tools_used,
        expected_hits=hits,
        expected_misses=misses,
        forbidden_violations=violations,
        precision=precision,
        recall=recall,
    )


# ---------------------------------------------------------------------------
# LLM-as-judge grading (live mode only)
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM_PROMPT = """\
You are evaluating an AI real estate assistant's response quality.
Score each dimension from 0 to 5, where 0 is terrible and 5 is excellent.
Return ONLY a JSON object with numeric scores and a brief reasoning string.\
"""

_JUDGE_USER_TEMPLATE = """\
USER SEGMENT: {segment}

USER MESSAGE:
{message}

ASSISTANT RESPONSE:
{response}

EXPECTED TOPICS (should be addressed): {expected_topics}
TOPICS TO AVOID (should not appear): {forbidden_topics}

Score each dimension 0-5:
1. topic_coverage: Does the response address the expected topics?
2. topic_avoidance: Does the response avoid the forbidden topics? (5 = avoids all)
3. factual_grounding: Are claims supported by data, not hallucinated?
4. helpfulness: Overall quality for this buyer's situation?

Return JSON: {{"topic_coverage": N, "topic_avoidance": N, "factual_grounding": N, \
"helpfulness": N, "reasoning": "..."}}\
"""


@dataclass
class ResponseQualityGrade:
    """LLM-judged response quality scores."""

    topic_coverage: float = 0.0
    topic_avoidance: float = 0.0
    factual_grounding: float = 0.0
    helpfulness: float = 0.0
    reasoning: str = ""
    judge_error: str | None = None


def grade_response_quality(
    client: Any,
    response: str,
    message: str,
    segment: str,
    expected_topics: list[str],
    forbidden_topics: list[str],
) -> ResponseQualityGrade:
    """Use Haiku as a judge to score response quality.

    Only called in live mode. Returns a ResponseQualityGrade with scores 0-5.
    """
    prompt = _JUDGE_USER_TEMPLATE.format(
        segment=segment,
        message=message,
        response=response,
        expected_topics=", ".join(expected_topics) if expected_topics else "(none specified)",
        forbidden_topics=", ".join(forbidden_topics) if forbidden_topics else "(none specified)",
    )

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        return ResponseQualityGrade(
            topic_coverage=float(data.get("topic_coverage", 0)),
            topic_avoidance=float(data.get("topic_avoidance", 0)),
            factual_grounding=float(data.get("factual_grounding", 0)),
            helpfulness=float(data.get("helpfulness", 0)),
            reasoning=data.get("reasoning", ""),
        )
    except Exception as e:
        logger.warning("LLM judge failed: %s", e)
        return ResponseQualityGrade(judge_error=str(e))
