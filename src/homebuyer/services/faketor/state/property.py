"""Property state containers for the segment-driven Faketor redesign.

Tracks what the buyer is looking at (filter intent, working set, focus
property) and what they've learned (per-property analyses with staleness
detection against market snapshots).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from homebuyer.services.faketor.state.market import MarketDelta


# ---------------------------------------------------------------------------
# FilterIntent — what the buyer is searching for
# ---------------------------------------------------------------------------


@dataclass
class FilterIntent:
    """Serializable description of what the buyer is looking for.

    Mirrors ``search_properties`` parameters so it can be re-executed
    against current data when a returning user resumes.
    """

    criteria: dict[str, Any] = field(default_factory=dict)
    description: str = ""  # Human-readable summary
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria": self.criteria,
            "description": self.description,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilterIntent:
        return cls(
            criteria=data.get("criteria", {}),
            description=data.get("description", ""),
            created_at=data.get("created_at", 0.0),
        )


# ---------------------------------------------------------------------------
# FocusProperty — the single property being deeply analyzed
# ---------------------------------------------------------------------------


@dataclass
class FocusProperty:
    """The single property the buyer is currently drilling into."""

    property_id: int = 0
    address: str = ""
    last_known_status: Literal["active", "pending", "sold", "unknown"] = "unknown"
    status_checked_at: float = 0.0
    property_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "address": self.address,
            "last_known_status": self.last_known_status,
            "status_checked_at": self.status_checked_at,
            "property_context": self.property_context,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FocusProperty:
        return cls(
            property_id=data.get("property_id", 0),
            address=data.get("address", ""),
            last_known_status=data.get("last_known_status", "unknown"),
            status_checked_at=data.get("status_checked_at", 0.0),
            property_context=data.get("property_context", {}),
        )


# ---------------------------------------------------------------------------
# AnalysisRecord — a single analysis result for a property
# ---------------------------------------------------------------------------


@dataclass
class AnalysisRecord:
    """A single analysis result for a property.

    Tracks when the analysis was computed and which market snapshot it
    was computed against, enabling staleness detection.
    """

    tool_name: str = ""  # e.g. "get_price_prediction"
    result_summary: str = ""  # e.g. "Predicted: $1.35M (confidence 85%)"
    conclusion: str | None = None  # e.g. "8% overpriced based on comps"
    computed_at: float = 0.0
    market_snapshot_at: float = 0.0  # For staleness detection

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "result_summary": self.result_summary,
            "conclusion": self.conclusion,
            "computed_at": self.computed_at,
            "market_snapshot_at": self.market_snapshot_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisRecord:
        return cls(
            tool_name=data.get("tool_name", ""),
            result_summary=data.get("result_summary", ""),
            conclusion=data.get("conclusion"),
            computed_at=data.get("computed_at", 0.0),
            market_snapshot_at=data.get("market_snapshot_at", 0.0),
        )


# ---------------------------------------------------------------------------
# PropertyAnalysis — all analyses for a single property
# ---------------------------------------------------------------------------


@dataclass
class PropertyAnalysis:
    """All analyses for a single property, keyed by tool name."""

    property_id: int = 0
    address: str = ""
    analyses: dict[str, AnalysisRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "address": self.address,
            "analyses": {k: v.to_dict() for k, v in self.analyses.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PropertyAnalysis:
        return cls(
            property_id=data.get("property_id", 0),
            address=data.get("address", ""),
            analyses={
                k: AnalysisRecord.from_dict(v)
                for k, v in data.get("analyses", {}).items()
            },
        )


# ---------------------------------------------------------------------------
# PropertyState — the buyer's property research portfolio
# ---------------------------------------------------------------------------

# Analysis tools whose results are sensitive to market changes
_MARKET_SENSITIVE_TOOLS = frozenset({
    "get_price_prediction",
    "estimate_sell_vs_hold",
    "estimate_rental_income",
    "analyze_investment_scenarios",
    "get_comparable_sales",
    "get_neighborhood_stats",
})


@dataclass
class PropertyState:
    """The buyer's property research portfolio.

    Combines what they're looking at (filter intent, working set) with
    what they've learned (analyses, conclusions).

    Note: ``working_set`` is left as ``None`` here. It wraps the existing
    ``SessionWorkingSet`` and is wired in by the ``ResearchContextStore``
    when loading or creating a context.
    """

    filter_intent: FilterIntent | None = None
    focus_property: FocusProperty | None = None
    analyses: dict[int, PropertyAnalysis] = field(default_factory=dict)

    def record_analysis(
        self,
        property_id: int,
        address: str,
        tool_name: str,
        result_summary: str,
        conclusion: str | None,
        market_snapshot_at: float,
    ) -> None:
        """Record an analysis conclusion for a property."""
        if property_id not in self.analyses:
            self.analyses[property_id] = PropertyAnalysis(
                property_id=property_id,
                address=address,
            )
        pa = self.analyses[property_id]
        pa.analyses[tool_name] = AnalysisRecord(
            tool_name=tool_name,
            result_summary=result_summary,
            conclusion=conclusion,
            computed_at=time.time(),
            market_snapshot_at=market_snapshot_at,
        )

    def get_stale_analyses(
        self,
        current_snapshot_at: float,
        material_delta: MarketDelta | None,
    ) -> list[tuple[int, str, AnalysisRecord]]:
        """Find analyses needing re-computation based on market changes.

        Returns a list of (property_id, address, stale_record) tuples for
        analyses that:
        1. Were computed against a different market snapshot, AND
        2. Are market-sensitive tools, AND
        3. The market delta has material changes

        If there's no material delta, returns an empty list (no re-computation
        needed even if the snapshot changed).
        """
        if not material_delta or not material_delta.any_material:
            return []

        stale: list[tuple[int, str, AnalysisRecord]] = []
        for prop_id, pa in self.analyses.items():
            for tool_name, record in pa.analyses.items():
                if tool_name not in _MARKET_SENSITIVE_TOOLS:
                    continue
                if record.market_snapshot_at < current_snapshot_at:
                    stale.append((prop_id, pa.address, record))
        return stale

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "filter_intent": self.filter_intent.to_dict() if self.filter_intent else None,
            "focus_property": self.focus_property.to_dict() if self.focus_property else None,
            "analyses": {
                str(k): v.to_dict() for k, v in self.analyses.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PropertyState:
        return cls(
            filter_intent=(
                FilterIntent.from_dict(data["filter_intent"])
                if data.get("filter_intent")
                else None
            ),
            focus_property=(
                FocusProperty.from_dict(data["focus_property"])
                if data.get("focus_property")
                else None
            ),
            analyses={
                int(k): PropertyAnalysis.from_dict(v)
                for k, v in data.get("analyses", {}).items()
            },
        )
