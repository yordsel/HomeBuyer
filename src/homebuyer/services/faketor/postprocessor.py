"""PostProcessor: extract signals from LLM output and promote state.

After the LLM loop completes, the PostProcessor:
1. Extracts buyer signals from the LLM's response text
2. Promotes analysis conclusions to PropertyState (analyses done, discussed properties)
3. Updates BuyerState with refined classification
4. Applies confidence decay to stale segments

Phase E-7 (#51) of Epic #23.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from homebuyer.services.faketor.classification import SegmentClassifier
from homebuyer.services.faketor.extraction import SignalExtractor
from homebuyer.services.faketor.state.context import ResearchContext
from homebuyer.services.faketor.state.property import PropertyState

logger = logging.getLogger(__name__)


@dataclass
class PostProcessResult:
    """Summary of what changed during post-processing."""

    signals_extracted: int = 0
    segment_changed: bool = False
    previous_segment: str | None = None
    new_segment: str | None = None
    properties_discussed: list[int] = field(default_factory=list)
    analyses_recorded: int = 0


class PostProcessor:
    """Post-processes a completed LLM turn to update ResearchContext.

    Usage::

        processor = PostProcessor(extractor, classifier)
        result = processor.process(
            reply_text="Here's my analysis...",
            tool_calls=[{"name": "get_price_prediction", ...}],
            discussed_properties=[42],
            context=research_context,
        )
    """

    def __init__(
        self,
        extractor: SignalExtractor,
        classifier: SegmentClassifier,
    ) -> None:
        self._extractor = extractor
        self._classifier = classifier

    def process(
        self,
        reply_text: str,
        tool_calls: list[dict[str, Any]],
        discussed_properties: list[int],
        context: ResearchContext,
    ) -> PostProcessResult:
        """Run post-processing on a completed turn.

        Args:
            reply_text: The LLM's final response text.
            tool_calls: List of tool calls made during the turn.
            discussed_properties: Property IDs discussed during the turn.
            context: The ResearchContext to update.

        Returns:
            PostProcessResult summarizing what changed.
        """
        result = PostProcessResult()
        previous_segment = context.buyer.segment_id

        # 1. Extract signals from LLM output
        self._extract_output_signals(reply_text, context, result)

        # 2. Promote property analysis state
        self._promote_property_state(
            tool_calls, discussed_properties, context, result
        )

        # 3. Re-classify with updated signals
        self._reclassify(context, result)

        # Track segment change
        if context.buyer.segment_id != previous_segment:
            result.segment_changed = True
            result.previous_segment = previous_segment
            result.new_segment = context.buyer.segment_id

        return result

    def _extract_output_signals(
        self,
        reply_text: str,
        context: ResearchContext,
        result: PostProcessResult,
    ) -> None:
        """Extract buyer signals from the LLM's response text."""
        if not reply_text or not reply_text.strip():
            return

        try:
            extraction = self._extractor.extract_from_output(reply_text)
            if extraction:
                extractions = extraction.to_extractions()
                if extractions:
                    context.buyer.profile.apply_extraction(extractions)
                    result.signals_extracted = len(extractions)
                    logger.debug(
                        "PostProcessor: extracted %d signals from output",
                        len(extractions),
                    )
        except Exception as e:
            logger.warning("PostProcessor: output signal extraction failed: %s", e)

    def _promote_property_state(
        self,
        tool_calls: list[dict[str, Any]],
        discussed_properties: list[int],
        context: ResearchContext,
        result: PostProcessResult,
    ) -> None:
        """Record analyses performed and properties discussed."""
        if not discussed_properties and not tool_calls:
            return

        # Ensure PropertyState exists
        if context.property is None:
            context.property = PropertyState()

        # Record discussed properties
        result.properties_discussed = list(discussed_properties)

        # Record analyses per property
        # Group tool calls by their target property (if detectable)
        analysis_tools = {
            "get_price_prediction",
            "get_comparable_sales",
            "get_development_potential",
            "estimate_rental_income",
            "lookup_permits",
            "analyze_investment_scenarios",
        }

        # Get market snapshot timestamp for analysis records
        market_snapshot_at = time.time()

        for call in tool_calls:
            tool_name = call.get("name", "")
            if tool_name not in analysis_tools:
                continue

            tool_input = call.get("input", {})
            address = tool_input.get("address", "")

            # Build a meaningful result summary from tool input
            input_parts = [f"{k}={v}" for k, v in tool_input.items() if k != "address"]
            result_summary = (
                f"{tool_name}({', '.join(input_parts)})"
                if input_parts
                else f"{tool_name} completed"
            )

            # Record analysis for each discussed property
            for prop_id in discussed_properties:
                context.property.record_analysis(
                    property_id=prop_id,
                    address=address or f"Property #{prop_id}",
                    tool_name=tool_name,
                    result_summary=result_summary,
                    conclusion=None,
                    market_snapshot_at=market_snapshot_at,
                )
                result.analyses_recorded += 1

    def _reclassify(
        self,
        context: ResearchContext,
        result: PostProcessResult,
    ) -> None:
        """Re-classify segment after incorporating output signals."""
        try:
            classification = self._classifier.classify(
                context.buyer.profile,
                context.market,
            )
            context.buyer.record_transition(
                context.buyer.segment_id,
                classification.segment_id,
                classification.confidence,
                factor_coverage=classification.factor_coverage,
            )
        except Exception as e:
            logger.warning("PostProcessor: re-classification failed: %s", e)
