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

    # IDK fields — contextual signals that aren't certain enough to commit to.
    # These are surfaced to Sonnet via the confidence nudge so it can reason
    # about them or ask a clarifying question.
    idk_fields: dict[str, str] = field(default_factory=dict)
    # e.g. {"owns_current_home": "mentioned mortgage rate lock",
    #        "intent": "asked about cap rates"}

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
extract from this single message.

THREE-VALUE PATTERN FOR BOOLEAN & INTENT FIELDS:
For intent, owns_current_home, and is_first_time_buyer, use:
- The definite value (e.g., "occupy", true, false) when EXPLICITLY stated
- "idk" when there is a CONTEXTUAL SIGNAL but no explicit statement
- null when there is NO relevant signal at all

"idk" means "there is evidence pointing this direction but the user didn't \
say it outright." This lets the downstream system ask a clarifying question.

RULES:
- Dollar amounts should be integers (no decimals)
- If someone says "about 200k" → capital: 200000
- If someone says "I make around 150" in context of salary → income: 150000
- Each signal should explain what was detected and why
- When returning "idk", ALWAYS include a signal explaining the evidence

INTENT EXTRACTION:
- "I want to buy a home to live in" → intent: "occupy" (explicit)
- "I want to invest in rental properties" → intent: "invest" (explicit)
- "What's a realistic budget to settle down in Berkeley?" → intent: "idk" \
(settling down implies occupy, but not stated)
- "How are rents trending in South Berkeley?" → intent: "idk" \
(rent question implies invest, but could be a renter asking)
- "Tell me about the Berkeley market" → intent: null (no directional signal)

OWNERSHIP EXTRACTION:
- "I own a home in Oakland" → owns_current_home: true (explicit)
- "I'm currently renting" → owns_current_home: false (explicit)
- "My rate is locked at 3.1% and I'd hate to give it up" → \
owns_current_home: "idk" (having a mortgage rate implies ownership)
- "I want to tap into my home equity" → owns_current_home: "idk" \
(equity implies ownership)
- "I'm exploring Berkeley" → owns_current_home: null (no signal)

FIRST-TIME BUYER EXTRACTION:
- "This is my first home purchase" → is_first_time_buyer: true (explicit)
- "I've bought and sold several properties" → is_first_time_buyer: false (explicit)
- "I don't really understand what escrow means" → is_first_time_buyer: "idk" \
(lack of knowledge suggests first-time, but not certain)
- "Looking at Berkeley homes" → is_first_time_buyer: null (no signal)

IMPLICIT CASH/FINANCING SIGNALS:
- "all-cash", "pay cash", "no mortgage", "no financing needed" → add a signal \
with implication "cash_buyer" and confidence 0.8. Do NOT fabricate a capital \
number — leave capital as null, but record the cash intent as a signal.
- "for my client who has $X" or "my investor with $X budget" → capital: X \
(third-party framing is still a capital statement)
- "I have enough to buy outright" → signal with implication "cash_buyer", \
confidence 0.7
- "looking to use a mortgage" or "need financing" → signal with implication \
"needs_financing", confidence 0.8"""

_EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": ["string", "null"],
            "enum": ["occupy", "invest", "idk", None],
            "description": "Buy to live in (occupy), investment (invest), or idk if contextual signal exists but not explicit",
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
            "type": ["boolean", "string", "null"],
            "description": "Whether the buyer currently owns a home. Use 'idk' if contextual signal (e.g., mentions mortgage rate, equity) but not explicitly stated",
        },
        "is_first_time_buyer": {
            "type": ["boolean", "string", "null"],
            "description": "Whether this is their first home purchase. Use 'idk' if contextual signal (e.g., unfamiliar with terms) but not explicitly stated",
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

            # Collect idk fields with evidence from signals
            idk_fields: dict[str, str] = {}
            raw_intent = data.get("intent")
            raw_owns = data.get("owns_current_home")
            raw_first_time = data.get("is_first_time_buyer")

            if raw_intent == "idk":
                evidence = _find_signal_evidence(signals, "intent")
                idk_fields["intent"] = evidence
                raw_intent = None

            if raw_owns == "idk":
                evidence = _find_signal_evidence(
                    signals, "owns_current_home", "ownership", "mortgage"
                )
                idk_fields["owns_current_home"] = evidence
                raw_owns = None

            if raw_first_time == "idk":
                evidence = _find_signal_evidence(
                    signals, "first_time", "first-time", "novice"
                )
                idk_fields["is_first_time_buyer"] = evidence
                raw_first_time = None

            return ExtractionResult(
                intent=raw_intent if raw_intent in ("occupy", "invest") else None,
                capital=_safe_int(data.get("capital")),
                equity=_safe_int(data.get("equity")),
                income=_safe_int(data.get("income")),
                current_rent=_safe_int(data.get("current_rent")),
                owns_current_home=_safe_bool(raw_owns),
                is_first_time_buyer=_safe_bool(raw_first_time),
                sophistication=data.get("sophistication"),
                signals=signals,
                idk_fields=idk_fields,
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


def _find_signal_evidence(signals: list[Signal], *keywords: str) -> str:
    """Find the evidence string from signals matching any of the keywords."""
    for signal in signals:
        text = (signal.implication + " " + signal.evidence).lower()
        if any(kw in text for kw in keywords):
            return signal.evidence
    return "contextual signal detected"


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
