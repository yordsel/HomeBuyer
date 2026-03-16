"""Buyer state containers for the segment-driven Faketor redesign.

Tracks the buyer's financial profile, intent, segment classification, and
segment transition history. Every numeric field has provenance tracking via
``FieldSource`` so the system knows where data came from and how confident
it is.

Fields are ``None`` until extracted — never defaulted to zero.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Signal — raw evidence extracted from user messages
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    """A single buyer signal extracted from conversation text."""

    evidence: str  # What the buyer said
    implication: str  # What it means (e.g. "development_intent")
    confidence: float  # 0.0–1.0


# ---------------------------------------------------------------------------
# FieldSource — provenance tracking for profile fields
# ---------------------------------------------------------------------------


@dataclass
class FieldSource:
    """Provenance for a single profile field.

    Tracks where a value came from, how confident the system is, and
    whether it has decayed since the last session.
    """

    source: Literal["explicit", "extracted", "inferred", "intake_form"]
    confidence: float  # 0.0–1.0
    evidence: str  # What the buyer said or what was inferred from
    extracted_at: float  # Timestamp
    stale: bool = False  # True after confidence decay on resume

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "extracted_at": self.extracted_at,
            "stale": self.stale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FieldSource:
        return cls(
            source=data["source"],
            confidence=data["confidence"],
            evidence=data["evidence"],
            extracted_at=data["extracted_at"],
            stale=data.get("stale", False),
        )


# ---------------------------------------------------------------------------
# BuyerProfile — the buyer's complete financial and situational profile
# ---------------------------------------------------------------------------

# Core factors used by known_factor_count()
_CORE_FACTORS = ("intent", "capital", "equity", "income")


@dataclass
class BuyerProfile:
    """The buyer's complete financial and situational profile.

    Every field starts as ``None`` until extracted from conversation.
    Each value field has a companion ``FieldSource`` for provenance.
    """

    # --- Intent ---
    intent: Literal["occupy", "invest"] | None = None
    intent_source: FieldSource | None = None

    # --- Financial ---
    capital: int | None = None  # Liquid cash ($)
    capital_source: FieldSource | None = None

    equity: int | None = None  # Property equity ($)
    equity_source: FieldSource | None = None

    income: int | None = None  # Annual household gross ($)
    income_source: FieldSource | None = None

    current_rent: int | None = None  # Monthly rent if renting ($)
    current_rent_source: FieldSource | None = None

    # --- Situational ---
    owns_current_home: bool | None = None
    owns_current_home_source: FieldSource | None = None

    is_first_time_buyer: bool | None = None
    is_first_time_buyer_source: FieldSource | None = None

    # --- Derived ---
    sophistication: Literal["novice", "informed", "professional"] | None = None
    sophistication_source: FieldSource | None = None

    # --- Raw signals ---
    signals: list[Signal] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Mutation methods
    # ------------------------------------------------------------------

    def apply_extraction(self, extractions: dict[str, tuple[Any, FieldSource]]) -> list[str]:
        """Apply extracted signals, respecting confidence hierarchy.

        ``extractions`` is a dict mapping field names to (value, source) tuples.
        A field is only updated if the new source has higher confidence than
        the existing source, or the field is currently ``None``.

        Returns a list of field names that were actually updated.
        """
        updated: list[str] = []
        for field_name, (value, source) in extractions.items():
            source_attr = f"{field_name}_source"
            if not hasattr(self, field_name) or not hasattr(self, source_attr):
                continue

            existing_source: FieldSource | None = getattr(self, source_attr)
            if existing_source is None or source.confidence > existing_source.confidence:
                setattr(self, field_name, value)
                setattr(self, source_attr, source)
                updated.append(field_name)

        return updated

    def apply_confidence_decay(self, factor: float = 0.8) -> None:
        """Decay all field confidences when loading a returning user's profile.

        Multiplies every non-None FieldSource's confidence by ``factor``
        and marks it as stale.
        """
        for attr_name in dir(self):
            if attr_name.endswith("_source") and not attr_name.startswith("_"):
                source: FieldSource | None = getattr(self, attr_name)
                if source is not None:
                    source.confidence *= factor
                    source.stale = True

    def known_factor_count(self) -> int:
        """Count non-None core factors: intent, capital, equity, income."""
        return sum(1 for f in _CORE_FACTORS if getattr(self, f) is not None)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        data: dict[str, Any] = {}

        # Value fields and their sources
        for attr_name in (
            "intent", "capital", "equity", "income", "current_rent",
            "owns_current_home", "is_first_time_buyer", "sophistication",
        ):
            data[attr_name] = getattr(self, attr_name)
            source: FieldSource | None = getattr(self, f"{attr_name}_source")
            data[f"{attr_name}_source"] = source.to_dict() if source else None

        data["signals"] = [
            {"evidence": s.evidence, "implication": s.implication, "confidence": s.confidence}
            for s in self.signals
        ]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BuyerProfile:
        """Deserialize from a dict."""
        profile = cls()
        for attr_name in (
            "intent", "capital", "equity", "income", "current_rent",
            "owns_current_home", "is_first_time_buyer", "sophistication",
        ):
            if attr_name in data:
                setattr(profile, attr_name, data[attr_name])
            source_key = f"{attr_name}_source"
            if data.get(source_key):
                setattr(profile, source_key, FieldSource.from_dict(data[source_key]))

        profile.signals = [
            Signal(
                evidence=s["evidence"],
                implication=s["implication"],
                confidence=s["confidence"],
            )
            for s in data.get("signals", [])
        ]
        return profile


# ---------------------------------------------------------------------------
# SegmentTransition — records a segment change
# ---------------------------------------------------------------------------


@dataclass
class SegmentTransition:
    """Records a segment classification change with evidence."""

    from_segment: str | None
    to_segment: str
    confidence: float
    trigger: Signal | None  # Evidence that triggered transition
    triggered_at: float  # Timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_segment": self.from_segment,
            "to_segment": self.to_segment,
            "confidence": self.confidence,
            "trigger": (
                {
                    "evidence": self.trigger.evidence,
                    "implication": self.trigger.implication,
                    "confidence": self.trigger.confidence,
                }
                if self.trigger
                else None
            ),
            "triggered_at": self.triggered_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SegmentTransition:
        trigger = None
        if data.get("trigger"):
            t = data["trigger"]
            trigger = Signal(
                evidence=t["evidence"],
                implication=t["implication"],
                confidence=t["confidence"],
            )
        return cls(
            from_segment=data["from_segment"],
            to_segment=data["to_segment"],
            confidence=data["confidence"],
            trigger=trigger,
            triggered_at=data["triggered_at"],
        )


# ---------------------------------------------------------------------------
# BuyerState — wraps profile + segment + history
# ---------------------------------------------------------------------------


@dataclass
class BuyerState:
    """Complete buyer state container.

    Wraps the financial profile, current segment classification, and
    the full history of segment transitions.
    """

    profile: BuyerProfile = field(default_factory=BuyerProfile)
    segment_id: str | None = None
    segment_confidence: float = 0.0
    segment_history: list[SegmentTransition] = field(default_factory=list)

    def record_transition(
        self,
        from_segment: str | None,
        to_segment: str,
        confidence: float,
        trigger: Signal | None = None,
    ) -> None:
        """Record a segment transition in the history."""
        self.segment_id = to_segment
        self.segment_confidence = confidence
        self.segment_history.append(
            SegmentTransition(
                from_segment=from_segment,
                to_segment=to_segment,
                confidence=confidence,
                trigger=trigger,
                triggered_at=time.time(),
            )
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "segment_id": self.segment_id,
            "segment_confidence": self.segment_confidence,
            "segment_history": [t.to_dict() for t in self.segment_history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BuyerState:
        return cls(
            profile=BuyerProfile.from_dict(data.get("profile", {})),
            segment_id=data.get("segment_id"),
            segment_confidence=data.get("segment_confidence", 0.0),
            segment_history=[
                SegmentTransition.from_dict(t)
                for t in data.get("segment_history", [])
            ],
        )
