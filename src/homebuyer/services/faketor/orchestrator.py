"""TurnOrchestrator: 9-step pipeline for segment-driven Faketor turns.

Coordinates the full turn lifecycle:
1. Load or create research context
2. Extract buyer signals from user message
3. Classify buyer segment
4. Resolve jobs → TurnPlan
5. Pre-execute proactive analyses
6. Assemble system prompt
7. Run LLM loop (Claude API with tool use)
8. Post-process (extract signals from LLM output, promote state)
9. Persist research context

Phase E-6 (#50) of Epic #23.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from homebuyer.services.faketor.accumulator import AnalysisAccumulator
from homebuyer.services.faketor.classification import SegmentClassifier
from homebuyer.services.faketor.extraction import SignalExtractor
from homebuyer.services.faketor.jobs import JobResolver, TurnPlan
from homebuyer.services.faketor.postprocessor import PostProcessor
from homebuyer.services.faketor.prompts import PromptAssembler, render_iteration_budget
from homebuyer.services.faketor.state.context import ResearchContext, ResearchContextStore
from homebuyer.services.faketor.tools.executor import ToolExecutor
from homebuyer.services.faketor.tools.preexecution import PreExecutionResult, PreExecutor
from homebuyer.services.faketor.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-sonnet-4-20250514"
_MAX_ITERATIONS = 12
_FALLBACK_REPLY = "Here's what I found based on my analysis so far."

# Shared tool labels for SSE events — keeps orchestrator consistent with legacy service
_TOOL_LABELS: dict[str, str] = {
    "lookup_property": "Looking up property...",
    "get_price_prediction": "Running price prediction...",
    "get_comparable_sales": "Finding comparable sales...",
    "get_development_potential": "Checking development potential...",
    "get_neighborhood_stats": "Getting neighborhood stats...",
    "get_market_summary": "Loading market data...",
    "estimate_rental_income": "Estimating rental income...",
    "analyze_investment_scenarios": "Comparing investment scenarios...",
    "estimate_sell_vs_hold": "Analyzing sell vs hold...",
    "get_improvement_simulation": "Simulating improvements...",
    "search_properties": "Searching properties...",
    "lookup_permits": "Looking up permits...",
    "query_database": "Querying database...",
    "undo_filter": "Undoing last filter...",
    "generate_investment_prospectus": "Generating investment prospectus...",
    "lookup_regulation": "Looking up Berkeley regulations...",
    "update_working_set": "Updating property list...",
    "lookup_glossary_term": "Looking up definition...",
    # Phase F gap tools
    "compute_true_cost": "Computing true ownership cost...",
    "rent_vs_buy": "Comparing rent vs buy...",
    "pmi_model": "Modeling PMI costs...",
    "rate_penalty": "Calculating rate penalty...",
    "appreciation_stress_test": "Running appreciation stress test...",
    "competition_assessment": "Analyzing competition...",
    "neighborhood_lifestyle": "Matching neighborhoods to lifestyle...",
    "dual_property_model": "Comparing two properties...",
    "yield_ranking": "Ranking by investment yield...",
    "adjacent_market_comparison": "Exploring adjacent markets...",
}


@dataclass
class TurnMetrics:
    """Timing and telemetry for a single turn."""

    extraction_ms: float = 0.0
    classification_ms: float = 0.0
    job_resolution_ms: float = 0.0
    preexecution_ms: float = 0.0
    prompt_assembly_ms: float = 0.0
    llm_loop_ms: float = 0.0
    postprocess_ms: float = 0.0
    total_ms: float = 0.0
    llm_iterations: int = 0
    tools_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "extraction_ms": round(self.extraction_ms, 1),
            "classification_ms": round(self.classification_ms, 1),
            "job_resolution_ms": round(self.job_resolution_ms, 1),
            "preexecution_ms": round(self.preexecution_ms, 1),
            "prompt_assembly_ms": round(self.prompt_assembly_ms, 1),
            "llm_loop_ms": round(self.llm_loop_ms, 1),
            "postprocess_ms": round(self.postprocess_ms, 1),
            "total_ms": round(self.total_ms, 1),
            "llm_iterations": self.llm_iterations,
            "tools_used": self.tools_used,
        }


@dataclass
class TurnResult:
    """Output of a non-streaming orchestrated turn."""

    reply: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    discussed_properties: list[int] = field(default_factory=list)
    metrics: TurnMetrics = field(default_factory=TurnMetrics)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.error:
            return {"error": self.error}
        return {
            "reply": self.reply,
            "tool_calls": self.tool_calls,
            "blocks": self.blocks,
        }


class TurnOrchestrator:
    """Orchestrates a single Faketor chat turn through the 9-step pipeline.

    Usage (non-streaming)::

        orchestrator = TurnOrchestrator(
            client=anthropic_client,
            context_store=context_store,
            signal_extractor=signal_extractor,
            segment_classifier=segment_classifier,
            tool_executor=typed_tool_executor,
            pre_executor=pre_executor,
            registry=tool_registry,
        )
        result = await orchestrator.run(user_id, message, history, property_context)

    Usage (streaming)::

        async for event in orchestrator.run_stream(user_id, message, history, ...):
            yield event  # SSE-compatible dict
    """

    def __init__(
        self,
        *,
        client: Any,  # anthropic.Anthropic
        context_store: ResearchContextStore,
        signal_extractor: SignalExtractor,
        segment_classifier: SegmentClassifier,
        tool_executor: ToolExecutor,
        pre_executor: PreExecutor,
        registry: ToolRegistry,
        job_resolver: JobResolver | None = None,
        prompt_assembler: PromptAssembler | None = None,
        post_processor: PostProcessor | None = None,
        model: str = _CLAUDE_MODEL,
        max_iterations: int = _MAX_ITERATIONS,
    ) -> None:
        self._client = client
        self._context_store = context_store
        self._extractor = signal_extractor
        self._classifier = segment_classifier
        self._tool_executor = tool_executor
        self._pre_executor = pre_executor
        self._registry = registry
        self._resolver = job_resolver or JobResolver()
        self._assembler = prompt_assembler or PromptAssembler()
        self._post_processor = post_processor or PostProcessor(
            signal_extractor, segment_classifier
        )
        self._model = model
        self._max_iterations = max_iterations

    # ------------------------------------------------------------------
    # Step 1: Load or create context
    # ------------------------------------------------------------------

    async def _load_context(self, user_id: str) -> ResearchContext:
        return await self._context_store.load_or_create(user_id)

    # ------------------------------------------------------------------
    # Step 2: Extract buyer signals
    # ------------------------------------------------------------------

    async def _extract_signals(
        self,
        message: str,
        context: ResearchContext,
        metrics: TurnMetrics,
    ) -> None:
        """Extract buyer signals from user message and merge into context.

        Runs the synchronous Haiku LLM call in a thread executor to avoid
        blocking the async event loop (~200ms per call).
        """
        start = time.monotonic()
        try:
            loop = asyncio.get_running_loop()
            extraction = await loop.run_in_executor(
                None, self._extractor.extract, message
            )
            if extraction and not extraction.is_empty():
                extractions = extraction.to_extractions()
                context.buyer.profile.apply_extraction(extractions)
        except Exception as e:
            logger.warning("Signal extraction failed: %s", e)
        metrics.extraction_ms = (time.monotonic() - start) * 1000

    # ------------------------------------------------------------------
    # Step 3: Classify segment
    # ------------------------------------------------------------------

    def _classify_segment(
        self,
        context: ResearchContext,
        metrics: TurnMetrics,
    ) -> None:
        """Classify buyer segment and update context.

        Also computes top-N alternative candidates for ambiguous cases.
        Candidates are stored on ``context.buyer.segment_candidates``
        (ephemeral, not persisted) for use by the prompt renderer.
        """
        start = time.monotonic()
        mortgage_rate = context.market.mortgage_rate_30yr or 6.5
        median_price = (
            context.market.berkeley_wide.median_sale_price or 1_300_000
        )
        try:
            result = self._classifier.classify(
                context.buyer.profile,
                mortgage_rate=mortgage_rate,
                median_price=median_price,
            )
            # Guard: only record transition when classifier returns a segment
            if result.segment_id is not None:
                context.buyer.record_transition(
                    context.buyer.segment_id,
                    result.segment_id,
                    result.confidence,
                    factor_coverage=result.factor_coverage,
                )

            # Compute alternatives for ambiguous classifications
            context.buyer.segment_candidates = (
                self._classifier.classify_with_alternatives(
                    context.buyer.profile,
                    mortgage_rate=mortgage_rate,
                    median_price=median_price,
                )
            )
        except Exception as e:
            logger.warning("Segment classification failed: %s", e)
            context.buyer.segment_candidates = []
        metrics.classification_ms = (time.monotonic() - start) * 1000

    # ------------------------------------------------------------------
    # Step 4: Resolve jobs → TurnPlan
    # ------------------------------------------------------------------

    def _resolve_jobs(
        self,
        message: str,
        context: ResearchContext,
        metrics: TurnMetrics,
    ) -> TurnPlan:
        start = time.monotonic()
        segment_result = None
        if context.buyer.segment_id:
            from homebuyer.services.faketor.classification import SegmentResult
            segment_result = SegmentResult(
                segment_id=context.buyer.segment_id,
                confidence=context.buyer.segment_confidence,
                reasoning="from context",
                factor_coverage=context.buyer.segment_factor_coverage,
            )
        # Extract alternative segment IDs from candidates for broader
        # pre-execution coverage (multi-segment classification, #82)
        alt_ids: list[str] | None = None
        candidates = getattr(context.buyer, "segment_candidates", None)
        if candidates and len(candidates) > 1:
            alt_ids = [
                c.segment_id for c in candidates
                if c.segment_id != context.buyer.segment_id
                and c.confidence > 0.25
            ]

        plan = self._resolver.resolve(
            message, segment_result, context,
            alternative_segment_ids=alt_ids,
        )
        metrics.job_resolution_ms = (time.monotonic() - start) * 1000
        return plan

    # ------------------------------------------------------------------
    # Step 5: Pre-execute proactive analyses
    # ------------------------------------------------------------------

    def _pre_execute(
        self,
        plan: TurnPlan,
        property_context: dict[str, Any] | None,
        metrics: TurnMetrics,
        context: ResearchContext | None = None,
    ) -> PreExecutionResult:
        start = time.monotonic()
        # Build buyer profile dict for gap tools that need buyer data
        buyer_profile: dict[str, Any] | None = None
        if context and context.buyer and context.buyer.profile:
            bp = context.buyer.profile
            buyer_profile = {
                k: v
                for k, v in {
                    "capital": bp.capital,
                    "equity": bp.equity,
                    "income": bp.income,
                    "current_rent": bp.current_rent,
                    "owns_current_home": bp.owns_current_home,
                    "is_first_time_buyer": bp.is_first_time_buyer,
                    "intent": bp.intent,
                }.items()
                if v is not None
            }
            if not buyer_profile:
                buyer_profile = None
        result = self._pre_executor.execute(plan, property_context, buyer_profile)
        metrics.preexecution_ms = (time.monotonic() - start) * 1000
        return result

    # ------------------------------------------------------------------
    # Step 6: Assemble system prompt
    # ------------------------------------------------------------------

    def _assemble_prompt(
        self,
        context: ResearchContext,
        pre_result: PreExecutionResult,
        accumulated_facts: str | None,
        iteration_remaining: int | None,
        working_set_descriptor: str,
        property_context: dict[str, Any] | None,
        plan: TurnPlan,
        metrics: TurnMetrics,
    ) -> str:
        start = time.monotonic()

        # Combine pre-executed facts with accumulated facts
        all_facts_parts = []
        pre_fragment = pre_result.render_prompt_fragment()
        if pre_fragment:
            all_facts_parts.append(pre_fragment)
        if accumulated_facts:
            all_facts_parts.append(accumulated_facts)
        combined_facts = "\n\n".join(all_facts_parts) if all_facts_parts else None

        prompt = self._assembler.assemble(
            context=context,
            accumulated_facts=combined_facts,
            iteration_remaining=iteration_remaining,
        )

        # Append framing directive from TurnPlan
        if plan.framing.tone or plan.framing.lead_with:
            prompt += "\n\n=== RESPONSE FRAMING ===\n"
            if plan.framing.tone:
                prompt += f"Tone: {plan.framing.tone}\n"
            if plan.framing.lead_with:
                prompt += f"Lead with: {plan.framing.lead_with}\n"
            if plan.framing.avoid:
                prompt += f"Avoid: {plan.framing.avoid}\n"
            prompt += "=== END RESPONSE FRAMING ==="

        # Append secondary nudge
        if plan.secondary_nudge:
            prompt += (
                f"\n\nSECONDARY SUGGESTION: If appropriate, weave in: "
                f'"{plan.secondary_nudge}"'
            )

        # Append property context as JSON for backward compat
        if property_context:
            prompt += (
                f"\n\nCURRENT PROPERTY CONTEXT:\n"
                f"{json.dumps(property_context, indent=2)}"
            )

        if working_set_descriptor:
            prompt += f"\n\n{working_set_descriptor}"

        metrics.prompt_assembly_ms = (time.monotonic() - start) * 1000
        return prompt

    # ------------------------------------------------------------------
    # Step 7: LLM loop (non-streaming)
    # ------------------------------------------------------------------

    def _run_llm_loop(
        self,
        system_prompt: str,
        messages: list[dict],
        accumulator: AnalysisAccumulator,
        metrics: TurnMetrics,
        executor: ToolExecutor | None = None,
    ) -> TurnResult:
        """Run the Claude API loop with tool use (non-streaming)."""
        start = time.monotonic()
        result = TurnResult()
        tool_schemas = self._registry.get_tool_schemas()
        effective_executor = executor or self._tool_executor

        for iteration in range(self._max_iterations):
            metrics.llm_iterations = iteration + 1

            if iteration == 0:
                logger.debug(
                    "LLM loop system prompt (%d chars):\n%s",
                    len(system_prompt),
                    system_prompt,
                )

            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=messages,
                    tools=tool_schemas,
                )
            except Exception as e:
                logger.error("Claude API error: %s", e)
                result.error = f"AI service error: {e}"
                break

            # Extract text
            text_parts = [b.text for b in response.content if b.type == "text"]

            # Check for tool use
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            if not tool_use_blocks:
                # No tools — done
                result.reply = "\n\n".join(text_parts) or _FALLBACK_REPLY
                break

            # Append assistant response with tool_use blocks
            messages.append({"role": "assistant", "content": response.content})

            # Execute tools
            tool_results_for_api = []
            for tool_block in tool_use_blocks:
                tool_result = effective_executor.execute(
                    tool_block.name, tool_block.input
                )
                metrics.tools_used.append(tool_block.name)
                result.tool_calls.append({
                    "name": tool_block.name,
                    "input": tool_block.input,
                })

                # Record facts in accumulator
                if tool_result.has_facts:
                    accumulator.record(
                        tool_block.name, tool_block.input, tool_result.facts
                    )

                # Collect blocks
                block = tool_result.to_block()
                if block:
                    result.blocks.append(block)

                # Track discussed properties
                if tool_result.discussed_property_id:
                    result.discussed_properties.append(
                        tool_result.discussed_property_id
                    )

                tool_results_for_api.append(
                    tool_result.to_anthropic_result(tool_block.id)
                )

            # Append tool results and update system prompt with facts
            messages.append({"role": "user", "content": tool_results_for_api})

            summary = accumulator.get_summary()
            if summary:
                system_prompt = self._update_system_prompt_with_facts(
                    system_prompt, summary, iteration
                )

            if response.stop_reason == "end_turn":
                result.reply = "\n\n".join(text_parts) or _FALLBACK_REPLY
                break
        else:
            # Hit max iterations
            result.reply = _FALLBACK_REPLY

        metrics.llm_loop_ms = (time.monotonic() - start) * 1000
        return result

    def _update_system_prompt_with_facts(
        self,
        prompt: str,
        facts_summary: str,
        iteration: int,
    ) -> str:
        """Update system prompt with accumulated facts and iteration budget."""
        remaining = self._max_iterations - iteration - 1
        budget_str = render_iteration_budget(remaining)
        if budget_str:
            return prompt + f"\n\n{facts_summary}\n\n{budget_str}"
        return prompt + f"\n\n{facts_summary}"

    # ------------------------------------------------------------------
    # Step 8: Post-process
    # ------------------------------------------------------------------

    def _post_process(
        self,
        llm_result: TurnResult,
        context: ResearchContext,
        metrics: TurnMetrics,
    ) -> None:
        """Delegate to PostProcessor for signal extraction and state promotion."""
        start = time.monotonic()
        try:
            pp_result = self._post_processor.process(
                reply_text=llm_result.reply,
                tool_calls=llm_result.tool_calls,
                discussed_properties=llm_result.discussed_properties,
                context=context,
            )
            if pp_result.segment_changed:
                logger.info(
                    "Segment changed: %s → %s",
                    pp_result.previous_segment,
                    pp_result.new_segment,
                )
        except Exception as e:
            logger.warning("Post-processing failed: %s", e)
        metrics.postprocess_ms = (time.monotonic() - start) * 1000

    # ------------------------------------------------------------------
    # Step 9: Persist
    # ------------------------------------------------------------------

    async def _persist_context(self, context: ResearchContext) -> None:
        await self._context_store.persist(context)

    # ------------------------------------------------------------------
    # SSE event helpers
    # ------------------------------------------------------------------

    def _build_resume_briefing_data(
        self, context: ResearchContext
    ) -> dict[str, Any] | None:
        """Build resume briefing data for returning users with material changes."""
        delta = context.market_delta
        if delta is None or not delta.any_material:
            return None

        data: dict[str, Any] = {"market_changes": []}

        if delta.rate_material:
            direction = "up" if delta.rate_change > 0 else "down"
            data["market_changes"].append({
                "type": "mortgage_rate",
                "direction": direction,
                "change": round(abs(delta.rate_change), 2),
                "change_pct": round(delta.rate_change_pct, 1),
            })

        if delta.price_material:
            direction = "up" if delta.median_price_change > 0 else "down"
            data["market_changes"].append({
                "type": "median_price",
                "direction": direction,
                "change": abs(delta.median_price_change),
                "change_pct": round(delta.median_price_change_pct, 1),
            })

        if delta.inventory_material:
            direction = "up" if delta.inventory_change > 0 else "down"
            data["market_changes"].append({
                "type": "inventory",
                "direction": direction,
                "change": abs(delta.inventory_change),
                "change_pct": round(delta.inventory_change_pct, 1),
            })

        # Focus property
        focus = context.property.focus_property
        if focus and focus.address:
            data["focus_property"] = {
                "address": focus.address,
                "last_known_status": focus.last_known_status,
            }

        # Stale analyses
        try:
            stale = context.property.get_stale_analyses(
                context.market.snapshot_at, delta,
            )
            if stale:
                data["stale_analyses"] = [
                    {"tool": record.tool_name, "address": address, "property_id": prop_id}
                    for prop_id, address, record in stale
                ]
        except Exception:
            pass  # Non-critical

        return data

    def _build_profile_summary(self, context: ResearchContext) -> str:
        """Build a human-readable profile summary for the segment_update event."""
        profile = context.buyer.profile
        parts = []
        if profile.intent:
            parts.append(f"Intent: {profile.intent}")
        if profile.capital is not None:
            parts.append(f"Capital: ${profile.capital:,.0f}")
        if profile.income is not None:
            parts.append(f"Income: ${profile.income:,.0f}")
        if profile.is_first_time_buyer is not None:
            parts.append(
                "First-time buyer" if profile.is_first_time_buyer else "Not first-time"
            )
        return " | ".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Public API: run (non-streaming)
    # ------------------------------------------------------------------

    def _effective_tool_executor(
        self, tool_executor_override: ToolExecutor | None
    ) -> ToolExecutor:
        """Return the per-request tool executor or the default one."""
        return tool_executor_override or self._tool_executor

    def _apply_buyer_context(
        self,
        context: ResearchContext,
        buyer_context: dict[str, Any] | None,
    ) -> None:
        """Seed buyer profile from frontend intake form data."""
        if not buyer_context:
            return
        profile = context.buyer.profile
        if "intent" in buyer_context and buyer_context["intent"]:
            profile.intent = buyer_context["intent"]
        if "capital" in buyer_context and buyer_context["capital"] is not None:
            profile.capital = buyer_context["capital"]
        if "income" in buyer_context and buyer_context["income"] is not None:
            profile.income = buyer_context["income"]
        if "current_rent" in buyer_context and buyer_context["current_rent"] is not None:
            profile.current_rent = buyer_context["current_rent"]
        if "is_first_time_buyer" in buyer_context and buyer_context["is_first_time_buyer"] is not None:
            profile.is_first_time_buyer = buyer_context["is_first_time_buyer"]

    async def run(
        self,
        user_id: str,
        message: str,
        history: list[dict],
        property_context: dict[str, Any] | None = None,
        working_set_descriptor: str = "",
        tool_executor: ToolExecutor | None = None,
        buyer_context: dict[str, Any] | None = None,
    ) -> TurnResult:
        """Execute the full 9-step pipeline for a non-streaming turn.

        Args:
            tool_executor: Optional per-request ToolExecutor override.
                Use this to inject a session-aware executor that handles
                working-set scoping. Falls back to the default executor
                configured at init time.
            buyer_context: Optional buyer intake data from frontend form.
        """
        total_start = time.monotonic()
        metrics = TurnMetrics()
        effective_executor = self._effective_tool_executor(tool_executor)

        # Step 1: Load context
        context = await self._load_context(user_id)

        # Apply buyer intake if provided (seeds profile for turn 1)
        self._apply_buyer_context(context, buyer_context)

        # Step 2: Extract signals (async — runs Haiku in thread pool)
        await self._extract_signals(message, context, metrics)

        # Step 3: Classify segment
        self._classify_segment(context, metrics)

        # Step 4: Resolve jobs
        plan = self._resolve_jobs(message, context, metrics)

        # Step 5: Pre-execute
        pre_result = self._pre_execute(plan, property_context, metrics, context)

        # Step 6: Assemble prompt
        system_prompt = self._assemble_prompt(
            context=context,
            pre_result=pre_result,
            accumulated_facts=None,
            iteration_remaining=None,
            working_set_descriptor=working_set_descriptor,
            property_context=property_context,
            plan=plan,
            metrics=metrics,
        )

        # Step 7: LLM loop
        messages = list(history) + [{"role": "user", "content": message}]
        accumulator = AnalysisAccumulator()
        result = self._run_llm_loop(
            system_prompt, messages, accumulator, metrics, effective_executor
        )

        # Step 8: Post-process
        self._post_process(result, context, metrics)

        # Step 9: Persist
        await self._persist_context(context)

        metrics.total_ms = (time.monotonic() - total_start) * 1000
        result.metrics = metrics

        logger.info(
            "Turn completed: user=%s segment=%s request=%s tools=%d time=%.0fms",
            user_id,
            context.buyer.segment_id,
            plan.request_type.value,
            len(metrics.tools_used),
            metrics.total_ms,
        )

        return result

    # ------------------------------------------------------------------
    # Public API: run_stream (SSE-compatible streaming)
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        user_id: str,
        message: str,
        history: list[dict],
        property_context: dict[str, Any] | None = None,
        working_set_descriptor: str = "",
        tool_executor: ToolExecutor | None = None,
        buyer_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute the 9-step pipeline with SSE streaming events.

        Args:
            tool_executor: Optional per-request ToolExecutor override.
            buyer_context: Optional buyer intake data from frontend form.

        Yields events compatible with the existing SSE format:
        - {"event": "tool_start", "data": {"name": "..."}}
        - {"event": "tool_end", "data": {...}}
        - {"event": "tool_result", "data": {"name": "...", "block": ...}}
        - {"event": "text_delta", "data": {"text": "..."}}
        - {"event": "working_set", "data": {...}}
        - {"event": "segment_update", "data": {"segment": "...", "confidence": ...}}
        - {"event": "resume_briefing", "data": {"market_changes": [...], ...}}
        - {"event": "pre_execution_start", "data": {"tools": [...]}}
        - {"event": "pre_execution_complete", "data": {"tools_run": N}}
        - {"event": "discussed_property", "data": {"property_id": ...}}
        - {"event": "done", "data": {"reply": "...", "tool_calls": [...], "blocks": [...]}}
        - {"event": "error", "data": {"message": "..."}}
        """
        total_start = time.monotonic()
        metrics = TurnMetrics()
        effective_executor = self._effective_tool_executor(tool_executor)

        # Steps 1-6: Same as non-streaming, but with SSE events for new steps
        context = await self._load_context(user_id)

        # Apply buyer intake if provided (seeds profile for turn 1)
        self._apply_buyer_context(context, buyer_context)

        # Emit resume_briefing if returning user has material market changes
        briefing_data = self._build_resume_briefing_data(context)
        if briefing_data:
            yield {"event": "resume_briefing", "data": briefing_data}

        await self._extract_signals(message, context, metrics)
        self._classify_segment(context, metrics)

        # Emit segment_update after classification
        if context.buyer.segment_id:
            yield {
                "event": "segment_update",
                "data": {
                    "segment": context.buyer.segment_id,
                    "confidence": round(context.buyer.segment_confidence, 2),
                    "profile_summary": self._build_profile_summary(context),
                },
            }

        plan = self._resolve_jobs(message, context, metrics)

        # Emit pre_execution_start/complete around pre-execution
        pre_tools = [a.tool_name for a in plan.proactive_analyses]
        if pre_tools:
            yield {
                "event": "pre_execution_start",
                "data": {"tools": pre_tools},
            }

        pre_result = self._pre_execute(plan, property_context, metrics, context)

        if pre_tools:
            yield {
                "event": "pre_execution_complete",
                "data": {"tools_run": len(pre_result.raw_results)},
            }

        system_prompt = self._assemble_prompt(
            context=context,
            pre_result=pre_result,
            accumulated_facts=None,
            iteration_remaining=None,
            working_set_descriptor=working_set_descriptor,
            property_context=property_context,
            plan=plan,
            metrics=metrics,
        )

        # Step 7: Streaming LLM loop
        messages = list(history) + [{"role": "user", "content": message}]
        accumulator = AnalysisAccumulator()
        tool_schemas = self._registry.get_tool_schemas()
        tool_calls_log: list[dict] = []
        blocks: list[dict] = []
        all_text_parts: list[str] = []
        discussed_properties: list[int] = []

        llm_start = time.monotonic()
        llm_error = False

        try:
            for iteration in range(self._max_iterations):
                metrics.llm_iterations = iteration + 1

                try:
                    with self._client.messages.stream(
                        model=self._model,
                        max_tokens=4096,
                        system=system_prompt,
                        messages=messages,
                        tools=tool_schemas,
                    ) as stream:
                        # Stream text deltas in real time as they arrive
                        iteration_text: list[str] = []
                        for text_chunk in stream.text_stream:
                            yield {"event": "text_delta", "data": {"text": text_chunk}}
                            iteration_text.append(text_chunk)

                        # Get the full response for tool block extraction
                        response = stream.get_final_message()

                except Exception as e:
                    logger.error("Claude API stream error: %s", e)
                    yield {"event": "error", "data": {"message": f"AI service error: {e}"}}
                    llm_error = True
                    break

                # Concatenate this iteration's streamed tokens into one string
                iteration_joined = "".join(iteration_text)

                # Check if Claude is done (no tool use)
                if response.stop_reason == "end_turn":
                    if iteration_joined:
                        all_text_parts.append(iteration_joined)
                    break

                # Check for tool use blocks
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                if not tool_use_blocks:
                    if iteration_joined:
                        all_text_parts.append(iteration_joined)
                    break

                # Mid-loop: add paragraph break between pre-tool text and
                # post-tool text so they don't jam together in rendering
                if iteration_joined:
                    all_text_parts.append(iteration_joined)
                    yield {"event": "text_delta", "data": {"text": "\n\n"}}

                # Append assistant response
                messages.append({"role": "assistant", "content": response.content})

                # Execute tools
                tool_results_for_api = []
                for tool_block in tool_use_blocks:
                    yield {
                        "event": "tool_start",
                        "data": {
                            "name": tool_block.name,
                            "label": _TOOL_LABELS.get(
                                tool_block.name,
                                f"Using {tool_block.name}...",
                            ),
                            "input": tool_block.input,
                        },
                    }

                    tool_result = effective_executor.execute(
                        tool_block.name, tool_block.input
                    )
                    metrics.tools_used.append(tool_block.name)
                    tool_calls_log.append({
                        "name": tool_block.name,
                        "input": tool_block.input,
                    })

                    yield {
                        "event": "tool_end",
                        "data": {
                            "name": tool_block.name,
                        },
                    }

                    # Record facts
                    if tool_result.has_facts:
                        accumulator.record(
                            tool_block.name, tool_block.input, tool_result.facts
                        )

                    # Emit tool result with block
                    block = tool_result.to_block()
                    if block:
                        blocks.append(block)

                    yield {
                        "event": "tool_result",
                        "data": {
                            "name": tool_block.name,
                            "block": block,
                        },
                    }

                    # Track discussed properties
                    if tool_result.discussed_property_id:
                        discussed_properties.append(tool_result.discussed_property_id)
                        yield {
                            "event": "discussed_property",
                            "data": {
                                "property_id": tool_result.discussed_property_id,
                            },
                        }

                    tool_results_for_api.append(
                        tool_result.to_anthropic_result(tool_block.id)
                    )

                # Append tool results
                messages.append({"role": "user", "content": tool_results_for_api})

                # Update system prompt with facts
                summary = accumulator.get_summary()
                if summary:
                    system_prompt = self._update_system_prompt_with_facts(
                        system_prompt, summary, iteration
                    )

                if response.stop_reason == "end_turn":
                    break
        finally:
            # Always persist context — even on LLM errors — so that signals
            # extracted in steps 2-3 are not lost for authenticated users.
            metrics.llm_loop_ms = (time.monotonic() - llm_start) * 1000
            await self._persist_context(context)

        if llm_error:
            return

        # Final text — already streamed as text_delta events above
        reply = "\n\n".join(all_text_parts) or _FALLBACK_REPLY

        # Step 8: Post-process
        pre_segment = context.buyer.segment_id
        llm_result = TurnResult(
            reply=reply,
            tool_calls=tool_calls_log,
            blocks=blocks,
            discussed_properties=discussed_properties,
        )
        self._post_process(llm_result, context, metrics)

        # Emit updated segment if it changed during post-processing
        if context.buyer.segment_id and context.buyer.segment_id != pre_segment:
            yield {
                "event": "segment_update",
                "data": {
                    "segment": context.buyer.segment_id,
                    "confidence": round(context.buyer.segment_confidence, 2),
                    "profile_summary": self._build_profile_summary(context),
                },
            }

        # Step 9: Persist (post-processing updates)
        await self._persist_context(context)

        metrics.total_ms = (time.monotonic() - total_start) * 1000

        # Emit dynamic suggestion chips based on current state
        from homebuyer.services.faketor.jobs import suggest_chips
        has_property = bool(property_context)
        chips = suggest_chips(context, has_property=has_property)
        if chips:
            yield {
                "event": "suggestion_chips",
                "data": {"chips": chips},
            }

        # Emit done event
        yield {
            "event": "done",
            "data": {
                "reply": reply,
                "tool_calls": tool_calls_log,
                "blocks": blocks,
            },
        }

        logger.info(
            "Turn (stream) completed: user=%s segment=%s request=%s tools=%d time=%.0fms",
            user_id,
            context.buyer.segment_id,
            plan.request_type.value,
            len(metrics.tools_used),
            metrics.total_ms,
        )
