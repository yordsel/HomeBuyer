"""Prompt assembly for the segment-driven Faketor redesign.

Composes the system prompt from independent, composable units.
Each component is a function: (inputs) → str with clear delimiters.

Phase D-4 (#41) of Epic #23.
"""

from __future__ import annotations

from homebuyer.services.faketor.prompts import (
    data_model,
    market,
    personality,
    preexecuted,
    property,
    return_briefing,
    segment,
    tools,
)
from homebuyer.services.faketor.state.context import ResearchContext


class PromptAssembler:
    """Assembles the system prompt from independent components.

    Each component is a function: (inputs) → str. Components have clear
    delimiters and are independently testable.
    """

    def assemble(
        self,
        context: ResearchContext,
        accumulated_facts: str | None = None,
        iteration_remaining: int | None = None,
    ) -> str:
        """Compose the full system prompt for this turn's LLM call.

        Components are assembled in a fixed order. Each component decides
        whether to emit content based on its inputs.

        Args:
            context: The persistent research context for this user.
            accumulated_facts: Fact summary from AnalysisAccumulator.
            iteration_remaining: Remaining LLM iterations for budget warning.
        """
        components = [
            personality.render(),
            data_model.render(),
            tools.render(),
            market.render(context.market),
            return_briefing.render(context),
            segment.render(
                context.buyer.segment_id,
                context.buyer.segment_confidence,
                context.buyer.profile,
                candidates=getattr(context.buyer, "segment_candidates", None),
            ),
            property.render(context.property),
            preexecuted.render(accumulated_facts),
            render_iteration_budget(iteration_remaining),
        ]

        return "\n\n".join(c for c in components if c)


def render_iteration_budget(remaining: int | None) -> str:
    """Render the iteration budget warning if running low."""
    if remaining is None:
        return ""
    if remaining <= 2:
        return (
            f"=== ITERATION BUDGET ===\n"
            f"WARNING: Only {remaining} tool-call iteration(s) remaining. "
            f"Wrap up your analysis and provide a final answer. Do NOT start "
            f"new tool calls unless absolutely essential.\n"
            f"=== END ITERATION BUDGET ==="
        )
    return ""


__all__ = ["PromptAssembler", "render_iteration_budget"]
