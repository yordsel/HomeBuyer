"""PreExecutor: run proactive analyses before the LLM turn.

Takes a TurnPlan from the JobResolver and executes the proactive analyses
via the tool_executor callable. Produces a prompt fragment with pre-computed
facts that gets injected into the system prompt.

Handles:
- Dependency ordering (analyses without property_context deps run first)
- Graceful failure (logged, never blocks the turn)
- Fact enrichment via compute_facts_for_tool

Phase E-4 (#48) of Epic #23.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from homebuyer.services.faketor.facts import compute_facts_for_tool
from homebuyer.services.faketor.jobs import AnalysisSpec, TurnPlan

logger = logging.getLogger(__name__)

# Type alias for the tool executor callable used in faketor service.
# Signature: (tool_name: str, tool_input: dict) -> str (JSON result)
ToolExecutorFn = Callable[[str, dict[str, Any]], str]


@dataclass
class PreExecutionResult:
    """Output from pre-executing proactive analyses."""

    # Facts keyed by tool_name
    facts: dict[str, dict] = field(default_factory=dict)

    # Raw results for tools that produced output (for frontend blocks)
    raw_results: dict[str, Any] = field(default_factory=dict)

    # Tools that failed (name → error message)
    failures: dict[str, str] = field(default_factory=dict)

    # Execution time in milliseconds
    execution_time_ms: float = 0.0

    @property
    def has_facts(self) -> bool:
        return bool(self.facts)

    def render_prompt_fragment(self) -> str:
        """Render pre-executed facts as a system prompt fragment.

        Format matches what the AnalysisAccumulator produces, so Claude
        sees a consistent format whether facts come from pre-execution
        or from reactive tool use.
        """
        if not self.facts:
            return ""

        lines = ["=== PRE-EXECUTED ANALYSIS RESULTS ==="]
        lines.append("The following analyses were run proactively based on your query:")
        lines.append("")

        for tool_name, tool_facts in self.facts.items():
            lines.append(f"--- {tool_name} ---")
            for key, value in tool_facts.items():
                if isinstance(value, dict):
                    lines.append(f"  {key}:")
                    for k, v in value.items():
                        lines.append(f"    {k}: {v}")
                elif isinstance(value, list):
                    lines.append(f"  {key}: {json.dumps(value)}")
                else:
                    lines.append(f"  {key}: {value}")
            lines.append("")

        lines.append("=== END PRE-EXECUTED ANALYSIS RESULTS ===")
        return "\n".join(lines)


class PreExecutor:
    """Runs proactive analyses from a TurnPlan before the LLM turn.

    Usage::

        pre_executor = PreExecutor(tool_executor_fn)
        result = pre_executor.execute(turn_plan, property_context)
        prompt_fragment = result.render_prompt_fragment()
    """

    def __init__(self, tool_executor: ToolExecutorFn) -> None:
        self._tool_executor = tool_executor

    def execute(
        self,
        plan: TurnPlan,
        property_context: dict[str, Any] | None = None,
        buyer_profile: dict[str, Any] | None = None,
    ) -> PreExecutionResult:
        """Execute proactive analyses from the turn plan.

        Args:
            plan: TurnPlan with proactive_analyses from JobResolver.
            property_context: Current focus property context dict, used
                to build tool inputs for property-dependent analyses.
            buyer_profile: Buyer profile dict (from BuyerState.profile),
                used to build inputs for buyer-dependent gap tools
                (rate_penalty, dual_property, adjacent_market, etc.).

        Returns:
            PreExecutionResult with facts, raw results, and failures.
        """
        result = PreExecutionResult()

        if not plan.proactive_analyses:
            return result

        start_time = time.monotonic()

        # Order: non-property-dependent first, then property-dependent.
        # This ensures market data is available if a later analysis needs it.
        ordered = _order_analyses(plan.proactive_analyses)

        for spec in ordered:
            try:
                tool_input = _build_tool_input(spec, property_context, buyer_profile)
                raw_json = self._tool_executor(spec.tool_name, tool_input)

                # Parse result
                try:
                    raw_data = json.loads(raw_json)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "PreExecutor: non-JSON result from %s", spec.tool_name
                    )
                    continue

                # Check for error responses
                if isinstance(raw_data, dict) and raw_data.get("error"):
                    result.failures[spec.tool_name] = str(raw_data["error"])
                    logger.warning(
                        "PreExecutor: %s returned error: %s",
                        spec.tool_name,
                        raw_data["error"],
                    )
                    continue

                result.raw_results[spec.tool_name] = raw_data

                # Compute facts for prompt enrichment
                if isinstance(raw_data, (dict, list)):
                    facts = compute_facts_for_tool(spec.tool_name, raw_data)
                    if facts:
                        result.facts[spec.tool_name] = facts

            except Exception as e:
                result.failures[spec.tool_name] = str(e)
                logger.warning(
                    "PreExecutor: %s failed: %s",
                    spec.tool_name,
                    e,
                    exc_info=True,
                )

        elapsed_ms = (time.monotonic() - start_time) * 1000
        result.execution_time_ms = elapsed_ms

        logger.info(
            "PreExecutor completed: %d analyses, %d facts, %d failures, %.0fms",
            len(ordered),
            len(result.facts),
            len(result.failures),
            elapsed_ms,
        )

        return result


def _order_analyses(analyses: list[AnalysisSpec]) -> list[AnalysisSpec]:
    """Order analyses: no-dependency first, then property-dependent.

    This ensures market-level data is available before property-level
    analyses that might conceptually benefit from it.
    """
    no_deps = [a for a in analyses if not a.requires]
    has_deps = [a for a in analyses if a.requires]
    return no_deps + has_deps


def _build_tool_input(
    spec: AnalysisSpec,
    property_context: dict[str, Any] | None,
    buyer_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the input dict for a tool based on spec and available context.

    Maps tool names to their expected input parameters using the
    property_context data and buyer_profile when available.
    """
    tool_input: dict[str, Any] = {}
    prop = property_context or {}
    buyer = buyer_profile or {}

    has_property = bool(prop) and "property_context" in spec.requires
    has_buyer = bool(buyer) and "buyer_profile" in spec.requires

    if has_property:
        # --- Original tools ---
        if spec.tool_name == "get_price_prediction":
            tool_input["address"] = prop.get("address", "")

        elif spec.tool_name == "get_comparable_sales":
            tool_input["address"] = prop.get("address", "")
            if prop.get("price"):
                tool_input["target_price"] = prop["price"]

        elif spec.tool_name == "estimate_rental_income":
            tool_input["address"] = prop.get("address", "")
            if prop.get("bedrooms"):
                tool_input["bedrooms"] = prop["bedrooms"]
            if prop.get("sqft"):
                tool_input["sqft"] = prop["sqft"]

        elif spec.tool_name == "get_development_potential":
            tool_input["address"] = prop.get("address", "")

        elif spec.tool_name == "get_neighborhood_stats":
            tool_input["neighborhood"] = prop.get("neighborhood", "")

        # --- Gap tools: property-dependent ---
        elif spec.tool_name == "compute_true_cost":
            tool_input["purchase_price"] = prop.get("price", 0)
            tool_input["mortgage_rate"] = prop.get("mortgage_rate", 7.0)
            if buyer.get("capital") and prop.get("price"):
                tool_input["down_payment_pct"] = min(
                    round(buyer["capital"] / prop["price"] * 100), 100
                )
            else:
                tool_input["down_payment_pct"] = 20.0
            if buyer.get("current_rent"):
                tool_input["current_rent"] = buyer["current_rent"]
            if prop.get("year_built"):
                tool_input["year_built"] = prop["year_built"]

        elif spec.tool_name == "compute_rent_vs_buy":
            tool_input["purchase_price"] = prop.get("price", 0)
            tool_input["mortgage_rate"] = prop.get("mortgage_rate", 7.0)
            tool_input["current_rent"] = buyer.get("current_rent", 3000)
            if buyer.get("capital") and prop.get("price"):
                tool_input["down_payment_pct"] = min(
                    round(buyer["capital"] / prop["price"] * 100), 100
                )
            else:
                tool_input["down_payment_pct"] = 20.0

        elif spec.tool_name == "compute_pmi_model":
            tool_input["purchase_price"] = prop.get("price", 0)
            tool_input["mortgage_rate"] = prop.get("mortgage_rate", 7.0)
            if buyer.get("capital") and prop.get("price"):
                tool_input["down_payment_pct"] = min(
                    round(buyer["capital"] / prop["price"] * 100), 100
                )
            else:
                tool_input["down_payment_pct"] = 10.0
            if buyer.get("capital"):
                tool_input["monthly_savings"] = int(buyer["capital"] * 0.02)

        elif spec.tool_name == "compute_competition":
            if prop.get("neighborhood"):
                tool_input["neighborhood"] = prop["neighborhood"]
            if prop.get("price"):
                tool_input["price_min"] = int(prop["price"] * 0.8)
                tool_input["price_max"] = int(prop["price"] * 1.2)

        elif spec.tool_name == "compute_appreciation_stress":
            tool_input["purchase_price"] = prop.get("price", 0)
            tool_input["mortgage_rate"] = prop.get("mortgage_rate", 7.0)
            if buyer.get("capital") and prop.get("price"):
                tool_input["down_payment_pct"] = min(
                    round(buyer["capital"] / prop["price"] * 100), 100
                )
            else:
                tool_input["down_payment_pct"] = 20.0

        elif spec.tool_name == "compute_rate_penalty":
            # Requires buyer profile for existing mortgage data
            if has_buyer and buyer.get("equity") and prop.get("price"):
                # Estimate existing balance from equity + home value
                tool_input["new_purchase_price"] = prop["price"]
                tool_input["new_rate"] = prop.get("mortgage_rate", 7.0)
                if buyer.get("income"):
                    tool_input["annual_gross_income"] = buyer["income"]
            else:
                # Not enough data — will gracefully fail or return minimal result
                tool_input["new_purchase_price"] = prop.get("price", 0)
                tool_input["new_rate"] = prop.get("mortgage_rate", 7.0)

        elif spec.tool_name == "compute_dual_property":
            if has_buyer and buyer.get("equity") and prop.get("price"):
                tool_input["investment_price"] = prop["price"]
                tool_input["investment_rate"] = prop.get("mortgage_rate", 7.0)
                if buyer.get("income"):
                    tool_input["annual_gross_income"] = buyer["income"]
            else:
                tool_input["investment_price"] = prop.get("price", 0)
                tool_input["investment_rate"] = prop.get("mortgage_rate", 7.0)

        else:
            # Generic fallback: pass address if available
            if prop.get("address"):
                tool_input["address"] = prop["address"]

    # --- Gap tools: buyer-only (no property_context required) ---
    if not has_property:
        if spec.tool_name == "compute_neighborhood_lifestyle":
            # No required params — defaults to comparing all neighborhoods
            pass

        elif spec.tool_name == "compute_adjacent_market":
            if has_buyer and buyer.get("capital"):
                tool_input["budget"] = buyer["capital"]
            else:
                tool_input["budget"] = 1_000_000  # Berkeley default

    return tool_input
