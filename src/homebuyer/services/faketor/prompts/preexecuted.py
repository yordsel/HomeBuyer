"""PreExecutedResults prompt component.

Results from pre-execution step (Phase E). Currently a placeholder —
renders the accumulated facts string from the existing pattern.

Phase D-1 (#38) of Epic #23.
"""

from __future__ import annotations


def render(accumulated_facts: str | None) -> str:
    """Render pre-executed results and accumulated facts.

    In Phase E, this will render pre-execution results from the
    TurnOrchestrator. For now, it passes through the accumulated
    facts string from the existing AnalysisAccumulator.
    """
    if not accumulated_facts or not accumulated_facts.strip():
        return ""

    return accumulated_facts  # Already formatted by AnalysisAccumulator
