"""Signal extractor for the segment-driven Faketor redesign.

Uses Claude Haiku for fast (~200ms) structured extraction of buyer signals
from conversation messages. Separate from the main conversation LLM — this
is a cheap, focused call that parses financial and situational data.

Phase C-1 (#32) of Epic #23.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from homebuyer.services.faketor.state.buyer import BuyerProfile, FieldSource, Signal

logger = logging.getLogger(__name__)

# Model for extraction — Haiku is fast and cheap
_EXTRACTION_MODEL = "claude-haiku-4-5-20251001"

# Fields we extract from messages
_EXTRACTABLE_FIELDS = (
    "intent", "capital", "equity", "income", "current_rent",
    "owns_current_home", "is_first_time_buyer", "sophistication",
)


# ---------------------------------------------------------------------------
# ExtractionResult
# ---------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    """Structured output from the extraction LLM call.

    Fields are None when not detected in the message. Only populated
    fields should be applied to the buyer profile.
    """

    intent: Literal["occupy", "invest"] | None = None
    capital: int | None = None
    equity: int | None = None
    income: int | None = None
    current_rent: int | None = None
    owns_current_home: bool | None = None
    is_first_time_buyer: bool | None = None
    sophistication: Literal["novice", "informed", "professional"] | None = None
    signals: list[Signal] = field(default_factory=list)

    # Metadata
    extraction_time_ms: float = 0.0
    model_used: str = ""

    def is_empty(self) -> bool:
        """True if no fields were extracted."""
        return (
            self.intent is None
            and self.capital is None
            and self.equity is None
            and self.income is None
            and self.current_rent is None
            and self.owns_current_home is None
            and self.is_first_time_buyer is None
            and self.sophistication is None
            and len(self.signals) == 0
        )

    def to_extractions(self) -> dict[str, tuple[Any, FieldSource]]:
        """Convert to the format expected by BuyerProfile.apply_extraction().

        Creates (value, FieldSource) tuples for each non-None extracted field.
        """
        now = time.time()
        result: dict[str, tuple[Any, FieldSource]] = {}

        for field_name in _EXTRACTABLE_FIELDS:
            value = getattr(self, field_name)
            if value is None:
                continue

            # Find the signal with the highest confidence for this field
            related_signals = [
                s for s in self.signals
                if field_name in s.implication.lower()
            ]
            confidence = (
                max(s.confidence for s in related_signals)
                if related_signals
                else 0.7  # Default confidence for extracted values
            )
            evidence = (
                related_signals[0].evidence
                if related_signals
                else "Extracted from message"
            )

            result[field_name] = (
                value,
                FieldSource(
                    source="extracted",
                    confidence=confidence,
                    evidence=evidence,
                    extracted_at=now,
                ),
            )

        return result


# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM_PROMPT = """\
You are analyzing a home buyer's message to extract financial and situational \
signals. You are NOT having a conversation — just parsing.

Extract any of the following if present. Return ONLY what you can confidently \
extract. Do not infer aggressively — if the buyer says "I'm renting" that \
implies they don't own, but it doesn't tell you their income.

RULES:
- Only extract what is explicitly stated or very strongly implied
- Dollar amounts should be integers (no decimals)
- If someone says "about 200k" → capital: 200000
- If someone says "I make around 150" in context of salary → income: 150000
- "I want to rent it out" → intent: "invest"
- "I want to buy my first home" → intent: "occupy", is_first_time_buyer: true
- If unsure about a field, omit it (return null)
- Each signal should explain what was detected and why"""

_EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": ["string", "null"],
            "enum": ["occupy", "invest", None],
            "description": "Buy to live in (occupy) or as investment (invest)",
        },
        "capital": {
            "type": ["integer", "null"],
            "description": "Liquid cash/savings in dollars",
        },
        "equity": {
            "type": ["integer", "null"],
            "description": "Equity in existing property in dollars",
        },
        "income": {
            "type": ["integer", "null"],
            "description": "Annual household gross income in dollars",
        },
        "current_rent": {
            "type": ["integer", "null"],
            "description": "Current monthly rent in dollars",
        },
        "owns_current_home": {
            "type": ["boolean", "null"],
            "description": "Whether the buyer currently owns a home",
        },
        "is_first_time_buyer": {
            "type": ["boolean", "null"],
            "description": "Whether this is their first home purchase",
        },
        "sophistication": {
            "type": ["string", "null"],
            "enum": ["novice", "informed", "professional", None],
            "description": "Buyer's real estate knowledge level",
        },
        "signals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence": {
                        "type": "string",
                        "description": "What the buyer said (quote or paraphrase)",
                    },
                    "implication": {
                        "type": "string",
                        "description": "What it means for segmentation",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Confidence in this signal (0.0-1.0)",
                    },
                },
                "required": ["evidence", "implication", "confidence"],
            },
        },
    },
}


# ---------------------------------------------------------------------------
# SignalExtractor
# ---------------------------------------------------------------------------


class SignalExtractor:
    """Extracts buyer signals from a message using a focused LLM call.

    This is NOT the main conversation LLM. It's a separate, cheap, fast
    call using Haiku with a structured output schema.
    """

    def __init__(self, client: Any) -> None:
        """Initialize with an Anthropic client.

        Args:
            client: An anthropic.Anthropic client instance.
        """
        self._client = client

    def extract(
        self,
        message: str,
        current_profile: BuyerProfile | None = None,
        prior_signals: list[Signal] | None = None,
    ) -> ExtractionResult:
        """Extract buyer signals from a single user message.

        Uses Claude Haiku with a structured JSON output schema.
        Returns empty ExtractionResult if no signals are detected.
        """
        if not message or not message.strip():
            return ExtractionResult()

        user_content = self._build_extraction_prompt(
            message=message,
            current_profile=current_profile,
            prior_signals=prior_signals,
            is_user_message=True,
        )

        return self._run_extraction(user_content)

    def extract_from_output(
        self,
        llm_response: str,
        current_profile: BuyerProfile | None = None,
    ) -> ExtractionResult:
        """Extract signals from the LLM's response (post-processing).

        The LLM sometimes elicits and confirms information in its response
        that wasn't in the user's message. E.g., "So you're looking for your
        first home—" confirms first_time_buyer without the user saying it.
        """
        if not llm_response or not llm_response.strip():
            return ExtractionResult()

        user_content = self._build_extraction_prompt(
            message=llm_response,
            current_profile=current_profile,
            is_user_message=False,
        )

        return self._run_extraction(user_content)

    def _build_extraction_prompt(
        self,
        message: str,
        current_profile: BuyerProfile | None = None,
        prior_signals: list[Signal] | None = None,
        is_user_message: bool = True,
    ) -> str:
        """Build the user-content portion of the extraction prompt."""
        parts: list[str] = []

        # Current profile context
        if current_profile:
            profile_data = {
                k: v for k, v in {
                    "intent": current_profile.intent,
                    "capital": current_profile.capital,
                    "equity": current_profile.equity,
                    "income": current_profile.income,
                    "current_rent": current_profile.current_rent,
                    "owns_current_home": current_profile.owns_current_home,
                    "is_first_time_buyer": current_profile.is_first_time_buyer,
                    "sophistication": current_profile.sophistication,
                }.items()
                if v is not None
            }
            if profile_data:
                parts.append(f"CURRENT BUYER PROFILE:\n{json.dumps(profile_data, indent=2)}")

        # Prior signals context
        if prior_signals:
            signals_data = [
                {"evidence": s.evidence, "implication": s.implication}
                for s in prior_signals[-5:]  # Last 5 signals for context
            ]
            parts.append(f"PRIOR SIGNALS:\n{json.dumps(signals_data, indent=2)}")

        # The message to extract from
        label = "USER MESSAGE" if is_user_message else "LLM RESPONSE (extract confirmed facts)"
        parts.append(f"{label}:\n{message}")

        parts.append(
            "Extract buyer signals from the above. Return JSON matching the schema. "
            "Omit fields that cannot be confidently extracted (use null)."
        )

        return "\n\n".join(parts)

    def _run_extraction(self, user_content: str) -> ExtractionResult:
        """Execute the extraction LLM call and parse the result."""
        start = time.time()
        try:
            response = self._client.messages.create(
                model=_EXTRACTION_MODEL,
                max_tokens=1024,
                system=_EXTRACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )

            elapsed_ms = (time.time() - start) * 1000

            # Parse the response text as JSON
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

            return self._parse_response(text, elapsed_ms)

        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            logger.warning(
                "Extraction failed after %.0fms: %s", elapsed_ms, str(e)
            )
            return ExtractionResult(extraction_time_ms=elapsed_ms)

    def _parse_response(self, text: str, elapsed_ms: float) -> ExtractionResult:
        """Parse the LLM's JSON response into an ExtractionResult."""
        try:
            # Handle markdown code blocks
            cleaned = text.strip()
            if cleaned.startswith("```"):
                # Remove ```json and trailing ```
                lines = cleaned.split("\n")
                lines = [line for line in lines if not line.strip().startswith("```")]
                cleaned = "\n".join(lines)

            data = json.loads(cleaned)

            signals = [
                Signal(
                    evidence=s.get("evidence", ""),
                    implication=s.get("implication", ""),
                    confidence=_safe_confidence(s.get("confidence", 0.5)),
                )
                for s in data.get("signals", [])
                if isinstance(s, dict)
            ]

            return ExtractionResult(
                intent=data.get("intent"),
                capital=_safe_int(data.get("capital")),
                equity=_safe_int(data.get("equity")),
                income=_safe_int(data.get("income")),
                current_rent=_safe_int(data.get("current_rent")),
                owns_current_home=_safe_bool(data.get("owns_current_home")),
                is_first_time_buyer=_safe_bool(data.get("is_first_time_buyer")),
                sophistication=data.get("sophistication"),
                signals=signals,
                extraction_time_ms=elapsed_ms,
                model_used=_EXTRACTION_MODEL,
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse extraction response: %s", str(e))
            return ExtractionResult(extraction_time_ms=elapsed_ms)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CONFIDENCE_WORDS: dict[str, float] = {
    "high": 0.8,
    "medium": 0.5,
    "med": 0.5,
    "low": 0.3,
    "very high": 0.9,
    "very low": 0.2,
}


def _safe_confidence(value: Any) -> float:
    """Convert a confidence value to float, handling word labels from LLM.

    Haiku sometimes returns "high"/"medium"/"low" instead of numeric values.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in _CONFIDENCE_WORDS:
            return _CONFIDENCE_WORDS[lower]
        try:
            return float(lower)
        except ValueError:
            return 0.5
    return 0.5


def _safe_int(value: Any) -> int | None:
    """Safely convert a value to int, returning None on failure.

    Handles float strings like "200000.5" by converting through float first.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        # Try float conversion for strings like "200000.5"
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None


def _safe_bool(value: Any) -> bool | None:
    """Safely convert a value to bool, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1")
    return None
